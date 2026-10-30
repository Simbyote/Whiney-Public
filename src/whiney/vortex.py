"""Finds Vortex and its mods folder, and reads Vortex's mod folder names.

Purpose:
    The app can't drive Vortex, only find it, start it, see whether it is
    running, and read the staging folder it installs mods into. Vortex names
    each mod folder "<name>-<Nexus id>-<version>-<timestamp>"; nice_mod_name
    turns that back into the name players recognize.

Main package:
    The staging folder (staging_dir): one folder per installed mod.

Flow:
    1. The staging folder: the player's saved choice, else Vortex's default.
    2. Mod folder names: the readable name.
    3. Vortex.exe: default folders, the nxm:// handler, uninstall entries; is it running; start it.
"""
import re
from pathlib import Path

from whiney import config, paths, winapi

SKIP_PREFIXES = ("__vortex", "__folder_managed_by_vortex")
ARCHIVE_EXTS = (".zip", ".7z", ".rar")


def staging_dir() -> Path:
    saved = config.settings().get("staging_dir")
    if saved and Path(saved).is_dir():
        return Path(saved)
    return paths.VORTEX_STAGING


def nice_mod_name(folder_name: str) -> str:
    """'Skyrim Souls RE - Unpaused Menus 27859 3.2.0 2026-09-25T11-22Z IoFl' -> 'Skyrim Souls RE - Unpaused Menus'."""
    short = re.split(r"[ \-]\d{4,}", folder_name)[0].strip(" -_")
    return short or folder_name


def vortex_running() -> bool:
    return winapi.process_running("Vortex.exe")


# Where Vortex's nxm:// link handler is registered: per user, then machine-wide
NXM_HANDLER_KEYS = (("HKCU", r"Software\Classes\nxm\shell\open\command"),
                    ("HKCR", r"nxm\shell\open\command"))
UNINSTALL_KEYS = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                  r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")


def registry_path(value: object) -> Path:
    """A path from an uninstall entry: quotes and a trailing icon index removed.

    Inputs:
        value: DisplayIcon or InstallLocation as stored, e.g. '"C:\\Vortex\\Vortex.exe",0',
            'C:\\Vortex\\Vortex.exe,0' or 'C:\\Vortex'. Only a trailing ",<number>" is an
            icon index, so a folder name containing a comma survives.
    """
    text = str(value).strip()
    if text.startswith('"'):
        return Path(text[1:].split('"', 1)[0])
    return Path(re.sub(r",\s*-?\d+$", "", text).strip())


def find_vortex() -> Path | None:
    """Default folders, then the nxm:// link handler Vortex registers, then uninstall entries."""
    for exe in paths.VORTEX_CANDIDATES:
        if exe.exists():
            return exe

    def exe_from(text: str | None) -> Path | None:
        m = re.search(r'([A-Za-z]:\\[^"]*?vortex\.exe)', text or "", re.I)
        return Path(m.group(1)) if m and Path(m.group(1)).exists() else None

    for hive, key in NXM_HANDLER_KEYS:
        hit = exe_from(winapi.reg_value(hive, key))
        if hit:
            return hit

    for hive in ("HKCU", "HKLM"):
        for base in UNINSTALL_KEYS:
            for sub in winapi.reg_subkeys(hive, base):
                entry = f"{base}\\{sub}"
                name = winapi.reg_value(hive, entry, "DisplayName")
                if name is None or "vortex" not in str(name).lower():
                    continue
                for field in ("DisplayIcon", "InstallLocation"):
                    val = winapi.reg_value(hive, entry, field)
                    if val is None:
                        continue
                    cand = registry_path(val)
                    if cand.is_dir():
                        cand = cand / "Vortex.exe"
                    if cand.name.lower() == "vortex.exe" and cand.exists():
                        return cand
    return None


def launch_vortex() -> bool:
    exe = find_vortex()
    if exe:
        winapi.open_path(exe)
        return True
    return False
