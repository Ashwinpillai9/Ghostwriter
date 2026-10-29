"""Paths, auto-start, and the first-run bootstrap.

These are the three places a frozen build and a source checkout genuinely differ, so they are
the three most likely to drift. Everything here stubs the operating system: no tasks are
registered, nothing is downloaded, and no GPU is required.
"""

import ctypes
import hashlib
import io
import json
import subprocess
import zipfile

import pytest
from packaging.requirements import Requirement

from ghostwriter import autostart, bootstrap, paths


class Result:
    """Stands in for a CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def as_frozen(monkeypatch, tmp_path):
    """Pretend to be an installed build, with its own APPDATA."""
    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    return tmp_path


# --- paths -------------------------------------------------------------------


def test_from_source_everything_stays_in_the_checkout():
    assert paths.frozen() is False
    assert paths.config_path() == paths.program_dir() / "config.toml"


def test_installed_config_lives_outside_the_program_directory(as_frozen):
    # An update replaces the program directory wholesale, so nothing the user owns may be in it.
    assert "roaming" in str(paths.config_path()).lower()
    assert paths.config_path().name == "config.toml"
    assert paths.program_dir() not in paths.config_path().parents


def test_the_fetched_runtime_survives_an_update(as_frozen):
    # ~2 GB fetched for this machine; re-downloading it on every update would be absurd.
    assert paths.program_dir() not in paths.runtime_dir().parents


# --- launching the settings window -------------------------------------------


def test_from_source_the_settings_window_is_a_module(tmp_path):
    command = paths.launch_settings_command(tmp_path / "config.toml")
    assert command[1:3] == ["-m", "ghostwriter.settings"]


def test_frozen_the_settings_window_is_a_flag(as_frozen, tmp_path):
    # A frozen build has no `python -m`; sys.executable is Ghostwriter.exe. Getting this wrong
    # is why the settings window would have been broken in any packaged build.
    command = paths.launch_settings_command(tmp_path / "config.toml")
    assert "-m" not in command
    assert command[1] == "--settings"


def test_the_config_path_is_passed_either_way(as_frozen, tmp_path):
    target = tmp_path / "somewhere" / "config.toml"
    assert str(target) == paths.launch_settings_command(target)[-1]


# --- auto-start --------------------------------------------------------------


def test_auto_start_is_unavailable_from_source():
    # The command would point into a virtual environment that exists only on this machine.
    assert autostart.available() is False
    assert "installed build" in autostart.reason_unavailable()


def test_enabling_from_source_is_refused_not_attempted(monkeypatch):
    called = []
    monkeypatch.setattr(autostart, "_run_elevated", lambda args: called.append(args))
    ok, message = autostart.enable()
    assert ok is False
    assert called == [], "must not touch Task Scheduler when it cannot work"
    assert message


def test_enabling_registers_a_logon_task_with_highest_privileges(as_frozen, monkeypatch):
    seen = {}

    def record(args):
        seen["args"] = args
        return autostart._ElevatedResult(declined=False, returncode=0)

    monkeypatch.setattr(autostart, "_run_elevated", record)

    ok, message = autostart.enable()
    assert ok is True and message == ""

    args = seen["args"]
    assert "/create" in args
    assert args[args.index("/sc") + 1] == "onlogon"
    # The whole reason for a task rather than a Run key: without this the hotkeys stay dead
    # over elevated windows.
    assert args[args.index("/rl") + 1] == "highest"


def test_declined_elevation_is_reported_not_raised(as_frozen, monkeypatch):
    # What ShellExecuteExW reports when the user dismisses the UAC prompt itself.
    monkeypatch.setattr(autostart, "_run_elevated",
                         lambda args: autostart._ElevatedResult(declined=True, returncode=None))
    ok, message = autostart.enable()
    assert ok is False
    assert "administrator" in message.lower()


def test_a_missing_schtasks_does_not_raise(as_frozen, monkeypatch):
    def explode(_args):
        raise OSError("schtasks not found")

    monkeypatch.setattr(autostart, "_run_elevated", explode)
    monkeypatch.setattr(autostart, "_run", explode)
    assert autostart.enable()[0] is False
    assert autostart.is_enabled() is False


def test_state_is_read_from_windows_every_time(as_frozen, monkeypatch):
    answers = iter([Result(returncode=0), Result(returncode=1)])
    monkeypatch.setattr(autostart, "_run", lambda args: next(answers))

    assert autostart.is_enabled() is True
    # The user deleted the task in Task Scheduler between the two calls. A cached preference
    # would now be a lie.
    assert autostart.is_enabled() is False


def test_disabling_something_absent_succeeds_quietly(as_frozen, monkeypatch):
    monkeypatch.setattr(autostart, "_run", lambda args: Result(returncode=1))
    assert autostart.disable() == (True, "")


def test_state_reports_everything_the_control_needs(as_frozen, monkeypatch):
    monkeypatch.setattr(autostart, "_run", lambda args: Result(returncode=0))
    state = autostart.state()
    assert set(state) == {"available", "enabled", "reason", "target"}
    assert state["available"] is True and state["enabled"] is True


# --- the UAC elevation itself -------------------------------------------------
#
# `schtasks.exe` has no manifest asking Windows to elevate it, so a plain subprocess call is
# just refused — without ever showing the user a prompt. These exercise the ShellExecuteExW
# plumbing in `_run_elevated` that actually raises one.


def test_run_elevated_waits_and_reports_the_real_exit_code(monkeypatch):
    def fake_shell_execute(info_ptr):
        info_ptr.contents.hProcess = 4242
        return 1

    def fake_exit_code(_handle, code_ptr):
        code_ptr.contents.value = 0
        return 1

    closed = []
    monkeypatch.setattr(ctypes.windll.shell32, "ShellExecuteExW", fake_shell_execute)
    monkeypatch.setattr(ctypes.windll.kernel32, "WaitForSingleObject", lambda *a: 0)
    monkeypatch.setattr(ctypes.windll.kernel32, "GetExitCodeProcess", fake_exit_code)
    monkeypatch.setattr(ctypes.windll.kernel32, "CloseHandle",
                         lambda handle: closed.append(handle) or 1)

    result = autostart._run_elevated(["/query", "/tn", "Ghostwriter"])
    assert result.declined is False
    assert result.returncode == 0
    assert closed == [4242], "the process handle must be released"


def test_run_elevated_detects_a_declined_uac_prompt(monkeypatch):
    monkeypatch.setattr(ctypes.windll.shell32, "ShellExecuteExW", lambda info_ptr: 0)
    monkeypatch.setattr(ctypes.windll.kernel32, "GetLastError",
                         lambda: autostart._ERROR_CANCELLED)

    result = autostart._run_elevated(["/create"])
    assert result.declined is True
    assert result.returncode is None


def test_run_elevated_distinguishes_other_launch_failures(monkeypatch):
    monkeypatch.setattr(ctypes.windll.shell32, "ShellExecuteExW", lambda info_ptr: 0)
    monkeypatch.setattr(ctypes.windll.kernel32, "GetLastError", lambda: 2)  # file not found

    result = autostart._run_elevated(["/create"])
    assert result.declined is False
    assert result.returncode is None


# --- bootstrap ---------------------------------------------------------------


def test_no_nvidia_gpu_means_no_cuda_download(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: False)
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: False)
    fetched = []
    monkeypatch.setattr(bootstrap, "fetch_cuda", lambda *a, **k: fetched.append(1))
    monkeypatch.setattr(bootstrap, "fetch_model", lambda *a, **k: True)

    outcome = bootstrap.run("tiny.en", "cuda")
    assert fetched == [], "a machine that cannot use CUDA must never download 2 GB of it"
    assert outcome["model"] is True


def test_an_nvidia_gpu_gets_the_runtime(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: True)
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: False)
    monkeypatch.setattr(bootstrap, "fetch_cuda", lambda *a, **k: True)
    monkeypatch.setattr(bootstrap, "fetch_model", lambda *a, **k: True)
    assert bootstrap.run("tiny.en", "cuda")["cuda"] is True


def test_a_cpu_configuration_never_fetches_cuda(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: False)
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: True)
    fetched = []
    monkeypatch.setattr(bootstrap, "fetch_cuda", lambda *a, **k: fetched.append(1))
    monkeypatch.setattr(bootstrap, "fetch_model", lambda *a, **k: True)

    bootstrap.run("tiny.en", "cpu")
    assert fetched == []


# --- fetching the CUDA runtime directly from PyPI ----------------------------
#
# A frozen build has no pip and no standalone python.exe: `sys.executable` is Ghostwriter.exe
# itself. Running that with pip-style arguments doesn't invoke pip — it relaunches the whole
# app, which re-enters this same code and launches another copy, forever. These tests pin
# fetch_cuda to never shell out at all.


def _fake_pypi_response(name: str, versions: dict[str, list[str]]) -> bytes:
    """A minimal PyPI JSON payload: {version: [wheel filenames]}."""
    releases = {
        version: [{"filename": filename, "url": f"https://files/{filename}",
                   "digests": {"sha256": ""}} for filename in filenames]
        for version, filenames in versions.items()
    }
    return json.dumps({"releases": releases}).encode("utf-8")


def test_fetch_cuda_never_shells_out(as_frozen, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))

    assert bootstrap.fetch_cuda() is False
    assert calls == [], "fetch_cuda must never run a subprocess — see module docstring"


def test_best_wheel_picks_the_highest_matching_windows_wheel(monkeypatch):
    payload = _fake_pypi_response("nvidia-cublas-cu12", {
        "12.8.0": ["nvidia_cublas_cu12-12.8.0-py3-none-win_amd64.whl"],
        "12.9.1": ["nvidia_cublas_cu12-12.9.1-py3-none-win_amd64.whl",
                   "nvidia_cublas_cu12-12.9.1-py3-none-manylinux2014_x86_64.whl"],
        "12.1.0": ["nvidia_cublas_cu12-12.1.0-py3-none-win_amd64.whl"],  # below the specifier
    })
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: io.BytesIO(payload))

    requirement = Requirement("nvidia-cublas-cu12>=12.8")
    found = bootstrap._best_wheel(requirement.name, requirement.specifier)
    assert found["filename"] == "nvidia_cublas_cu12-12.9.1-py3-none-win_amd64.whl"


def test_best_wheel_returns_none_without_a_windows_wheel(monkeypatch):
    payload = _fake_pypi_response("nvidia-cublas-cu12", {
        "12.9.1": ["nvidia_cublas_cu12-12.9.1-py3-none-manylinux2014_x86_64.whl"],
    })
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: io.BytesIO(payload))

    requirement = Requirement("nvidia-cublas-cu12>=12.8")
    assert bootstrap._best_wheel(requirement.name, requirement.specifier) is None


def test_best_wheel_handles_a_network_failure(monkeypatch):
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert bootstrap._best_wheel("nvidia-cublas-cu12", Requirement("x>=1").specifier) is None


def _wheel_bytes(member_name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, content)
    return buffer.getvalue()


def test_fetch_wheel_extracts_into_target(tmp_path, monkeypatch):
    content = b"not really a dll"
    wheel = _wheel_bytes("nvidia/cublas/lib/cublas.dll", content)
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: io.BytesIO(wheel))

    file_info = {"filename": "nvidia_cublas_cu12-1.0-py3-none-win_amd64.whl",
                 "url": "https://files/x.whl",
                 "digests": {"sha256": hashlib.sha256(wheel).hexdigest()}}
    assert bootstrap._fetch_wheel(file_info, tmp_path) is True
    assert (tmp_path / "nvidia" / "cublas" / "lib" / "cublas.dll").read_bytes() == content
    assert not list(tmp_path.glob("*.part"))   # the staging file is cleaned up


def test_fetch_wheel_rejects_a_checksum_mismatch(tmp_path, monkeypatch):
    wheel = _wheel_bytes("nvidia/cublas/lib/cublas.dll", b"data")
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen",
                         lambda *a, **k: io.BytesIO(wheel))

    file_info = {"filename": "nvidia_cublas_cu12-1.0-py3-none-win_amd64.whl",
                 "url": "https://files/x.whl",
                 "digests": {"sha256": "0" * 64}}
    assert bootstrap._fetch_wheel(file_info, tmp_path) is False
    assert not (tmp_path / "nvidia").exists()
    assert not list(tmp_path.glob("*.part"))


def test_fetch_cuda_reports_failure_without_raising(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "_best_wheel", lambda *a, **k: None)
    assert bootstrap.fetch_cuda() is False


def test_a_failed_model_fetch_is_reported_not_raised(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: False)
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: False)

    def offline(*_a, **_k):
        raise OSError("no network")

    import faster_whisper.utils

    monkeypatch.setattr(faster_whisper.utils, "download_model", offline)
    assert bootstrap.fetch_model("tiny.en") is False   # must not raise


def test_nothing_is_needed_once_it_has_been_done(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: True)
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: True)
    bootstrap._record(model="tiny.en")
    assert bootstrap.needed("tiny.en", "cuda") is False


def test_a_different_model_is_needed_again(as_frozen, monkeypatch):
    monkeypatch.setattr(bootstrap, "cuda_present", lambda: True)
    monkeypatch.setattr(bootstrap, "has_nvidia_gpu", lambda: True)
    bootstrap._record(model="tiny.en")
    assert bootstrap.needed("small.en", "cuda") is True


def test_gpu_detection_survives_a_missing_nvidia_smi(monkeypatch):
    def explode(*_a, **_k):
        raise OSError("nvidia-smi not found")

    monkeypatch.setattr(subprocess, "run", explode)
    assert bootstrap.has_nvidia_gpu() is False


def test_gpu_detection_falls_back_to_the_adapter_list(monkeypatch):
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args[0])
        if args[0] == "nvidia-smi":
            return Result(returncode=1)
        return Result(returncode=0, stdout="NVIDIA GeForce RTX 5060\nAMD Radeon 780M\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert bootstrap.has_nvidia_gpu() is True
    assert "powershell" in calls


def test_bundled_data_is_read_from_the_bundle_not_beside_the_exe(monkeypatch, tmp_path):
    """PyInstaller unpacks data into _internal/, not next to the executable.

    Reading a shipped file relative to sys.executable therefore looks in the wrong directory —
    a mistake invisible from source and obvious only in a built copy.
    """
    exe_dir = tmp_path / "Ghostwriter"
    bundle = exe_dir / "_internal"
    bundle.mkdir(parents=True)
    (bundle / "config.toml").write_text("# shipped template\n", encoding="utf-8")

    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "executable", str(exe_dir / "Ghostwriter.exe"))
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)

    assert paths.program_dir() == exe_dir
    assert paths.resource_dir() == bundle

    from ghostwriter import config as config_module

    assert "shipped template" in config_module.template()


def test_a_first_run_creates_the_config_from_the_template(monkeypatch, tmp_path):
    bundle = tmp_path / "_internal"
    bundle.mkdir(parents=True)
    (bundle / "config.toml").write_text("# the manual\naccent = 1\n", encoding="utf-8")
    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths, "resource_dir", lambda: bundle)

    from ghostwriter import config as config_module

    target = tmp_path / "roaming" / "config.toml"
    created = config_module.ensure_exists(target)
    assert created.exists()
    # The comments are the manual; a settings file without them is a worse starting point.
    assert "# the manual" in created.read_text(encoding="utf-8")


def test_an_existing_config_is_never_overwritten(monkeypatch, tmp_path):
    from ghostwriter import config as config_module

    target = tmp_path / "config.toml"
    target.write_text("# mine\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "template", lambda: "# shipped\n")
    config_module.ensure_exists(target)
    assert target.read_text(encoding="utf-8") == "# mine\n"
