"""Entry point: wires hotkeys, recorder, transcription worker, overlay and tray together."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import winsound
from pathlib import Path

import keyboard
import numpy as np

from . import config as config_module
from . import inject, postprocess
from .audio import Recorder
from .endpoint import SilenceEndpointer
from .hotkeys import HotkeyManager
from .overlay import Overlay
from .transcribe import Transcriber
from .wakeword import WakeWordListener
from .wakeword_whisper import WhisperWakeWordListener

log = logging.getLogger("Ghostwriter")


def beep(kind: str) -> None:
    tones = {"start": (880, 60), "stop": (620, 60), "error": (300, 160)}
    freq, ms = tones.get(kind, (700, 60))
    threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


class App:
    def __init__(self, cfg_path: Path | None = None):
        self.cfg = config_module.load(cfg_path)
        self.sounds = self.cfg.get("output.sounds", True)
        self.min_duration = self.cfg.get("audio.min_duration_sec", 0.35)

        self.recorder = Recorder(
            sample_rate=self.cfg.get("audio.sample_rate", 16000),
            device=self.cfg.get("audio.device", ""),
            max_seconds=self.cfg.get("audio.max_duration_sec", 300.0),
        )
        self.overlay = Overlay(level_source=lambda: self.recorder.level)
        self.jobs: queue.Queue[tuple[np.ndarray, str] | None] = queue.Queue()
        self.transcriber: Transcriber | None = None
        self.model_ready = threading.Event()
        self.toggle_active = False
        self.cancelled = False
        self.wake_active = False
        self._stop_requested = False
        self._stop_key_handle = None

        self.endpointer = SilenceEndpointer(
            level_source=lambda: self.recorder.level,
            silence_timeout=self.cfg.get("endpoint.silence_timeout_sec", 1.2),
            threshold=self.cfg.get("endpoint.silence_threshold", 0.012),
            min_speech=self.cfg.get("endpoint.min_speech_sec", 0.4),
            lead_in=self.cfg.get("endpoint.lead_in_sec", 2.0),
            max_duration=self.cfg.get("endpoint.max_duration_sec", 60.0),
        )
        self.wake = self._build_wake() if self.cfg.get("wakeword.enabled", True) else None

        self.hotkeys = HotkeyManager(
            on_press=self.start_recording,
            on_release=self.finish_recording,
            on_toggle=self.handle_toggle,
            on_cancel=self.cancel_recording,
        )

    def _build_wake(self):
        """Pick the wake-word backend. The default needs no trained model."""
        if self.cfg.get("wakeword.backend", "whisper") == "openwakeword":
            return WakeWordListener(
                on_detect=self.on_wake,
                model_path=self.cfg.get("wakeword.model_path", ""),
                fallback_model=self.cfg.get("wakeword.fallback_model", "hey_jarvis"),
                threshold=self.cfg.get("wakeword.threshold", 0.5),
                cooldown_sec=self.cfg.get("wakeword.cooldown_sec", 2.0),
                device=self.cfg.get("audio.device", ""),
            )
        return WhisperWakeWordListener(
            on_detect=self.on_wake,
            phrase=self.cfg.get("wakeword.phrase", "hey ghost"),
            aliases=self.cfg.get("wakeword.aliases", []),
            model_name=self.cfg.get("wakeword.model", "tiny.en"),
            device_type=self.cfg.get("wakeword.device", "cpu"),
            compute_type=self.cfg.get("wakeword.compute_type", "int8"),
            threshold=self.cfg.get("wakeword.threshold", 0.8),
            vad_threshold=self.cfg.get("wakeword.vad_threshold", 0.5),
            cooldown_sec=self.cfg.get("wakeword.cooldown_sec", 2.0),
            device=self.cfg.get("audio.device", ""),
        )

    # --- model -----------------------------------------------------------

    def load_model(self) -> None:
        self.overlay.set_state("transcribing", "Loading model...")
        try:
            self.transcriber = Transcriber(
                name=self.cfg.get("model.name"),
                device=self.cfg.get("model.device"),
                compute_type=self.cfg.get("model.compute_type"),
                language=self.cfg.get("model.language"),
                vocabulary=self.cfg.get("model.vocabulary", []),
                vad=self.cfg.get("audio.vad", True),
            )
            self.model_ready.set()
            self.overlay.set_state("done", "Ready")
        except Exception:
            log.exception("model load failed")
            self.overlay.set_state("error", "Model load failed")

    # --- recording -------------------------------------------------------

    def start_recording(self, mode: str = "paste") -> None:
        if self.recorder.recording:
            return
        self.cancelled = False
        # The listener must let go of the microphone before the recorder claims it.
        if self.wake is not None:
            self.wake.pause()
        self.recorder.start()
        self.overlay.set_state("recording")
        if self.sounds:
            beep("start")

    def finish_recording(self, mode: str = "paste") -> None:
        if not self.recorder.recording:
            return
        audio = self.recorder.stop()
        if self.wake is not None:
            self.wake.resume()
        if self.sounds:
            beep("stop")
        if self.cancelled:
            self.overlay.set_state("idle")
            return
        seconds = len(audio) / self.recorder.sample_rate
        if seconds < self.min_duration:
            self.overlay.set_state("idle")
            return
        self.overlay.set_state("transcribing")
        self.jobs.put((audio, mode))

    def handle_toggle(self) -> None:
        if self.toggle_active:
            self.toggle_active = False
            self.finish_recording("paste")
        else:
            self.toggle_active = True
            self.start_recording("paste")

    def cancel_recording(self) -> None:
        if not self.recorder.recording:
            return
        self.cancelled = True
        self.toggle_active = False
        self.recorder.stop()
        if self.wake is not None:
            self.wake.resume()
        self.overlay.set_state("idle")

    # --- wake word -------------------------------------------------------

    def on_wake(self) -> None:
        """Called from the listener thread when the wake phrase fires."""
        if self.recorder.recording:
            return
        threading.Thread(target=self._wake_utterance, daemon=True).start()

    def _wake_utterance(self) -> None:
        self.wake_active = True
        self._stop_requested = False
        self._bind_stop_key()
        try:
            self.start_recording("paste")
            reason = self.endpointer.wait(cancelled=lambda: not self.wake_active)
            if self._stop_requested:
                reason = "stop_key"
            log.info("hands-free utterance ended: %s", reason)
            if reason == "no_speech":
                # You said the wake word but never followed up; drop it silently.
                self.cancelled = True
            self.finish_recording("paste")
        finally:
            self.wake_active = False
            self._unbind_stop_key()

    def _bind_stop_key(self) -> None:
        """Bind the manual stop key, but only for the duration of this utterance."""
        key = self.cfg.get("endpoint.stop_key")
        if not key or self._stop_key_handle is not None:
            return
        try:
            self._stop_key_handle = keyboard.add_hotkey(key, self._stop_now, suppress=True)
        except Exception:  # noqa: BLE001 - a bad key name shouldn't break dictation
            log.exception("could not bind stop key %r", key)

    def _unbind_stop_key(self) -> None:
        handle, self._stop_key_handle = self._stop_key_handle, None
        if handle is not None:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:  # noqa: BLE001
                pass

    def _stop_now(self) -> None:
        """Stop-key press: end the utterance now and transcribe what we have (not a cancel)."""
        self._stop_requested = True
        self.wake_active = False

    # --- worker ----------------------------------------------------------

    def worker(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            audio, mode = job
            try:
                self.process(audio, mode)
            except Exception:
                log.exception("transcription failed")
                self.overlay.set_state("error", "Transcription failed")
                if self.sounds:
                    beep("error")

    def process(self, audio: np.ndarray, mode: str) -> None:
        if not self.model_ready.wait(timeout=120):
            self.overlay.set_state("error", "Model not ready")
            return
        assert self.transcriber is not None
        raw = self.transcriber.transcribe(audio)
        text = postprocess.clean(raw, self.cfg.get("postprocess", {}))
        if not text:
            self.overlay.set_state("idle")
            return
        log.info("transcript (%s): %s", mode, text)
        send = mode == "send"
        if self.cfg.get("output.paste", True):
            inject.paste_text(
                text,
                press_enter=send,
                restore_delay=self.cfg.get("output.clipboard_restore_delay", 0.35),
            )
        else:
            inject.type_text(text, press_enter=send)
        self.overlay.set_state("done", text)

    # --- tray ------------------------------------------------------------

    def build_tray(self):
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (64, 64), "#0b0f19")
        draw = ImageDraw.Draw(image)
        draw.ellipse((18, 8, 46, 40), fill="#22c55e")
        draw.rectangle((30, 40, 34, 50), fill="#22c55e")
        draw.rectangle((20, 50, 44, 54), fill="#22c55e")

        items = [
            pystray.MenuItem(
                f"Hold {self.cfg.get('hotkeys.push_to_talk')} to dictate", None, enabled=False
            )
        ]
        if self.cfg.get("hotkeys.push_to_talk_send"):
            items.append(
                pystray.MenuItem(
                    f"Hold {self.cfg.get('hotkeys.push_to_talk_send')} to dictate + Enter",
                    None,
                    enabled=False,
                )
            )
        if self.wake is not None:
            items.append(
                pystray.MenuItem(
                    lambda item: f'Listening for "{self.wake_phrase()}"',  # noqa: ARG005
                    self.toggle_listening,
                    checked=lambda item: self.wake is not None and self.wake.listening,  # noqa: ARG005
                )
            )
        items += [
            pystray.MenuItem("Move overlay", self.move_overlay),
            pystray.MenuItem("Open config.toml", self.open_config),
            pystray.MenuItem("Quit", self.quit),
        ]
        return pystray.Icon("Ghostwriter", image, "Ghostwriter", pystray.Menu(*items))

    def start_listening(self) -> None:
        if self.wake is None:
            return
        try:
            self.wake.start()
        except Exception:  # noqa: BLE001 - no microphone shouldn't stop the hotkeys working
            log.exception("wake-word listener failed to start")
            self.wake = None

    def wake_phrase(self) -> str:
        """Human-readable phrase, derived from whichever model actually loaded.

        Until a custom model is trained this is the fallback's name, so the UI never claims to
        answer to a phrase it can't hear.
        """
        if self.wake is None:
            return ""
        return self.wake.model_name.replace("_", " ")

    def toggle_listening(self, icon=None, item=None) -> None:  # noqa: ARG002 - pystray signature
        if self.wake is None:
            return
        if self.wake.listening:
            self.wake.stop()
            self.overlay.set_state("done", "Wake word off")
        else:
            self.wake.start()
            self.overlay.set_state("done", f'Listening for "{self.wake_phrase()}"')

    def move_overlay(self, icon=None, item=None) -> None:  # noqa: ARG002 - pystray signature
        self.overlay.start_move()

    def open_config(self) -> None:
        import os

        os.startfile(str(self.cfg.path))  # noqa: S606 - opening the user's own config

    def quit(self, icon=None, item=None) -> None:  # noqa: ARG002 - pystray callback signature
        self.jobs.put(None)
        if self.wake is not None:
            self.wake.stop()
        self.hotkeys.unregister()
        if icon is not None:
            icon.stop()
        self.overlay.quit()

    # --- run -------------------------------------------------------------

    def run(self) -> None:
        threading.Thread(target=self.load_model, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        self.hotkeys.register(self.cfg.get("hotkeys", {}))
        # Before build_tray, since a failed listener clears self.wake and drops its menu item.
        self.start_listening()
        self.tray = self.build_tray()
        threading.Thread(target=self.tray.run, daemon=True).start()
        lines = [
            "Ghostwriter running.",
            f"  Hold {self.cfg.get('hotkeys.push_to_talk')} to dictate",
        ]
        if self.cfg.get("hotkeys.push_to_talk_send"):
            lines.append(
                f"  Hold {self.cfg.get('hotkeys.push_to_talk_send')} to dictate and press Enter"
            )
        if self.wake is not None:
            lines.append(
                f'  Say "{self.wake_phrase()}" to dictate hands-free '
                f"(stop with silence or {self.cfg.get('endpoint.stop_key')})"
            )
            if self.wake.using_fallback:
                lines.append(
                    "  NOTE: openWakeWord backend is using its pretrained fallback phrase - "
                    "set wakeword.backend = \"whisper\" for the real phrase, no training needed"
                )
        lines += [
            f"  {self.cfg.get('hotkeys.toggle')} toggles hands-free mode",
            f"  {self.cfg.get('hotkeys.cancel')} cancels a recording",
        ]
        print("\n".join(lines), flush=True)
        self.overlay.run()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    App(cfg_path).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
