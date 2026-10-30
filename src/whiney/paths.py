"""Every real-world location the app reads or writes, in one place.

Purpose:
    The kit folder and the exe's bundled data, the player's work folder in
    Downloads, AppData, Vortex. Nothing else in the app builds these paths,
    so the test sandbox can redirect all of them by patching this module.
    Callers use `paths.NAME` at call time (never `from paths import NAME`),
    so a patch reaches them.

Main package:
    The path constants. File names that are joined onto them later
    (CONFIG_NAME, REQ_FILE, UPDATE_INFO) live here too.

Flow:
    1. Kit and bundle: where the maintainer's files and the exe's data are.
    2. The work folder and everything the installer keeps in it.
    3. Windows locations: AppData, Vortex.
"""
import os
import sys
from pathlib import Path

# ---- kit and bundle ---------------------------------------------------------------
# The kit folder (repo root): build.bat, pack_config.json, the manifests and
# _packinfo/ live here. This file is src/whiney/paths.py, two levels below it.
# Only meaningful from source; the exe reads its data from BUNDLE_DIR
KIT_DIR = Path(__file__).resolve().parents[2]
# Inside the PyInstaller exe, data files unpack to _MEIPASS; from source they're in the kit
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", KIT_DIR))
ASSET_DIR = BUNDLE_DIR / "assets"
PACKINFO_NAME = "_packinfo"
PACKINFO = BUNDLE_DIR / PACKINFO_NAME
REQ_FILE = "requirements.json"
INVENTORY_FILE = "files.json"       # in _packinfo: each pack mod's deployed files (snapshot.deployed_inventory)
# The players' guide: bundled at the exe's root by build.bat; in release/ when run from source
GUIDE = BUNDLE_DIR / "README.txt" if hasattr(sys, "_MEIPASS") else KIT_DIR / "release" / "README.txt"
CONFIG_NAME = "pack_config.json"

# ---- the player's work folder -------------------------------------------------------
# The player's own folders; the browser fallback looks for a manual download in DOWNLOADS
DOWNLOADS = Path.home() / "Downloads"
# Only when Windows doesn't report the Documents shell folder (skyrim.documents_dir)
HOME_DOCUMENTS = Path.home() / "Documents"
WORK_DIR = DOWNLOADS / "Whiney"
ARCHIVE = WORK_DIR / "modpack.tar.gz"
ARCHIVE_ID = WORK_DIR / "modpack.id"
EXTRACT_DIR = WORK_DIR / "extracted"
ZIP_DIR = WORK_DIR / "ToVortex"
BASE_READY = ZIP_DIR / ".base_ready"
# ToVortex also holds the update's zips once applied; this records which update and what it changed
UPDATE_READY = ZIP_DIR / ".update_ready"
# "Update only" hands the player just the update's zips, from here, and leaves ToVortex whole
UPDATE_ZIPS = WORK_DIR / "ToVortex_Update"
UPDATE_ARCHIVE = WORK_DIR / "modpack_update.tar.gz"
UPDATE_EXTRACT = WORK_DIR / "update_extracted"
UPDATE_INFO = "_update_info.json"
# Repair (installer mode "repair"): zips of just the mods being repaired, and the archive members they came from
REPAIR_DIR = WORK_DIR / "Repair"
REPAIR_EXTRACT = WORK_DIR / "repair_extracted"
INSTALLED_MARKER = WORK_DIR / "installed.json"
SETTINGS_FILE = WORK_DIR / "settings.json"
CRASH_HISTORY = WORK_DIR / "crash_history.json"
SAVE_BACKUPS = WORK_DIR / "save_backups"
LOG_FILE = WORK_DIR / "app_log.txt"

# ---- Windows locations -------------------------------------------------------------
SKYRIM_APPDATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Skyrim Special Edition"
VORTEX_STAGING = Path(os.environ.get("APPDATA", "")) / "Vortex" / "skyrimse" / "mods"
VORTEX_CANDIDATES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Black Tree Gaming Ltd" / "Vortex" / "Vortex.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "vortex" / "Vortex.exe",
]
