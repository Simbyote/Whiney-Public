"""
test_vortex.py  --  src/whiney/vortex.py

Players recognize mods by name, not by Vortex's folder names. The Doctor and
Crash Squatch both show nice_mod_name's output, and the Doctor matches pack mods
to installed ones by it.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
from pathlib import Path

import pytest

from whiney import vortex

pytestmark = pytest.mark.software


@pytest.mark.parametrize("folder, name", [
    # Vortex staging names: mod name, Nexus id, version, install timestamp, random suffix
    ("Skyrim Souls RE - Unpaused Menus 27859 3.2.0 2026-09-25T11-22Z IoFl", "Skyrim Souls RE - Unpaused Menus"),
    ("SkyUI_5_2_SE-12604-5-2SE", "SkyUI_5_2_SE"),
    ("Plain Mod", "Plain Mod"),
    ("12345", "12345"),                  # nothing left after the split: keep the original
])
def test_nice_mod_name_drops_vortex_id_and_version_suffix(folder, name):
    assert vortex.nice_mod_name(folder) == name


# ---- finding Vortex.exe (fake registry) -------------------------------------------------
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
UNINSTALL_32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


def _exe(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Vortex.exe").write_bytes(b"MZ")
    return folder / "Vortex.exe"


def _entry(sandbox, hive, base, sub, **values):
    for name, value in values.items():
        sandbox.winapi.set_reg(hive, f"{base}\\{sub}", name, value)


def test_nothing_registered_means_no_vortex(sandbox):
    assert vortex.find_vortex() is None


def test_an_uninstall_entry_named_vortex_gives_its_install_folder(sandbox):
    exe = _exe(sandbox.root / "Vortex")
    _entry(sandbox, "HKCU", UNINSTALL, "OtherApp", DisplayName="Other", InstallLocation=str(sandbox.root))
    _entry(sandbox, "HKCU", UNINSTALL, "abc-123", DisplayName="Vortex 1.13", InstallLocation=str(exe.parent))
    assert vortex.find_vortex() == exe


def test_per_user_entries_win_over_machine_wide_ones(sandbox):
    mine, machine = _exe(sandbox.root / "Mine"), _exe(sandbox.root / "Machine")
    _entry(sandbox, "HKLM", UNINSTALL, "v", DisplayName="Vortex", InstallLocation=str(machine.parent))
    _entry(sandbox, "HKCU", UNINSTALL, "v", DisplayName="Vortex", InstallLocation=str(mine.parent))
    assert vortex.find_vortex() == mine


def test_32_bit_uninstall_entries_are_searched_too(sandbox):
    exe = _exe(sandbox.root / "Vortex")
    _entry(sandbox, "HKLM", UNINSTALL_32, "v", DisplayName="Vortex", InstallLocation=str(exe.parent))
    assert vortex.find_vortex() == exe


def test_an_entry_pointing_at_a_missing_exe_falls_through_to_the_next(sandbox):
    exe = _exe(sandbox.root / "Real")
    _entry(sandbox, "HKCU", UNINSTALL, "a-stale", DisplayName="Vortex", InstallLocation=str(sandbox.root / "Gone"))
    _entry(sandbox, "HKLM", UNINSTALL, "b-real", DisplayName="Vortex", InstallLocation=str(exe.parent))
    assert vortex.find_vortex() == exe


@pytest.mark.parametrize("form", [
    pytest.param("{exe},0", id="icon-unquoted"),
    pytest.param('"{exe}",0', id="icon-quoted"),
])
def test_display_icon_gives_the_exe(sandbox, form):
    exe = _exe(sandbox.root / "Vortex")
    _entry(sandbox, "HKCU", UNINSTALL, "v", DisplayName="Vortex", DisplayIcon=form.format(exe=exe))
    assert vortex.find_vortex() == exe


@pytest.mark.parametrize("value, path", [
    ('"C:\\Apps\\Vortex\\Vortex.exe",0', "C:\\Apps\\Vortex\\Vortex.exe"),
    ("C:\\Apps\\Vortex\\Vortex.exe,0", "C:\\Apps\\Vortex\\Vortex.exe"),
    ("C:\\Apps\\Vortex\\Vortex.exe, -101", "C:\\Apps\\Vortex\\Vortex.exe"),
    ('"C:\\Apps\\Vortex"', "C:\\Apps\\Vortex"),
    ("C:\\Apps\\Vortex", "C:\\Apps\\Vortex"),
    # The old split(",")[0] cut this at the comma
    ("D:\\Games, Mods\\Vortex\\Vortex.exe,0", "D:\\Games, Mods\\Vortex\\Vortex.exe"),
])
def test_registry_paths_lose_quotes_and_icon_index_only(value, path):
    assert vortex.registry_path(value) == Path(path)
