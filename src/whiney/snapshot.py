"""Records the maintainer's Skyrim setup into _packinfo/ for build.bat to bake into the exe.

Purpose:
    Runs on the maintainer's PC only, as `python -m whiney --snapshot`. Copies its
    load order and shared INIs, and writes requirements.json: what the pack
    was built against, which the Doctor and the installer check players
    against. Also migrates the Drive IDs from the old console installer.

Main package:
    _packinfo/: plugins.txt, loadorder.txt, the shared INIs and
    requirements.json (base_version, update_version, base_sha256,
    update_sha256, game_version, skse_dlls, cc_plugins, uses_enb, inis,
    mods, built). The checksums come from pack_manifest.json and
    last_update.json; the installer checks every download against them.
    files.json: for each pack mod, the files Vortex deployed from it into
    this game folder; the Doctor and the installer's final check compare
    players' game folders against it.

Flow:
    1. Make sure pack_config.json exists and has a Drive file ID.
    2. Find the game (or ask), clear _packinfo/.
    3. Copy plugins.txt, loadorder.txt and the INIs.
    4. Write requirements.json and files.json, and print a summary.
"""
import re
import shutil
import time
from pathlib import Path
from typing import Any

from whiney import config, paths, skyrim, util, vortex, winapi


def migrate_config_from_old_script() -> bool:
    """Pull the Drive IDs out of the old console installer's vortex_import.py, so they needn't be retyped."""
    cfg_file = paths.KIT_DIR / paths.CONFIG_NAME
    cfg = util.read_json(cfg_file, {}) or {}
    if cfg.get("drive_file_id") and cfg.get("drive_file_id") != "PASTE_FILE_ID_HERE":
        return False
    old = paths.KIT_DIR / "vortex_import.py"
    if not old.exists():
        return False
    text = old.read_text(encoding="locale", errors="ignore")
    found = {}
    for key, var in (("drive_file_id", "DRIVE_FILE_ID"), ("update_file_id", "UPDATE_FILE_ID"),
                     ("pack_name", "PACK_NAME")):
        m = re.search(rf'^{var}\s*=\s*"([^"]*)"', text, re.M)
        if m:
            found[key] = m.group(1)
    if not found.get("drive_file_id") or found["drive_file_id"] == "PASTE_FILE_ID_HERE":
        return False
    util.write_json(cfg_file, {**config.DEFAULT_CONFIG, **cfg, **found})
    return True


def deployed_inventory(game: Path, staging: Path, mods: list[str]) -> dict[str, list[str]]:
    """For each mod, the files from its staging folder that are deployed in this game folder.

    Recorded from what is actually deployed rather than from the staging
    folder alone, so it follows Vortex's own rules: files a fomod installer
    or Vortex left out, mods kept disabled, and mods deployed to the game
    root (SKSE, ENB) all come out right without this code knowing them.

    Outputs:
        {mod: ["Data/textures/a.dds", "skse64_loader.exe", ...]}, paths
        relative to the game folder as deployed, sorted; mods with no
        deployed file are left out.
    """
    present = skyrim.game_files(game)
    inventory = {}
    for mod in mods:
        folder = Path(staging) / mod
        files = []
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(folder).as_posix()
            # Most mods deploy into Data; SKSE- and ENB-type mods into the game folder itself
            for where in (f"Data/{rel}", rel):
                if where.lower() in present:
                    files.append(where)
                    break
        if files:
            inventory[mod] = files
    return inventory


def snapshot() -> None:
    """Record this PC's setup into _packinfo (run from build.bat)."""
    if migrate_config_from_old_script():
        print(f"Copied your Drive IDs from vortex_import.py into {paths.CONFIG_NAME}.")
    cfg_file = paths.KIT_DIR / paths.CONFIG_NAME
    if not cfg_file.exists():
        util.write_json(cfg_file, config.DEFAULT_CONFIG)
        print(f"Created {paths.CONFIG_NAME}.")
    cfg = util.read_json(cfg_file, {}) or {}
    if not cfg.get("drive_file_id") or cfg["drive_file_id"] == "PASTE_FILE_ID_HERE":
        raise SystemExit(f"\nOpen {paths.CONFIG_NAME} in Notepad and paste your mod pack's Drive file ID into "
                         f'"drive_file_id", then run build.bat again (see docs\\guides\\build.md).')

    out = paths.KIT_DIR / paths.PACKINFO_NAME
    game = skyrim.find_game_dir()
    if not game:
        p = input("Couldn't find Skyrim. Paste the folder that contains SkyrimSE.exe: ").strip().strip('"')
        if not skyrim.is_game_dir(p):
            raise SystemExit("SkyrimSE.exe isn't in that folder.")
        game = Path(p)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()

    for name in ("plugins.txt", "loadorder.txt"):
        src = paths.SKYRIM_APPDATA / name
        if src.exists():
            shutil.copy2(src, out / name)
    if not (out / "plugins.txt").exists():
        raise SystemExit(f"No plugins.txt in {paths.SKYRIM_APPDATA}.")

    inis = []
    for name in skyrim.INI_FILES:
        src = skyrim.ini_dir() / name
        if src.exists():
            shutil.copy2(src, out / name)
            inis.append(name)

    manifest = util.read_json(paths.KIT_DIR / "pack_manifest.json", {}) or {}
    last_update = util.read_json(paths.KIT_DIR / "last_update.json", {}) or {}
    staging = vortex.staging_dir()
    mods = sorted(manifest.get("mods", {}).keys())
    if staging.is_dir():           # current mod list (includes anything added via updates)
        mods = sorted(e.name for e in staging.iterdir()
                      if e.is_dir() and not e.name.startswith("__"))

    loader = game / "skse64_loader.exe"
    req: dict[str, Any] = {
        "base_version": manifest.get("created"),
        "update_version": last_update.get("created") if cfg.get("update_file_id") else None,
        "base_sha256": manifest.get("sha256"),
        "update_sha256": last_update.get("sha256") if cfg.get("update_file_id") else None,
        "game_version": winapi.file_version(game / "SkyrimSE.exe"),
        "skse_dlls": skyrim.skse_dlls(game),
        "skse_loader_version": winapi.file_version(loader) if loader.exists() else None,
        "cc_plugins": skyrim.cc_plugins(game),
        "uses_enb": skyrim.uses_enb(game),
        "inis": inis,
        "mods": mods,
        "built": time.strftime("%Y-%m-%d %H:%M"),
    }
    util.write_json(out / paths.REQ_FILE, req)
    inventory = deployed_inventory(game, staging, mods) if staging.is_dir() else {}
    util.write_json(out / paths.INVENTORY_FILE, inventory)

    print(f"Snapshot written to {out}")
    print(f"  Pack name    : {cfg.get('pack_name')}")
    print(f"  Game version : {req['game_version']}")
    print(f"  SKSE runtime : {', '.join(map(skyrim.skse_runtime_label, req['skse_dlls'])) or 'not installed'}")
    print(f"  CC plugins   : {len(req['cc_plugins'])}")
    print(f"  ENB          : {'yes' if req['uses_enb'] else 'no'}")
    print(f"  INIs         : {', '.join(inis) or 'none'}")
    print(f"  Mods         : {len(mods)} ({len(inventory)} deployed, "
          f"{sum(map(len, inventory.values()))} files recorded for the deployment check)")
    print(f"  Plugins      : {len(skyrim.enabled_plugins(out / 'plugins.txt'))} enabled")
    print(f"  Full pack    : {req['base_version'] or 'unknown (no pack_manifest.json yet)'}")
    print(f"  Update       : {req['update_version'] or 'none'}")
    if req["base_version"] and not req["base_sha256"]:
        print("  Checksum     : none for the full pack (recorded with record_baseline.bat); "
              "downloads of it aren't checked")
