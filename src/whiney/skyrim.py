"""Finds the game and reads its state: folders, version, SKSE, Creation Club, ENB, plugins.txt.

Purpose:
    Everything the app knows about a Skyrim SE install comes from here:
    where the game and the player's Documents folder are (Steam libraries,
    OneDrive redirection), which SKSE runtime and Creation Club files are
    installed, and the active load order with its sync code.

Main package:
    The game folder (find_game_dir) and the enabled plugin list
    (enabled_plugins), from which sync_code() derives the code players compare.

Flow:
    1. Folders: Documents, My Games, INIs, saves.
    2. The game: Steam libraries, then the saved choice, checked by SkyrimSE.exe.
    3. What's installed in it: version resource, SKSE, Creation Club, ENB.
    4. plugins.txt: the enabled list in order, and its sync code.
"""
import hashlib
import os
import re
from pathlib import Path

from whiney import config, paths, winapi

INI_FILES = ("Skyrim.ini", "SkyrimCustom.ini")   # SkyrimPrefs.ini is per-PC (resolution, graphics)
OFFICIAL_MASTERS = ("Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm")


def documents_dir() -> Path:
    """Real Documents folder (handles OneDrive redirection)."""
    return winapi.documents_folder() or paths.HOME_DOCUMENTS


def my_games_dir() -> Path:
    return documents_dir() / "My Games" / "Skyrim Special Edition"


def ini_dir() -> Path:
    return my_games_dir()


def saves_dir() -> Path:
    return my_games_dir() / "Saves"


def steam_libraries() -> list[Path]:
    """Steam's install folder, then every library folder listed in its libraryfolders.vdf; [] without Steam."""
    steam = winapi.reg_value("HKCU", r"Software\Valve\Steam", "SteamPath")
    if steam is None:
        return []
    libs = [Path(steam)]
    vdf = Path(steam) / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        libs += parse_library_folders(vdf.read_text(encoding="locale", errors="ignore"))
    return libs


def parse_library_folders(vdf_text: str) -> list[Path]:
    """The "path" entries of a libraryfolders.vdf, in file order.

    Inputs:
        vdf_text: The file's text. Steam escapes backslashes, so D:\\Games is stored as D:\\\\Games.
    """
    return [Path(m.group(1).replace("\\\\", "\\")) for m in re.finditer(r'"path"\s+"([^"]+)"', vdf_text)]


def is_game_dir(p: str | Path | None) -> bool:
    if not p:
        return False
    return (Path(p) / "SkyrimSE.exe").exists()


def game_files(game: str | Path) -> set[str]:
    """Every file under the game folder, as lowercased paths relative to it with "/" ("data/skse/x.dll").

    Lowercased because Windows paths are case-insensitive: Vortex deploys
    "Textures/a.dds" and the check looks for "textures/a.dds". One walk, so
    tens of thousands of lookups stay cheap.
    """
    game = Path(game)
    found: set[str] = set()
    for dirpath, _dirs, files in os.walk(game):
        rel = Path(dirpath).relative_to(game).as_posix()
        prefix = "" if rel == "." else rel.lower() + "/"
        found.update(prefix + f.lower() for f in files)
    return found


def find_game_dir() -> Path | None:
    """Saved choice first, then Steam libraries. None if not found."""
    saved = config.settings().get("game_dir")
    if saved and is_game_dir(saved):
        return Path(saved)
    for lib in steam_libraries():
        game = lib / "steamapps" / "common" / "Skyrim Special Edition"
        if is_game_dir(game):
            return game
    return None


def skse_dlls(game: str | Path) -> list[str]:
    return sorted(p.name.lower() for p in Path(game).glob("skse64_*.dll")
                  if re.match(r"skse64_\d+_\d+_\d+\.dll", p.name, re.I))


def skse_runtime_label(dll: str) -> str:
    m = re.match(r"skse64_(\d+)_(\d+)_(\d+)\.dll", dll, re.I)
    return ".".join(m.groups()) if m else dll


def cc_plugins(game: str | Path) -> list[str]:
    """Creation Club plugins listed in Skyrim.ccc that are actually installed."""
    ccc = Path(game) / "Skyrim.ccc"
    if not ccc.exists():
        return []
    names = [l.strip() for l in ccc.read_text(encoding="locale", errors="ignore").splitlines() if l.strip()]
    return [n for n in names if (Path(game) / "Data" / n).exists()]


def uses_enb(game: str | Path) -> bool:
    game = Path(game)
    return (game / "d3d11.dll").exists() and (
        (game / "enbseries.ini").exists() or (game / "enblocal.ini").exists())


def read_plugins_txt(path: str | Path) -> list[tuple[str, bool]]:
    """[(name, enabled)] in file order."""
    out: list[tuple[str, bool]] = []
    try:
        lines = Path(path).read_text(encoding="locale", errors="ignore").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            out.append((line[1:], True))
        else:
            out.append((line, False))
    return out


def enabled_plugins(path: str | Path) -> list[str]:
    return [n for n, on in read_plugins_txt(path) if on]


def sync_code(plugins_txt: str | Path | None = None) -> str | None:
    """Short code from the enabled plugin list + order. Same code = same load order."""
    path = plugins_txt or (paths.SKYRIM_APPDATA / "plugins.txt")
    names = [n.lower() for n in enabled_plugins(path)]
    if not names:
        return None
    h = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}"
