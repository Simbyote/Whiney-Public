"""
test_winapi.py  --  src/whiney/winapi.py

winapi is the only module that talks to the OS, and FakeWinapi stands in for
it in every software test. These check that the fake matches the real module
call for call, and that each real primitive returns what callers expect from
a real Windows: values or None/[] for anything missing, never an exception.
Read-only: nothing here writes to the registry or starts a lasting process.

--software  The fake's parity and the cross-platform primitives on any OS; the
            Win32 and registry reads on Windows only (skipped elsewhere).
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

from fake_winapi import FakeWinapi
from whiney import winapi

pytestmark = pytest.mark.software

# Taken at import, before the sandbox swaps them for the fake's
REAL = {name: getattr(winapi, name) for name in dir(winapi) if inspect.isfunction(getattr(winapi, name))}
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="real Win32 calls")


@pytest.fixture
def real(monkeypatch):
    """Put the real winapi functions back for one test."""
    for name, fn in REAL.items():
        monkeypatch.setattr(winapi, name, fn)


@pytest.mark.parametrize("name", sorted(n for n, f in REAL.items() if f.__module__ == winapi.__name__))
def test_the_fake_has_every_function_with_the_same_parameters(name):
    fake = getattr(FakeWinapi, name, None)
    assert fake is not None, f"add {name} to tests/fake_winapi.py"
    real_params = list(inspect.signature(REAL[name]).parameters)
    fake_params = list(inspect.signature(fake).parameters)[1:]          # drop self
    assert fake_params == real_params


# ---- any OS ----------------------------------------------------------------------------
def test_run_returns_the_commands_output(real):
    out = winapi.run([sys.executable, "-c", "print('hello')"])
    assert out.strip() == "hello"


def test_run_of_a_missing_command_is_none(real):
    assert winapi.run(["whiney-no-such-command-xyz"]) is None


def test_run_that_times_out_is_none(real):
    assert winapi.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5) is None


def test_a_missing_registry_key_reads_as_none_and_no_subkeys(real):
    # Off Windows winreg doesn't exist; on Windows the key doesn't: both read as missing
    assert winapi.reg_value("HKCU", r"Software\WhineyNoSuchKey", "x") is None
    assert winapi.reg_subkeys("HKCU", r"Software\WhineyNoSuchKey") == []


def test_this_python_is_a_running_process(real):
    name = Path(sys.executable).name
    assert winapi.process_running(name)
    proc = winapi.find_process(name)
    assert proc is not None and proc.info["name"].lower() == name.lower()
    alive, ram = winapi.process_stats(proc)
    assert alive and ram > 0


def test_an_exe_name_nobody_runs_is_not_found(real):
    assert not winapi.process_running("whiney-not-running.exe")
    assert winapi.find_process("whiney-not-running.exe") is None


# ---- Windows -----------------------------------------------------------------------------
@windows_only
def test_registry_reads_a_value_every_windows_has(real):
    product = winapi.reg_value("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName")
    assert isinstance(product, str) and "Windows" in product


@windows_only
def test_registry_lists_subkeys_every_windows_has(real):
    subkeys = winapi.reg_subkeys("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    assert subkeys and all(isinstance(s, str) for s in subkeys)


@windows_only
def test_file_version_reads_a_system_exe(real):
    version = winapi.file_version(Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe")
    assert version and len(version.split(".")) == 4


@windows_only
def test_file_version_of_a_file_without_a_version_resource_is_none(real, tmp_path):
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"MZ")
    assert winapi.file_version(plain) is None


@windows_only
def test_documents_folder_exists(real):
    docs = winapi.documents_folder()
    assert docs is not None and docs.is_dir()


@windows_only
def test_this_process_has_no_hung_window(real):
    assert winapi.window_hung(os.getpid()) is False
