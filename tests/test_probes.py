"""Hardware- and cache-backed lookups for the settings window.

Only the parts that can be checked without a microphone or a GPU: repo resolution, the model
catalogue's shape, and the pill preview. The rest degrades to an empty answer rather than
raising, which is itself worth pinning.
"""

import pytest

from ghostwriter.settings import probes


# --- repo resolution ---------------------------------------------------------


def test_our_alias_table_wins_over_faster_whispers():
    # transcribe.MODEL_ALIASES points large-v3-turbo at a different repo than faster-whisper's
    # own table does. Resolving in the wrong order would report the wrong download as present.
    from ghostwriter.transcribe import MODEL_ALIASES

    assert probes.repo_for("large-v3-turbo") == MODEL_ALIASES["large-v3-turbo"]
    assert probes.repo_for("large-v3-turbo") != "Systran/faster-whisper-large-v3"


def test_faster_whispers_table_covers_the_plain_names():
    assert probes.repo_for("tiny.en") == "Systran/faster-whisper-tiny.en"
    assert probes.repo_for("small.en") == "Systran/faster-whisper-small.en"


def test_an_unknown_name_is_treated_as_a_repo_id():
    # Someone may put a Hugging Face repo id straight into config.toml.
    assert probes.repo_for("someone/custom-ct2-model") == "someone/custom-ct2-model"


def test_every_offered_model_resolves_to_a_repo():
    for name in probes.MODEL_SIZES:
        assert probes.repo_for(name), f"{name} does not resolve"


# --- catalogue ---------------------------------------------------------------


def test_the_catalogue_marks_exactly_one_model_current():
    catalogue = probes.model_catalog("small.en")
    assert sum(1 for model in catalogue if model["current"]) == 1
    assert next(m for m in catalogue if m["current"])["name"] == "small.en"


def test_a_model_named_only_in_config_is_still_listed():
    # Otherwise the tab would show nothing selected and silently offer to change it.
    catalogue = probes.model_catalog("someone/custom-ct2-model")
    names = [model["name"] for model in catalogue]
    assert "someone/custom-ct2-model" in names
    assert next(m for m in catalogue if m["current"])["name"] == "someone/custom-ct2-model"


def test_every_entry_has_what_the_tab_needs():
    for model in probes.model_catalog("tiny.en"):
        assert set(model) >= {"name", "repo", "size", "downloaded", "current"}
        assert isinstance(model["downloaded"], bool)


def test_an_unreadable_cache_reports_nothing_rather_than_raising(monkeypatch):
    # "We cannot tell what is downloaded" must degrade to an unmarked list, not a crash
    # halfway through rendering the tab.
    import huggingface_hub

    def explode(*_args, **_kwargs):
        raise OSError("cache unreadable")

    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", explode)
    assert probes.downloaded_repos() == set()
    assert all(not model["downloaded"] for model in probes.model_catalog("tiny.en"))


# --- gpu ---------------------------------------------------------------------


def test_gpu_info_reports_a_shape_the_badge_can_use():
    info = probes.gpu_info()
    assert set(info) == {"cuda", "devices"}
    assert isinstance(info["cuda"], bool)
    assert isinstance(info["devices"], int)


# --- pill preview ------------------------------------------------------------


def test_the_preview_is_rendered_by_the_real_pill():
    image = probes.pill_preview("#a855f7")
    assert image is not None
    assert image.startswith("data:image/png;base64,")
    assert len(image) > 2000, "a real render, not a blank"


def test_the_preview_differs_by_accent():
    # If it did not, the Look tab would be lying about what a colour does.
    assert probes.pill_preview("#38bdf8") != probes.pill_preview("#ef4444")


def test_the_preview_differs_by_state():
    assert probes.pill_preview("#38bdf8", "recording") != probes.pill_preview("#38bdf8", "done")


def test_a_bad_accent_returns_nothing_rather_than_raising():
    # A preview is a nicety; a half-typed hex must not take the tab down.
    assert probes.pill_preview("not-a-colour") is None


# --- devices -----------------------------------------------------------------


def test_the_device_list_always_offers_the_system_default():
    devices = probes.input_devices()
    assert devices, "expected at least the system default entry"
    assert devices[0]["index"] is None
    assert devices[0]["name"] == "System default"


def test_the_device_list_survives_a_missing_audio_backend(monkeypatch):
    import sounddevice

    monkeypatch.setattr(
        sounddevice, "query_devices", lambda *a, **k: (_ for _ in ()).throw(OSError("no audio"))
    )
    assert probes.input_devices() == []
