"""
test_windows.py  --  src/whiney/skyrim.py and vortex.py against the real Windows API

The software tests fake every OS call; these pin what the real ones do, on
the throwaway Windows runner CI provides. They write the registry entries a
real Steam and Vortex would (a SteamPath, an nxm:// link handler, an
uninstall entry) under HKCU, check that game and Vortex detection find
them, and delete them again. They are the before/after check for moving the
Windows calls behind one module: the bodies stay the same, only `real_windows`
changes. (The plain Win32 reads, file_version, the Documents folder and the
process list, are in test_winapi.py with the other primitives.)

--software  Windows CI only (GITHUB_ACTIONS=true): writes and removes HKCU registry
            keys, so it never runs on a developer's PC. Skipped everywhere else.
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

from builders import make_game
from whiney import skyrim, vortex, winapi

ON_WINDOWS_CI = sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
pytestmark = [pytest.mark.software,
              pytest.mark.skipif(not ON_WINDOWS_CI, reason="writes the registry: Windows CI runner only")]

# Taken at import, before the sandbox swaps them for FakeWinapi's
REAL_WINAPI = {name: getattr(winapi, name) for name in dir(winapi) if inspect.isfunction(getattr(winapi, name))}

STEAM_KEY = r"Software\Valve\Steam"
NXM_KEY = r"Software\Classes\nxm\shell\open\command"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\WhineyTestVortex"


@pytest.fixture
def real_windows(sandbox, monkeypatch):
    """Undo the sandbox's OS fake, so detection reaches the real registry and Win32 APIs."""
    for name, fn in REAL_WINAPI.items():
        monkeypatch.setattr(winapi, name, fn)
    return sandbox


@pytest.fixture
def registry():
    """Write HKCU values for one test, then delete every key it created (refuses to touch existing ones)."""
    import winreg
    created = []

    def ensure(path):
        parts = path.split("\\")
        for i in range(1, len(parts) + 1):
            sub = "\\".join(parts[:i])
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub))
            except OSError:
                winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub))
                created.append(sub)

    def put(key, name, value):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key))
            if key not in created:
                pytest.skip(f"HKCU\\{key} already exists on this machine; not overwriting it")
        except OSError:
            pass
        ensure(key)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    yield put
    for sub in reversed(created):
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)


def _vortex_exe(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "Vortex.exe"
    exe.write_bytes(b"MZ")
    return exe


# ---- game detection through Steam --------------------------------------------------
def test_steam_path_in_the_registry_finds_the_game_in_a_second_library(real_windows, registry):
    steam = real_windows.root / "Steam"
    second = real_windows.root / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    # Steam writes paths with doubled backslashes inside libraryfolders.vdf
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"1"\n\t{\n\t\t"path"\t\t"' + str(second).replace("\\", "\\\\") + '"\n\t}\n}\n',
        encoding="utf-8")
    game = make_game(second / "steamapps" / "common" / "Skyrim Special Edition")
    registry(STEAM_KEY, "SteamPath", str(steam))

    assert skyrim.steam_libraries() == [steam, second]
    assert skyrim.find_game_dir() == game


def test_no_steam_in_the_registry_means_no_libraries(real_windows):
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_KEY))
        pytest.skip("this machine has Steam")
    except OSError:
        pass
    assert skyrim.steam_libraries() == []


# ---- Vortex detection --------------------------------------------------------------
def test_vortex_is_found_through_the_nxm_link_handler(real_windows, registry):
    exe = _vortex_exe(real_windows.root / "Black Tree Gaming" / "Vortex")
    registry(NXM_KEY, "", f'"{exe}" -d "%1"')
    assert vortex.find_vortex() == exe


# DisplayIcon is the exe plus an icon index, quoted or not; InstallLocation is the folder
UNINSTALL_FORMS = [
    pytest.param("DisplayIcon", "{exe},0", id="icon-unquoted"),
    pytest.param("DisplayIcon", '"{exe}",0', id="icon-quoted"),
    pytest.param("InstallLocation", "{folder}", id="install-folder"),
]


@pytest.mark.parametrize("field, form", UNINSTALL_FORMS)
def test_vortex_is_found_through_an_uninstall_entry(real_windows, registry, field, form):
    exe = _vortex_exe(real_windows.root / "Apps" / "Vortex")
    registry(UNINSTALL_KEY, "DisplayName", "Vortex")
    registry(UNINSTALL_KEY, field, form.format(exe=exe, folder=exe.parent))
    assert vortex.find_vortex() == exe


def test_the_nxm_handler_wins_over_an_uninstall_entry(real_windows, registry):
    handler = _vortex_exe(real_windows.root / "Handler")
    listed = _vortex_exe(real_windows.root / "Listed")
    registry(UNINSTALL_KEY, "DisplayName", "Vortex")
    registry(UNINSTALL_KEY, "InstallLocation", str(listed.parent))
    registry(NXM_KEY, "", f'"{handler}" -d "%1"')
    assert vortex.find_vortex() == handler


def test_a_handler_pointing_at_a_missing_exe_is_skipped(real_windows, registry):
    listed = _vortex_exe(real_windows.root / "Listed")
    registry(NXM_KEY, "", f'"{real_windows.root / "Gone" / "Vortex.exe"}" -d "%1"')
    registry(UNINSTALL_KEY, "DisplayName", "Vortex")
    registry(UNINSTALL_KEY, "InstallLocation", str(listed.parent))
    assert vortex.find_vortex() == listed
