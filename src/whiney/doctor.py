"""Health checks: turns the player's setup into findings with a fix for each.

Purpose:
    Catches the setups that crash Skyrim or desync multiplayer before the
    player finds out in game: a wrong game version, missing SKSE or Address
    Library, plugins missing a master or loading before it, too many full
    plugins, a load order that differs from the pack. The installer runs the
    preflight subset before installing; the Doctor tab runs everything.

Main package:
    Finding(level, area, title, detail, fix, mods): level is "OK" | "WARN" | "FAIL".
    FAIL means the game will crash or the install will fail; WARN is worth a
    look; fix is shown only for WARN and FAIL. mods names the pack mods a
    deployment finding is about, which the Doctor tab offers to repair.

Flow:
    1. Read plugin headers (masters, ESM/ESL flags) straight from the TES4 record.
    2. Build the effective load order the game uses: masters hoisted first.
    3. Check groups: preflight, plugins, SKSE plugins, deployment, mods, system.
    4. run_all collects them, turning a crashing group into a WARN; report_text formats them.
"""
import shutil
import struct
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from whiney import config, paths, skyrim, util, vortex, winapi

FULL_PLUGIN_LIMIT = 254     # one-byte load order index; 0xFE is light plugins, 0xFF runtime forms


LEVELS = ("OK", "WARN", "FAIL")
Level = Literal["OK", "WARN", "FAIL"]


@dataclass(frozen=True)
class Finding:
    """One Doctor result. level is checked on creation, so a misspelt level fails where it's made."""
    level: Level         # FAIL: the game will crash or the install will fail; WARN: worth a look
    area: str            # the group shown on the card: "Game", "Plugins", "SKSE", ...
    title: str
    detail: str = ""     # more lines under the title
    fix: str = ""        # what to do about it; never shown for OK
    mods: tuple[str, ...] = ()   # pack mod folders (files.json keys) a deployment finding is about: Repair

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"Finding level must be one of {LEVELS}, not {self.level!r}")


# ---- plugin header reader -----------------------------------------------------
class PluginHeader(TypedDict):
    """What the Doctor reads from a plugin's TES4 record."""
    masters: list[str]
    esm: bool          # ESM flag (0x1): loads with the masters
    esl: bool          # ESL flag (0x200): light, shares one load order slot


def read_plugin_header(path: str | Path) -> PluginHeader | None:
    """Masters + flags from a plugin's TES4 header. None if unreadable."""
    try:
        with open(path, "rb") as f:
            hdr = f.read(24)
            if len(hdr) < 24 or hdr[:4] != b"TES4":
                return None
            size, flags = struct.unpack_from("<II", hdr, 4)
            data = f.read(size)
    except OSError:
        return None
    masters: list[str] = []
    i, big = 0, None
    while i + 6 <= len(data):
        typ = data[i:i + 4]
        sz = struct.unpack_from("<H", data, i + 4)[0]
        i += 6
        if typ == b"XXXX":                    # next field is bigger than 64 KB
            big = struct.unpack_from("<I", data, i)[0]
            i += sz
            continue
        if big is not None:
            sz, big = big, None
        if typ == b"MAST":
            masters.append(data[i:i + sz].split(b"\0")[0].decode("cp1252", "replace"))
        i += sz
    return {"masters": masters, "esm": bool(flags & 0x1), "esl": bool(flags & 0x200)}


def data_plugin_index(game: str | Path) -> dict[str, Path]:
    """lowercase name -> Path for every plugin file in Data."""
    idx: dict[str, Path] = {}
    data = Path(game) / "Data"
    try:
        for p in data.iterdir():
            if p.suffix.lower() in (".esp", ".esm", ".esl") and p.is_file():
                idx[p.name.lower()] = p
    except OSError:
        pass
    return idx


def active_load_order(game: str | Path, plugins_txt: str | Path
                      ) -> tuple[list[str], dict[str, PluginHeader | None], dict[str, Path]]:
    """Plugins the game will actually load, in effective order."""
    idx = data_plugin_index(game)
    implicit = [m for m in skyrim.OFFICIAL_MASTERS if m.lower() in idx]
    implicit += [c for c in skyrim.cc_plugins(game) if c.lower() not in {m.lower() for m in implicit}]
    seen = {m.lower() for m in implicit}
    listed = [n for n in skyrim.enabled_plugins(plugins_txt) if n.lower() not in seen]
    order = implicit + listed
    headers = {n.lower(): read_plugin_header(idx[n.lower()]) for n in order if n.lower() in idx}

    def is_master(n: str) -> bool:
        h = headers.get(n.lower())
        return n.lower().endswith((".esm", ".esl")) or bool(h and h["esm"])
    # the game loads all masters before regular plugins, keeping their relative order
    effective = [n for n in order if is_master(n)] + [n for n in order if not is_master(n)]
    return effective, headers, idx


# ---- check groups ------------------------------------------------------------
def preflight(req: dict, game: Path | None) -> list[Finding]:
    """The checks the installer runs before installing."""
    out: list[Finding] = []
    if vortex.vortex_running() or vortex.find_vortex():
        out.append(Finding("OK", "Vortex", "Vortex is installed"))
    else:
        out.append(Finding("WARN", "Vortex", "Couldn't find Vortex",
                           fix="Install it from nexusmods.com/app, or ignore this if it's in an unusual folder."))
    if not game:
        out.append(Finding("FAIL", "Game", "Couldn't find Skyrim Special Edition",
                           fix="Home tab > Change game folder, and pick the folder with SkyrimSE.exe in it."))
        return out
    out.append(Finding("OK", "Game", "Found Skyrim SE", str(game)))

    want, have = req.get("game_version"), winapi.file_version(Path(game) / "SkyrimSE.exe")
    if want and have and want != have:
        out.append(Finding("FAIL", "Game", f"Game version {have} doesn't match the pack ({want})",
                           "SKSE and most of its mods only work on one exact game version.",
                           f"Ask {config.CONFIG['author']}: either he updates the pack or you downgrade."))
    elif want and have:
        out.append(Finding("OK", "Game", f"Game version {have} matches"))

    need = req.get("skse_dlls", [])
    if need:
        runtime = ", ".join(map(skyrim.skse_runtime_label, need))
        have_dlls = skyrim.skse_dlls(game)
        if not (Path(game) / "skse64_loader.exe").exists() or not set(need) <= set(have_dlls):
            out.append(Finding("FAIL", "SKSE", f"SKSE for game version {runtime} is missing",
                               fix="Get it from skse.silverlock.org. Copy skse64_loader.exe and the .dll "
                                   "files into the Skyrim folder, next to SkyrimSE.exe."))
        else:
            out.append(Finding("OK", "SKSE", "SKSE installed"))

    missing_cc = [p for p in req.get("cc_plugins", []) if not (Path(game) / "Data" / p).exists()]
    if len(missing_cc) > 4:
        out.append(Finding("FAIL", "Game", f"Missing {len(missing_cc)} Creation Club files",
                           fix="You need the Anniversary Edition upgrade. Buy it on Steam, launch the game "
                               "once so it downloads, then try again."))
    elif missing_cc:
        out.append(Finding("FAIL", "Game", "Missing Creation Club files", ", ".join(missing_cc),
                           fix="Launch the game once from Steam so it downloads its Creation Club content."))
    elif req.get("cc_plugins"):
        out.append(Finding("OK", "Game", "Anniversary / Creation Club content present"))

    if req.get("uses_enb") and not skyrim.uses_enb(game):
        out.append(Finding("WARN", "Graphics", f"{config.CONFIG['author']} uses an ENB and you don't",
                           "The game runs fine without it, it just won't look the same.",
                           "Optional: get the ENB binaries from enbdev.com and copy d3d11.dll + "
                           "d3dcompiler_46e.dll into the Skyrim folder."))
    return out


def check_plugins(game: Path, req: dict) -> list[Finding]:
    out: list[Finding] = []
    live = paths.SKYRIM_APPDATA / "plugins.txt"
    if not live.exists():
        out.append(Finding("WARN", "Plugins", "No load order file yet",
                           fix="Launch the game once from Steam, quit at the main menu, then install the pack."))
        return out
    order, headers, idx = active_load_order(game, live)

    missing_files = [n for n in order if n.lower() not in idx]
    if missing_files:
        out.append(Finding("FAIL", "Plugins", f"{len(missing_files)} enabled plugin(s) are missing from Data",
                           ", ".join(missing_files[:15]) + (" ..." if len(missing_files) > 15 else ""),
                           "In Vortex: Mods > select all > Enable > Deploy. Or run Install again."))

    active = {n.lower() for n in order}
    pos = {n.lower(): i for i, n in enumerate(order)}
    missing_masters: dict[str, list[str]] = {}
    bad_order: list[str] = []
    for n in order:
        h = headers.get(n.lower())
        if not h:
            continue
        for m in h["masters"]:
            if m.lower() not in active:
                missing_masters.setdefault(n, []).append(m)
            elif pos[m.lower()] > pos[n.lower()]:
                bad_order.append(f"{n} loads before its master {m}")
    if missing_masters:
        lines = [f"{p} needs: {', '.join(ms)}" for p, ms in list(missing_masters.items())[:12]]
        out.append(Finding("FAIL", "Plugins",
                           f"{len(missing_masters)} plugin(s) are missing a master (crashes at startup)",
                           "\n".join(lines),
                           "Install/enable the mod that provides the missing file, or disable the plugin "
                           "that needs it (Vortex > Plugins)."))
    if bad_order:
        out.append(Finding("FAIL", "Plugins", "Load order has plugins before their masters",
                           "\n".join(bad_order[:12]),
                           "Run Install again to restore the pack's load order (keep Autosort OFF)."))

    def is_light(n: str) -> bool:
        h = headers.get(n.lower())
        return n.lower().endswith(".esl") or bool(h and h["esl"])
    full = [n for n in order if not is_light(n)]
    if len(full) > FULL_PLUGIN_LIMIT:
        out.append(Finding("FAIL", "Plugins", f"{len(full)} full plugins enabled (limit is {FULL_PLUGIN_LIMIT})",
                           fix="Disable some plugins. Over the limit, the game crashes or silently drops plugins."))
    elif not (missing_files or missing_masters or bad_order):
        out.append(Finding("OK", "Plugins", f"{len(order)} plugins load cleanly",
                           f"{len(full)} full + {len(order) - len(full)} light, all masters present, order is valid."))

    pack_txt = paths.PACKINFO / "plugins.txt"
    if pack_txt.exists():
        pack = [n.lower() for n in skyrim.enabled_plugins(pack_txt)]
        mine = [n.lower() for n in skyrim.enabled_plugins(live)]
        extra = sorted(set(mine) - set(pack))
        lacking = sorted(set(pack) - set(mine))
        if pack == mine:
            out.append(Finding("OK", "Sync", f"Load order matches the pack (sync code {skyrim.sync_code()})"))
        else:
            detail = []
            if lacking:
                detail.append(f"Not enabled for you: {', '.join(lacking[:10])}" + (" ..." if len(lacking) > 10 else ""))
            if extra:
                detail.append(f"Extra on your side: {', '.join(extra[:10])}" + (" ..." if len(extra) > 10 else ""))
            if not detail:
                detail.append("Same plugins, different order.")
            out.append(Finding("WARN", "Sync", "Your load order differs from the pack",
                               "\n".join(detail),
                               "In multiplayer this causes desyncs. If every pack mod is in your game, "
                               "Apply the pack's load order (here or on Home) fixes it; otherwise Install again."))
    return out


def check_skse_plugins(game: Path, req: dict) -> list[Finding]:
    out: list[Finding] = []
    plugins_dir = Path(game) / "Data" / "SKSE" / "Plugins"
    dlls = list(plugins_dir.glob("*.dll")) if plugins_dir.is_dir() else []
    if not dlls:
        return out
    if not skyrim.skse_dlls(game):
        out.append(Finding("FAIL", "SKSE", f"{len(dlls)} SKSE plugins installed but SKSE itself isn't",
                           fix="Get SKSE from skse.silverlock.org and copy skse64_loader.exe + the .dll "
                               "files next to SkyrimSE.exe."))
    ver = winapi.file_version(Path(game) / "SkyrimSE.exe")
    if ver:
        bins = [f"versionlib-{ver.replace('.', '-')}.bin", f"version-{ver.replace('.', '-')}.bin"]
        if not any((plugins_dir / b).exists() for b in bins):
            out.append(Finding("WARN", "SKSE", "Address Library for your game version not found",
                               "Most SKSE plugins need it and will fail to load without it.",
                               "Install 'Address Library for SKSE Plugins' (All in one) from Nexus, through Vortex."))
        else:
            out.append(Finding("OK", "SKSE", "Address Library present"))
    logger = [d for d in dlls if d.name.lower() in ("crashlogger.dll", "trainwreck.dll")]
    if logger:
        out.append(Finding("OK", "Crash reports", f"{logger[0].stem} installed (detailed crash reports)"))
    else:
        out.append(Finding("WARN", "Crash reports", "No crash logger installed",
                           "Without one, Crash Squatch can only tell that the game crashed, not why.",
                           "Install 'Crash Logger SSE AE VR' from Nexus, through Vortex."))
    return out


def misplaced(missing: list[str], by_name: dict[str, list[str]]) -> tuple[str, str, int] | None:
    """Where a mod's missing files are instead, when Vortex deployed them into another folder.

    Inputs:
        missing: The mod's recorded paths that aren't in the game folder ("Data/X/a.exe").
        by_name: skyrim.game_files_by_name of the game folder.

    Outputs:
        (recorded folder, folder they are in, how many files moved that way), for
        the move most of the files share; "" is the game folder itself. None if
        no missing file is anywhere else. Each missing file is matched to the
        copy whose path ends the most like the recorded one, so a common name
        (readme.txt) in another mod rarely wins. Only a move into or out of a
        folder counts (game folder <-> Data, Data <-> Data/Data): that's what a
        different Mod Type does. A same-named file in a sibling folder is
        something else, e.g. two versions of a cache.
    """
    moves: Counter[tuple[str, str]] = Counter()
    for rel in missing:
        want = rel.split("/")
        best: tuple[str, str] | None = None
        shared = 0
        for cand in by_name.get(want[-1].lower(), []):
            have = cand.split("/")
            n = 0
            while n < min(len(want), len(have)) and want[-1 - n].lower() == have[-1 - n].lower():
                n += 1
            recorded, found = want[:len(want) - n], have[:len(have) - n]
            inner, outer = (recorded, found) if len(recorded) <= len(found) else (found, recorded)
            nested = [p.lower() for p in outer[:len(inner)]] == [p.lower() for p in inner]
            if nested and n > shared:
                best, shared = ("/".join(recorded), "/".join(found)), n
        if best:
            moves[best] += 1
    if not moves:
        return None
    (was, now), count = moves.most_common(1)[0]
    return was, now, count


def _folder(rel: str) -> str:
    return rel.replace("/", "\\") if rel else "the game folder"


def check_deployment(game: Path, inventory: dict[str, list[str]]) -> list[Finding]:
    """Compare the game folder with the files each pack mod deployed on the maintainer's PC (files.json).

    A mod with none of its files in place isn't deployed (FAIL: the install
    is incomplete); one missing some was deployed partly or overwritten by a
    file removal (WARN). Nothing is reported for a build without files.json.
    Missing files found in another folder are named with where they are:
    that's Vortex giving the mod another Mod Type than the maintainer's, which
    reinstalling the mod doesn't change.
    """
    if not inventory:
        return []
    present = skyrim.game_files(game)
    # Builds before RUNTIME_DIRS recorded the files Skyrim Together writes itself; they're never "missing"
    missing = {mod: [f for f in files if f.lower() not in present and not skyrim.is_runtime_file(f)]
               for mod, files in inventory.items()}
    missing = {mod: files for mod, files in missing.items() if files}
    total = sum(map(len, inventory.values()))
    if not missing:
        return [Finding("OK", "Deployment", f"All {len(inventory)} pack mods are deployed",
                        f"{total} files checked.")]
    by_name = skyrim.game_files_by_name(game)
    moved = {m: misplaced(files, by_name) for m, files in missing.items()}

    def where(mod: str) -> str:
        move = moved[mod]
        if move is None:
            return ""
        was, now, count = move
        return f"; {count} found in {_folder(now)} instead of {_folder(was)}"

    mod_type_fix = (f" Files found in another folder mean Vortex gave the mod another Mod Type than "
                    f"{config.CONFIG['author']}'s: in Vortex, Mods > show the Mod Type column, set it to match "
                    "theirs, then Deploy. Reinstalling the mod doesn't change it.")
    out: list[Finding] = []
    absent = [m for m in missing if len(missing[m]) == len(inventory[m])]
    partial = [m for m in missing if m not in absent]
    if absent:
        out.append(Finding("FAIL", "Deployment", f"{len(absent)} pack mod(s) aren't deployed in the game",
                           "\n".join(vortex.nice_mod_name(m) + where(m).replace("; ", ": ", 1)
                                     for m in absent[:15])
                           + ("\n..." if len(absent) > 15 else ""),
                           "In Vortex: Mods > select them > Enable > Deploy. If a mod isn't listed in "
                           "Vortex, click Repair to install just these again."
                           + (mod_type_fix if any(moved[m] for m in absent) else ""), tuple(absent)))
    if partial:
        lines = [f"{vortex.nice_mod_name(m)}: {len(missing[m])} of {len(inventory[m])} files missing "
                 f"(e.g. {missing[m][0]}){where(m)}" for m in partial[:12]]
        out.append(Finding("WARN", "Deployment", f"{len(partial)} pack mod(s) are missing files",
                           "\n".join(lines) + ("\n..." if len(partial) > 12 else ""),
                           "In Vortex: click Deploy. If files are still missing, click Repair to install "
                           "these mods again."
                           + (mod_type_fix if any(moved[m] for m in partial) else ""), tuple(partial)))
    return out


def setup_check(game: Path, req: dict) -> list[Finding]:
    """Does this game already match the pack? The plugin, load order and deployment checks, for the Home tab."""
    return check_plugins(game, req) + check_deployment(game, config.load_inventory())


def all_mods_in_place(game: Path | None, inventory: dict[str, list[str]] | None = None) -> bool:
    """Every plugin the pack enables is in Data, and every file its mods deployed (files.json) is in the game.

    Then only the load order and settings can differ from the pack. False
    without a game, a pack load order or a files.json (an older build can't tell).
    """
    inventory = config.load_inventory() if inventory is None else inventory
    plugins_txt = paths.PACKINFO / "plugins.txt"
    if not game or not inventory or not plugins_txt.exists():
        return False
    if any(not (Path(game) / "Data" / p).exists() for p in skyrim.enabled_plugins(plugins_txt)):
        return False
    return all(f.level == "OK" for f in check_deployment(Path(game), inventory))


def matches_pack(findings: list[Finding]) -> bool:
    """True if a setup_check found nothing to fix and could compare the load order with the pack's."""
    return all(f.level == "OK" for f in findings) and any(f.area == "Sync" for f in findings)


def check_mods(req: dict) -> list[Finding]:
    out: list[Finding] = []
    pack_mods = req.get("mods") or []
    staging = vortex.staging_dir()
    if not pack_mods:
        return out
    if not staging.is_dir():
        out.append(Finding("WARN", "Mods", "Couldn't find your Vortex mods folder",
                           str(staging), "Manage tab > Change Vortex mods folder."))
        return out
    have = {e.name.lower() for e in staging.iterdir() if e.is_dir()}
    have_short = {vortex.nice_mod_name(n).lower() for n in have}
    missing = [m for m in pack_mods
               if m.lower() not in have and vortex.nice_mod_name(m).lower() not in have_short]
    if missing:
        names = "\n".join(vortex.nice_mod_name(m) for m in missing[:15]) + ("\n..." if len(missing) > 15 else "")
        out.append(Finding("WARN", "Mods", f"{len(missing)} of {len(pack_mods)} pack mods aren't in your Vortex",
                           names,
                           "Run Install again, or drag those zips from Downloads\\Whiney\\ToVortex "
                           "into Vortex."))
    else:
        out.append(Finding("OK", "Mods", f"All {len(pack_mods)} pack mods are in Vortex"))
    return out


def check_system(game: Path | None) -> list[Finding]:
    out: list[Finding] = []
    try:
        free = shutil.disk_usage(game or paths.WORK_DIR.anchor or "/").free
        if free < 5 * 1024 ** 3:
            out.append(Finding("WARN", "System", f"Low disk space ({util.human(free)} free)",
                               "Skyrim needs room for saves and its shader cache.",
                               "Manage tab > Free up space deletes the downloaded pack files."))
    except OSError:
        pass
    if vortex.vortex_running():
        out.append(Finding("WARN", "System", "Vortex is open",
                           fix="Fine for browsing, but close it before installing or launching the game."))
    return out


def run_all(game: Path | None = None, req: dict | None = None,
            progress: Callable[[float, str], object] | None = None) -> list[Finding]:
    req = req if req is not None else config.load_requirements()
    game = game or skyrim.find_game_dir()
    results = []
    groups = [("Basics", lambda: preflight(req, game))]
    if game:
        groups += [("Plugins", lambda: check_plugins(game, req)),
                   ("SKSE plugins", lambda: check_skse_plugins(game, req)),
                   ("Deployment", lambda: check_deployment(game, config.load_inventory()))]
    groups += [("Mods", lambda: check_mods(req)), ("System", lambda: check_system(game))]
    for i, (name, fn) in enumerate(groups):
        if progress:
            progress(i / len(groups), f"Checking {name.lower()}...")
        try:
            results += fn()
        except Exception as e:
            results.append(Finding("WARN", name, f"Couldn't run the {name.lower()} check", f"{type(e).__name__}: {e}"))
    if progress:
        progress(1, "Done.")
    return results


def report_text(results: list[Finding]) -> str:
    lines = [f"{config.CONFIG['pack_name']} - Doctor report ({time.strftime('%Y-%m-%d %H:%M')})",
             f"Sync code: {skyrim.sync_code() or 'n/a'}", ""]
    for r in results:
        lines.append(f"[{r.level}] {r.area}: {r.title}")
        if r.detail:
            lines += [f"    {l}" for l in r.detail.splitlines()]
        if r.fix and r.level != "OK":
            lines.append(f"    Fix: {r.fix}")
    return "\n".join(lines)
