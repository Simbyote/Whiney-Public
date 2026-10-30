"""Backups, restores, cleanup and uninstall for the Manage tab.

Purpose:
    The operations where a player can lose data, kept small and in one place:
    save backups (a restore first backs up the current saves, then either
    merges the backup in or replaces the folder with it), putting the
    player's own settings back from the .bak files install left, deleting
    downloaded pack files, and forgetting the install.

Main package:
    Saves-<timestamp>.zip in paths.SAVE_BACKUPS: one save backup.

Flow:
    Independent operations, each called from one Manage button:
    backup_saves / restore_saves, restore_settings, free_space, uninstall.
"""
import shutil
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from whiney import paths, skyrim, util


def backup_saves(progress: Callable[[float, str], object] | None = None) -> Path | None:
    src = skyrim.saves_dir()
    if not src.is_dir() or not any(src.iterdir()):
        return None
    paths.SAVE_BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = paths.SAVE_BACKUPS / f"Saves-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    files = [p for p in src.rglob("*") if p.is_file()]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=1, strict_timestamps=False) as zf:
        for i, p in enumerate(files, 1):
            zf.write(p, p.relative_to(src))
            if progress and i % 10 == 0:
                progress(i / len(files), f"Backing up saves {i}/{len(files)}")
    return dest


def list_save_backups() -> list[Path]:
    if not paths.SAVE_BACKUPS.is_dir():
        return []
    return sorted(paths.SAVE_BACKUPS.glob("Saves-*.zip"), reverse=True)


def restore_saves(backup_zip: str | Path, replace: bool = False) -> Path | None:
    """Restores a backup. Current saves are backed up first, so nothing is lost.

    Inputs:
        replace: False merges (the backup's files are added back; saves made
            since stay, and same-named ones are overwritten). True makes the
            saves folder exactly the backup: everything else in it is deleted,
            once the safety backup of it has been written and read back.

    Outputs:
        The safety backup of the current saves, or None if there were none.

    Every entry is checked to land inside the saves folder before anything
    is backed up or written; util.UnsafeArchive stops a bad zip untouched.
    """
    dest = skyrim.saves_dir()
    with zipfile.ZipFile(backup_zip) as zf:
        for name in zf.namelist():
            util.safe_member_path(dest, name)
        first = backup_saves()
        if replace and dest.is_dir():
            _clear_saves(dest, first)
        dest.mkdir(parents=True, exist_ok=True)
        zf.extractall(dest)
    return first


def _clear_saves(dest: Path, safety: Path | None) -> None:
    """Empty the saves folder, but only if everything in it is in the readable safety backup."""
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    if files:
        if safety is None:
            raise OSError("the current saves weren't backed up, so they weren't deleted")
        with zipfile.ZipFile(safety) as zf:
            if zf.testzip() is not None or sorted(zf.namelist()) != files:
                raise OSError(f"the safety backup {safety.name} doesn't hold every current save, "
                              "so nothing was deleted")
    for p in dest.iterdir():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()


def settings_backups() -> list[Path]:
    pairs = [(paths.SKYRIM_APPDATA / n) for n in ("plugins.txt", "loadorder.txt")]
    pairs += [(skyrim.ini_dir() / n) for n in skyrim.INI_FILES]
    return [p for p in pairs if p.with_name(p.name + ".bak").exists()]


def restore_settings() -> list[str]:
    restored = []
    for p in settings_backups():
        shutil.copy2(p.with_name(p.name + ".bak"), p)
        restored.append(p.name)
    return restored


def download_space() -> int:
    total = 0
    for p in (paths.ARCHIVE, paths.UPDATE_ARCHIVE, paths.ZIP_DIR, paths.EXTRACT_DIR, paths.UPDATE_EXTRACT):
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return total


def free_space() -> int:
    """Deletes downloaded pack files. Keeps installed.json/settings so updates still work."""
    freed = download_space()
    for p in (paths.ARCHIVE, paths.ARCHIVE_ID, paths.UPDATE_ARCHIVE):
        if p.exists():
            p.unlink()
    for d in (paths.ZIP_DIR, paths.EXTRACT_DIR, paths.UPDATE_EXTRACT):
        shutil.rmtree(d, ignore_errors=True)
    return freed


def uninstall() -> tuple[list[str], int]:
    """Restores the player's own settings and forgets the install. Mods themselves
    have to be removed in Vortex (it has no outside control)."""
    restored = restore_settings()
    freed = free_space()
    if paths.INSTALLED_MARKER.exists():
        paths.INSTALLED_MARKER.unlink()
    return restored, freed
