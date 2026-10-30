"""The pack's config, what it was built against, the player's choices, and what's installed.

Purpose:
    Answers "which pack is this and is it installed?". CONFIG comes from
    pack_config.json (bundled into the exe); requirements.json comes from the
    maintainer's snapshot; settings.json holds the player's own choices (game
    folder, Vortex folder); installed.json says what the installer finished.

Main package:
    CONFIG: pack_name, author, drive_file_id, update_file_id, as
    pack_config.json merged over DEFAULT_CONFIG.
    install_state(): "none" | "installed" | "update".

Flow:
    1. Load CONFIG at import (bundle first, then the kit folder).
    2. Read requirements.json and the full pack's identity (base_id).
    3. Read and save the player's settings.
    4. Compare installed.json with the requirements.
"""
import json
import time
from typing import Any, Literal

from whiney import paths, util

# Placeholders only. A pack's real name, author and Drive IDs go in pack_config.json
# (kept out of the repo, bundled into the exe by build.bat). snapshot() refuses to
# build while drive_file_id is still PASTE_FILE_ID_HERE; a real ID here would
# silently skip that check for every fresh kit
DEFAULT_CONFIG = {
    "pack_name": "Whiney",
    "author": "Simbyote",
    "drive_file_id": "PASTE_FILE_ID_HERE",
    "update_file_id": "",
}


def load_config() -> dict[str, Any]:
    for folder in (paths.BUNDLE_DIR, paths.KIT_DIR):
        f = folder / paths.CONFIG_NAME
        if f.exists():
            try:
                return {**DEFAULT_CONFIG, **json.loads(f.read_text(encoding="utf-8"))}
            except Exception:
                pass
    return dict(DEFAULT_CONFIG)


CONFIG = load_config()


def load_requirements() -> dict[str, Any]:
    f = paths.PACKINFO / paths.REQ_FILE
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def load_inventory() -> dict[str, list[str]]:
    """The pack's deployed files per mod ({mod: ["Data/...", ...]}), from _packinfo; {} for builds without one."""
    data = util.read_json(paths.PACKINFO / paths.INVENTORY_FILE, {})
    return data if isinstance(data, dict) else {}


def mark_installed(req: dict[str, Any] | None = None) -> None:
    """Record the pack (and update) the exe was built for as installed: what install_state() compares."""
    req = req if req is not None else load_requirements()
    util.write_json(paths.INSTALLED_MARKER, {
        "base": base_id(req),
        "update": req.get("update_version"),
        "installed": time.strftime("%Y-%m-%d %H:%M"),
    })


def base_id(req: dict[str, Any] | None = None) -> str:
    """Identity of the full pack this app was built for."""
    req = req if req is not None else load_requirements()
    return req.get("base_version") or CONFIG["drive_file_id"]


def settings() -> dict[str, Any]:
    return util.read_json(paths.SETTINGS_FILE, {}) or {}


def save_setting(key: str, value: Any) -> None:
    s = settings()
    s[key] = value
    util.write_json(paths.SETTINGS_FILE, s)


def install_state(req: dict[str, Any] | None = None) -> Literal["none", "installed", "update"]:
    """'none' | 'installed' | 'update' (installed, but a newer update exists)."""
    req = req if req is not None else load_requirements()
    marker = util.read_json(paths.INSTALLED_MARKER, {}) or {}
    if marker.get("base") != base_id(req):
        return "none"
    if CONFIG.get("update_file_id") and req.get("update_version") \
            and marker.get("update") != req.get("update_version"):
        return "update"
    return "installed"
