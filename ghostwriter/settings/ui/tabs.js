/* The seven tabs. Each renders into its panel once the config has loaded.
 *
 * Wrapped in an IIFE: classic scripts share one global scope, and these names (el, card, row…)
 * are also declared at the top level of controls.js.
 */

"use strict";

(function () {

const {
  el, card, row, sectionTitle, advanced, toggle, slider, field, numberField,
  select, segmented, chips, colour, keyCapture,
} = window.ui;

const panel = (name) => document.querySelector(`.panel[data-panel="${name}"]`);

function fill(name, ...nodes) {
  const target = panel(name);
  target.querySelector(".stub")?.remove();
  target.querySelectorAll(".built").forEach((node) => node.remove());
  const wrap = el("div", { class: "built" }, ...nodes);
  target.append(wrap);
}

const PALETTE = ["#38bdf8", "#ef4444", "#22c55e", "#a855f7"];

/* --- Keys ---------------------------------------------------------------- */

/* Auto-start is the one control here that does not touch config.toml: it reads and writes
 * Windows itself, so what it shows is what will actually happen at the next logon. */
function autostartRow() {
  const note = el("div", { class: "note" }, "");
  const control = el("div", { class: "row-control" });

  const paint = (state) => {
    control.textContent = "";
    note.textContent = state.available
      ? "Runs with the privileges its hotkeys need, so they work over elevated windows too."
      : state.reason;
    if (!state.available) {
      control.append(el("span", { class: "unit" }, "unavailable"));
      return;
    }
    const button = el("button", {
      class: "toggle", type: "button", role: "switch",
      "aria-checked": String(state.enabled),
      onclick: async () => {
        button.disabled = true;
        const next = await window.pywebview.api.set_autostart(!state.enabled);
        button.disabled = false;
        paint(next);
        if (!next.ok && next.error) gw.say(next.error, "warn");
        else gw.say(next.enabled ? "Will start with Windows" : "Will not start with Windows", "ok");
      },
    }, el("span", { class: "toggle-knob" }));
    control.append(button);
  };

  window.pywebview.api.autostart_state().then(paint);

  return el("div", { class: "row" },
    el("div", { class: "row-text" },
      el("div", { class: "row-label" }, "Start with Windows"),
      note),
    control);
}

function renderKeys() {
  fill("keys",
    card(
      row("Push to talk",
        "Hold it while you speak. A bare Ctrl needs a double-tap first — it is the key held for every Ctrl+C.",
        keyCapture("hotkeys.push_to_talk")),
      row("Dictate and send", "Pastes the text, then presses Enter for you.",
        keyCapture("hotkeys.push_to_talk_send", { allowEmpty: true })),
      row("Hands-free toggle", "Press once to start, again to stop.",
        keyCapture("hotkeys.toggle")),
      row("Cancel", "Throws away the recording in progress. Never suppressed.",
        keyCapture("hotkeys.cancel")),
      row("Hide keys from other apps",
        "Swallows the keypress so nothing else reacts. Turn off if a binding fights a shortcut you need.",
        toggle("hotkeys.suppress")),
    ),
    card(autostartRow()),
    advanced("double-tap window 0.4s · matched on virtual-key codes, so left and right are distinct"),
  );
}

/* --- Wake word ----------------------------------------------------------- */

function renderWakeword() {
  const result = el("div", { class: "trial-result" }, "Say your phrase after pressing Try it.");
  const meter = el("div", { class: "trial-bar" }, el("i"));

  const tryIt = el("button", {
    type: "button", class: "button is-go",
    onclick: async () => {
      tryIt.disabled = true;
      tryIt.textContent = "Listening…";
      result.className = "trial-result";
      result.textContent = "Say your phrase now — 4 seconds.";
      try {
        const out = await window.pywebview.api.test_wake_word(4.0);
        if (!out.ok) {
          result.className = "trial-result is-bad";
          result.textContent = out.error || "The test could not run.";
        } else {
          meter.firstChild.style.width = `${Math.min(100, out.level * 900)}%`;
          const score = out.score.toFixed(2);
          result.className = "trial-result " + (out.matched ? "is-ok" : "is-warn");
          result.innerHTML = out.matched
            ? `Heard <b>“${out.heard}”</b> — match ${score}, above your ${out.threshold}. It would fire.`
            : `Heard <b>“${out.heard || "(nothing)"}”</b> — match ${score}, below your ${out.threshold}. It would not fire.`;
        }
      } finally {
        tryIt.disabled = false;
        tryIt.textContent = "Try it";
      }
    },
  }, "Try it");

  fill("wakeword",
    card(
      row("Listen for a wake word", "Start dictating without touching the keyboard.",
        toggle("wakeword.enabled")),
      row("The phrase", "Change it to anything. Nothing to retrain.",
        field("wakeword.phrase", { width: 180 })),
      el("div", { class: "sub" },
        el("div", { class: "sub-label" },
          "Also accept these — short invented names come back spelled several ways"),
        chips("wakeword.aliases", { placeholder: "add spelling" })),
    ),
    el("div", { class: "grid-3" },
      card(sectionTitle("How close a match"),
        slider("wakeword.threshold", {
          min: 0.4, max: 1, step: 0.01,
          ends: ["misses you less", "fires by accident less"],
        })),
      card(sectionTitle("What counts as speech"),
        slider("wakeword.vad_threshold", {
          min: 0.1, max: 0.95, step: 0.05,
          ends: ["any sound", "clear speech only"],
        })),
      card(sectionTitle("Wait after firing"),
        el("div", { class: "inline" },
          numberField("wakeword.cooldown_sec", { min: 0, max: 30 }),
          el("span", { class: "unit" }, "seconds"))),
    ),
    card(
      el("div", { class: "trial" }, tryIt,
        el("div", { class: "trial-body" }, meter, result)),
    ),
    advanced("decoded by tiny.en on the CPU · the GPU stays free for dictation"),
  );
}

/* --- Model --------------------------------------------------------------- */

async function renderModel() {
  const list = el("div", { class: "list" }, el("div", { class: "list-empty" }, "Reading the model cache…"));
  const badge = el("div", { class: "badge" }, "checking…");

  fill("model",
    el("div", { class: "head-row" },
      el("div", {},
        el("div", { class: "section-title" }, "Which model transcribes you"),
        el("div", { class: "section-hint" }, "Bigger models hear you better and take longer.")),
      badge),
    list,
    el("div", { class: "grid-2" },
      card(sectionTitle("Run it on"),
        segmented("model.device", [["cuda", "Graphics card"], ["cpu", "Processor"]]),
        el("div", { class: "note" },
          "On an RTX 50-series card the compute type must be float16; int8_float16 crashes cuBLAS."),
        el("div", { class: "inline" },
          el("span", { class: "unit" }, "compute"),
          select("model.compute_type", [
            ["float16", "float16"], ["int8_float16", "int8_float16"], ["int8", "int8"],
          ]))),
      card(sectionTitle("Words it keeps getting wrong",
        "Fed to the model as a hint. Prefer this over find-and-replace where it works."),
        chips("model.vocabulary", { placeholder: "add word" }))),
    advanced("changing the model needs a restart — the loaded one keeps working until then"),
  );

  const data = await window.pywebview.api.model_catalog();
  badge.textContent = data.gpu.cuda
    ? `GPU available · ${data.gpu.devices} device${data.gpu.devices === 1 ? "" : "s"}`
    : "No GPU found — running on the processor";
  badge.className = "badge " + (data.gpu.cuda ? "is-ok" : "is-warn");

  list.textContent = "";
  for (const model of data.models) {
    const choose = async () => {
      if (await gw.commit({ "model.name": model.name })) renderModel();
    };
    list.append(el("button", {
      type: "button",
      class: "list-row" + (model.current ? " is-on" : ""),
      onclick: choose,
    },
      el("span", { class: "radio" }),
      el("span", { class: "list-name mono" }, model.name),
      // Always present, even when empty: it is the flex spacer that keeps the size and state
      // columns aligned down the list.
      el("span", { class: "list-note" }, model.note || ""),
      el("span", { class: "list-size mono" }, model.size),
      el("span", { class: "list-state " + (model.downloaded ? "is-ok" : "") },
        model.downloaded ? "downloaded" : "downloads on next use"),
    ));
  }
}

/* --- Stopping ------------------------------------------------------------ */

function renderStopping() {
  const inline = (path, opts) => numberField(path, { width: 56, ...opts });

  fill("stopping",
    card(
      el("p", { class: "sentence" },
        "Stop after ", inline("endpoint.silence_timeout_sec", { min: 0.1, max: 10 }),
        " seconds of quiet, but never before ",
        inline("endpoint.min_recording_sec", { min: 0, max: 120 }),
        " seconds have passed — a pause to think, or taking a moment to start, will not cut you off. ",
        "Give up after ", inline("endpoint.lead_in_sec", { min: 0.2, max: 30 }),
        " seconds if I never speak, and stop no matter what at ",
        inline("endpoint.max_duration_sec", { min: 5, max: 600 }), " seconds."),
      el("div", { class: "note" },
        "Only hands-free dictation uses these. Push-to-talk ends when you let go of the key."),
    ),
    el("div", { class: "grid-2" },
      card(sectionTitle("What counts as you still talking"),
        slider("endpoint.vad_threshold", {
          min: 0.1, max: 0.95, step: 0.05,
          ends: ["cuts off less", "holds open less"],
        }),
        el("div", { class: "note" },
          "Raise it if a noisy room keeps the recording open; lower it if you get cut off mid-sentence. ",
          el("button", {
            type: "button", class: "linkish",
            onclick: () => gw.showTab("mic"),
          }, "Measure my room →"))),
      card(sectionTitle("Stopping early"),
        row("Stop now key", "Ends it and types straight away.",
          keyCapture("endpoint.stop_key")),
        row("Ignore blips shorter than", "So a cough does not start a sentence.",
          el("div", { class: "inline" },
            numberField("endpoint.min_speech_sec", { min: 0.05, max: 3 }),
            el("span", { class: "unit" }, "seconds"))))),
    advanced("fallback loudness gate, used only if the speech model will not load: " +
      String(gw.value("endpoint.silence_threshold"))),
  );
}

/* --- Look ---------------------------------------------------------------- */

function renderLook() {
  const preview = el("img", { class: "pill-preview", alt: "Preview of the status pill" });
  const previewNote = el("div", { class: "note" }, "Rendered by the real pill, not an imitation.");
  let previewState = "recording";

  const drawPreview = async () => {
    const out = await window.pywebview.api.pill_preview(gw.value("overlay.accent"), previewState);
    if (out.image) preview.src = out.image;
  };

  const stateChips = el("div", { class: "state-chips" },
    ...[["recording", "Recording"], ["idle", "Waiting"], ["transcribing", "Writing"],
        ["done", "Pasted"], ["error", "Failed"]].map(([value, label]) =>
      el("button", {
        type: "button",
        class: "state-chip" + (value === previewState ? " is-on" : ""),
        onclick: (event) => {
          previewState = value;
          for (const chip of stateChips.children) chip.classList.remove("is-on");
          event.currentTarget.classList.add("is-on");
          drawPreview();
        },
      }, label)));

  fill("look",
    el("div", { class: "grid-2" },
      el("div", {},
        card(sectionTitle("Recording colour",
          "The pill and the ripple both wear it."),
          colour("overlay.accent", { palette: PALETTE, onChange: drawPreview })),
        card(sectionTitle("Other states keep their meaning"),
          ...[["idle", "Waiting"], ["transcribing", "Writing it down"],
              ["done", "Pasted"], ["error", "Something went wrong"]].map(([key, label]) =>
            row(label, null, colour(`overlay.colors.${key}`, {}))))),
      el("div", {},
        card(el("div", { class: "preview-stage" }, preview),
          stateChips, previewNote),
        card(
          row("The ripple across the screen",
            "Like a droplet landing on water when recording starts.",
            toggle("overlay.wave.enabled")),
          sectionTitle("How fast it crosses"),
          slider("overlay.wave.duration_ms", {
            min: 400, max: 4000, step: 50, format: (v) => `${(v / 1000).toFixed(2)} s`,
          }),
          sectionTitle("How bright"),
          slider("overlay.wave.intensity", { min: 0.1, max: 3, step: 0.05 }),
          sectionTitle("How many ripples"),
          slider("overlay.wave.wavelength", {
            min: 10, max: 300, step: 2, format: (v) => `${v} px apart`,
          })))),
    advanced("crest colours follow the accent · set overlay.wave.halos/cores in config.toml to pin them"),
  );

  drawPreview();
}

/* --- Text ---------------------------------------------------------------- */

function renderText() {
  const table = el("div", { class: "pairs" });

  const paint = () => {
    table.textContent = "";
    const pairs = gw.value("postprocess.replacements") || {};
    const write = async (next) => {
      if (await gw.commit({ "postprocess.replacements": next })) paint();
    };

    for (const [wrong, right] of Object.entries(pairs)) {
      table.append(el("div", { class: "pair" },
        el("span", { class: "pair-from mono" }, wrong),
        el("span", { class: "pair-arrow" }, "→"),
        el("span", { class: "pair-to mono" }, right),
        el("button", {
          type: "button", class: "chip-x", title: `Remove ${wrong}`,
          onclick: () => {
            const next = { ...pairs };
            delete next[wrong];
            write(next);
          },
        }, "✕")));
    }

    const from = el("input", { class: "field mono", placeholder: "it hears…", style: "min-width:140px" });
    const to = el("input", { class: "field mono", placeholder: "write this", style: "min-width:140px" });
    const add = () => {
      const a = from.value.trim(), b = to.value.trim();
      if (!a || !b) return;
      write({ ...pairs, [a]: b });
    };
    for (const input of [from, to]) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); add(); }
      });
    }
    table.append(el("div", { class: "pair is-new" }, from,
      el("span", { class: "pair-arrow" }, "→"), to,
      el("button", { type: "button", class: "button is-small", onclick: add }, "Add")));
  };

  paint();
  document.addEventListener("refreshed", paint);

  fill("text",
    card(
      row("Strip filler words", "“um”, “uh”, “you know”…", toggle("postprocess.remove_fillers")),
      row("Spoken punctuation", "“comma”, “new line”, “open paren”…", toggle("postprocess.voice_commands")),
      row("Tidy sentences", "Capitalise the first letter, add a full stop.", toggle("postprocess.tidy_sentences")),
    ),
    card(sectionTitle("Corrections",
      "Applied last, after everything else. Good for names the model mangles."), table),
    card(
      row("How the text arrives",
        "Pasting is more reliable and handles Unicode; typing suits apps that block paste.",
        segmented("output.paste", [[true, "Paste"], [false, "Type it out"]])),
      row("Clipboard restore delay", "Raise it if pastes come out empty.",
        el("div", { class: "inline" },
          numberField("output.clipboard_restore_delay", { min: 0, max: 5 }),
          el("span", { class: "unit" }, "seconds"))),
      row("Sounds", "A short beep when recording starts and stops.", toggle("output.sounds")),
    ),
  );
}

/* --- Mic ----------------------------------------------------------------- */

let meterTimer = null;

function renderMic() {
  const bars = el("div", { class: "meter" },
    ...Array.from({ length: 22 }, () => el("i")));
  const verdict = el("span", { class: "meter-verdict" }, "—");
  const results = el("div", { class: "room" });

  const devicePicker = el("select", { class: "select", style: "min-width:260px" });
  const paintDevices = async () => {
    const devices = await window.pywebview.api.input_devices();
    devicePicker.textContent = "";
    const current = gw.value("audio.device") || "";
    for (const device of devices) {
      const value = device.index === null ? "" : device.name;
      devicePicker.append(el("option", {
        value, selected: value === current ? "" : null,
      }, device.name));
    }
  };
  devicePicker.addEventListener("change", async () => {
    if (await gw.commit({ "audio.device": devicePicker.value })) restartMeter();
  });

  const restartMeter = async () => {
    await window.pywebview.api.start_meter(gw.value("audio.device") || "");
  };

  const paintMeter = async () => {
    let reading;
    try {
      reading = await window.pywebview.api.meter();
    } catch { return; }
    // Speech sits well under 0.2, so scale for that rather than for full scale.
    const lit = Math.min(bars.children.length, Math.round(reading.peak * 8 * bars.children.length));
    [...bars.children].forEach((bar, index) => {
      bar.className = index < lit
        ? (index > 19 ? "is-hot" : index > 17 ? "is-warm" : "is-on")
        : "";
    });
    verdict.textContent = reading.peak < 0.004 ? "very quiet"
      : reading.peak < 0.02 ? "quiet"
      : reading.peak < 0.15 ? "good level" : "loud";
    verdict.className = "meter-verdict " + (reading.peak >= 0.02 && reading.peak < 0.15 ? "is-ok" : "");
  };

  const runCheck = el("button", {
    type: "button", class: "button",
    onclick: async () => {
      runCheck.disabled = true;
      results.className = "room is-busy";
      results.textContent = "Stay silent…";
      const poll = setInterval(async () => {
        try {
          const p = await window.pywebview.api.room_check_progress();
          if (p.phase === "quiet") results.textContent = `Stay silent… ${p.remaining}`;
          else if (p.phase === "talking") results.textContent = `Now talk… ${p.remaining}`;
        } catch { /* window closing */ }
      }, 400);
      try {
        const out = await window.pywebview.api.room_check(6.0);
        clearInterval(poll);
        paintRoom(out);
      } finally {
        clearInterval(poll);
        runCheck.disabled = false;
      }
    },
  }, "Check my room");

  const paintRoom = (out) => {
    results.className = "room";
    if (!out.ok) {
      results.className = "room is-bad";
      results.textContent = out.error;
      return;
    }
    const stat = (label, value) =>
      el("div", { class: "stat" },
        el("div", { class: "stat-label" }, label),
        el("div", { class: "stat-value mono" }, value));

    const apply = Object.keys(out.suggestions || {}).length
      ? el("div", { class: "room-actions" },
          el("button", {
            type: "button", class: "button is-small is-primary",
            onclick: async () => {
              if (await gw.commit(out.suggestions)) paintRoom({ ...out, suggestions: {} });
            },
          }, "Use these"),
          el("button", {
            type: "button", class: "button is-small",
            onclick: () => paintRoom({ ...out, suggestions: {} }),
          }, "Leave as is"))
      : null;

    const suggestionText = Object.entries(out.suggestions || {})
      .map(([key, value]) => `${key.split(".").pop()} → ${value} (now ${gw.value(key)})`)
      .join(", ");

    results.append(
      el("div", { class: "stats" },
        stat("background noise", out.quietRms.toFixed(4)),
        stat("your voice", out.talkingRms.toFixed(4)),
        stat("headroom", `${out.headroom.toFixed(0)}×`),
        stat("longest quiet", `${out.longestQuiet.toFixed(2)}s / ${out.neededQuiet.toFixed(2)}s`)),
      el("div", { class: "room-verdict " + (out.verdict === "fine" ? "is-ok" : "is-warn") },
        out.verdict === "fine" ? "Dictation will stop on its own when you stop talking." : out.message),
      suggestionText ? el("div", { class: "note" }, `Suggested: ${suggestionText}`) : null,
      apply);
  };

  fill("mic",
    card(
      row("Listening to", "Empty means whatever Windows is using.", devicePicker),
      el("div", { class: "meter-row" },
        el("span", { class: "unit" }, "level"), bars, verdict)),
    card(
      el("div", { class: "head-row" },
        el("div", {},
          el("div", { class: "section-title" }, "Check my room"),
          el("div", { class: "section-hint" },
            "Six seconds of silence, then six of you talking. Then it suggests settings that suit it.")),
        runCheck),
      results),
    card(
      row("Trim silence before transcribing", "Skips non-speech chunks, so decoding is quicker.",
        toggle("audio.vad")),
      row("Discard recordings shorter than", "Catches an accidental key tap.",
        el("div", { class: "inline" },
          numberField("audio.min_duration_sec", { min: 0, max: 5 }),
          el("span", { class: "unit" }, "seconds")))),
    advanced("16 kHz mono · hard cap " + gw.value("audio.max_duration_sec") + "s per recording"),
  );

  paintDevices();
  restartMeter();
  clearInterval(meterTimer);
  meterTimer = setInterval(paintMeter, 120);
}

/* --- wiring -------------------------------------------------------------- */

const RENDER = {
  keys: renderKeys, wakeword: renderWakeword, model: renderModel,
  stopping: renderStopping, look: renderLook, text: renderText, mic: renderMic,
};

const built = new Set();

function build(name) {
  if (built.has(name)) return;
  built.add(name);
  try {
    RENDER[name]();
  } catch (error) {
    built.delete(name);
    console.error(`could not build the ${name} tab`, error);
    gw.say(`The ${name} tab failed to render — see the console`, "bad");
  }
}

/* The mic tab holds a microphone open. Release it the moment it is not on screen. */
document.addEventListener("tabshown", async ({ detail }) => {
  build(detail.name);
  if (detail.name !== "mic") {
    clearInterval(meterTimer);
    meterTimer = null;
    try { await window.pywebview.api.stop_meter(); } catch { /* closing */ }
  } else if (!meterTimer) {
    renderMic();
  }
});

document.addEventListener("ready", () => build("keys"));

window.addEventListener("beforeunload", () => {
  try { window.pywebview.api.close_probes(); } catch { /* closing */ }
});
})();
