"""Packs Vortex's Skyrim SE mods (staging) folder into the archives players install.

Purpose:
    Runs on the maintainer's PC (pack_mods.bat, pack_update.bat,
    record_baseline.bat). A full pack holds every mod; an update is
    CUMULATIVE: everything that changed since the last FULL pack, so a
    player who skipped an update still ends up correct. Each new update
    replaces the previous one. When updates get big, do a new full pack.

Main package:
    modpack.tar.gz / modpack_update.tar.gz: mod folders under mods/, plus
    mods/_update_info.json (added, changed, removed) in an update.
    pack_manifest.json: per-mod fingerprints of the last full pack, which
    the next update is compared against, and the archive's SHA-256.
    last_update.json: the last update's contents and its archive's SHA-256.
    build.bat bakes both checksums into the exe, which checks every download.

Flow:
    1. Pick the staging folder (argument, Vortex's default, or ask).
    2. Fingerprint each mod folder (names, sizes, modified times).
    3. Full: tar everything, save the manifest. Update: diff against the manifest, tar the changes.
    4. Record the archive's SHA-256 next to it (manifest or last_update.json).

Command line:
    py -m whiney.pack_mods [mods_folder] [--update | --baseline] [-o output] [--level 1-9]
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

from whiney import paths, util, winapi

ARC_ROOT = "mods"     # top folder inside the tarball; the installer skips it automatically
# Outputs and manifests sit in the kit folder, beside the .bat files that run this
HERE = paths.KIT_DIR
MANIFEST = HERE / "pack_manifest.json"
LAST_UPDATE = HERE / "last_update.json"      # read by build.bat so the app knows an update exists
UPDATE_INFO = "_update_info.json"


def default_staging() -> Path:
    return paths.VORTEX_STAGING


def longpath(p: str | Path) -> str:
    """Windows long-path prefix so >260-char paths can be read."""
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def vortex_running() -> bool:
    return winapi.process_running("Vortex.exe")


def mod_dirs(src: Path) -> list[str]:
    return sorted(e.name for e in src.iterdir() if e.is_dir() and not e.name.startswith("__"))


def scan(src: Path, mods: list[str]) -> tuple[list[tuple[str, str, int]], int]:
    """All files of the given mod folders -> [(full_path, arcname, size)], total size."""
    files, total = [], 0
    base = longpath(src)
    for mod in mods:
        for dirpath, dirnames, filenames in os.walk(os.path.join(base, mod)):
            dirnames.sort()
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                files.append((full, f"{ARC_ROOT}/{rel}", size))
                total += size
    return files, total


def fingerprint(src: Path, mod: str) -> str:
    """Cheap per-mod fingerprint from file names, sizes and modified times."""
    h = hashlib.sha1()
    root = os.path.join(longpath(src), mod)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            h.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8", "replace"))
    return h.hexdigest()


def pick_source(arg: str | None) -> Path:
    if arg:
        src = Path(arg.strip('"'))
    else:
        src = default_staging()
        if not src.is_dir():
            print(f"Couldn't find Vortex's default mods folder:\n  {src}")
            print("(Vortex > Settings > Mods > 'Mod Staging Folder' shows where yours is.)")
            src = Path(input("Paste your mods folder path: ").strip().strip('"'))
    if not src.is_dir():
        sys.exit(f"Not a folder: {src}")
    if not (src / "__vortex_staging_folder").exists():
        print(f"Warning: {src} doesn't look like a Vortex mods folder "
              "(no __vortex_staging_folder marker).")
        if input("Pack it anyway? [y/N] ").strip().lower() != "y":
            sys.exit("Cancelled.")
    return src


def write_tar(src: Path, mods: list[str], out: Path, level: int, extra: dict[str, Any] | None = None) -> bool:
    """Pack the given mod folders (plus an optional JSON info file) into out."""
    print("Scanning files...")
    files, total = scan(src, mods)
    print(f"{len(mods)} mods, {len(files)} files, {util.human(total)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out.parent).free
    if free < total * 1.05:
        print(f"Warning: only {util.human(free)} free on the output drive (up to {util.human(total)} needed).")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit("Cancelled.")

    part = out.with_name(out.name + ".part")
    failed, done = [], 0
    start = last = time.time()
    with tarfile.open(part, "w:gz", compresslevel=level, format=tarfile.PAX_FORMAT) as tar:
        if extra is not None:
            data = json.dumps(extra, indent=2).encode()
            ti = tarfile.TarInfo(f"{ARC_ROOT}/{UPDATE_INFO}")
            ti.size, ti.mtime = len(data), int(time.time())
            tar.addfile(ti, io.BytesIO(data))
        for i, (full, arcname, size) in enumerate(files, 1):
            try:
                tar.add(full, arcname=arcname, recursive=False)
            except OSError as e:
                failed.append((arcname, e))
            done += size
            now = time.time()
            if now - last >= 1 or i == len(files):
                last = now
                elapsed = now - start
                rate = done / elapsed if elapsed else 0
                eta = (total - done) / rate if rate else 0
                pct = 100 * done / total if total else 100
                print(f"\r  {pct:5.1f}%  {util.human(done)} / {util.human(total)}  "
                      f"{util.human(rate)}/s  ETA {int(eta // 60)}m{int(eta % 60):02d}s   ",
                      end="", flush=True)
    print()

    if failed:
        print(f"\n{len(failed)} file(s) could not be read:")
        for arc, err in failed[:20]:
            print(f"  - {arc}: {err.strerror or err}")
        if len(failed) > 20:
            print(f"  ...and {len(failed) - 20} more")
        print(f"\nThe archive is incomplete and was left as {part.name}.")
        print("Close Vortex (and anything else using those files) and run this again.")
        return False

    os.replace(part, out)
    took = time.time() - start
    print(f"\nDone in {int(took // 60)}m{int(took % 60):02d}s: {out} ({util.human(out.stat().st_size)})")
    return True


def archive_checksum(out: Path) -> str:
    """SHA-256 of a finished archive, recorded so players' downloads can be checked against it."""
    print("Computing the checksum...")
    digest = util.sha256_file(out)
    print(f"SHA-256: {digest}")
    return digest


def full_pack(src: Path, out: Path, level: int) -> bool:
    mods = mod_dirs(src)
    if not mods:
        sys.exit("No mod folders found.")
    print(f"FULL pack of {src}")
    print("Fingerprinting mods (for future updates)...")
    prints = {m: fingerprint(src, m) for m in mods}
    if not write_tar(src, mods, out, level):
        return False
    digest = archive_checksum(out)
    MANIFEST.write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "sha256": digest,
                                    "mods": prints}, indent=2), encoding="locale")
    if LAST_UPDATE.exists():
        LAST_UPDATE.unlink()                   # a fresh full pack has no update yet
    print(f"Saved {MANIFEST.name} (remembers what's in this full pack).")
    print("\nNext: upload modpack.tar.gz to Drive. If it replaces an older full pack,")
    print("use Drive's 'Manage versions > Upload new version' to keep the same link.")
    print('Set "update_file_id": "" in pack_config.json (no update yet), then run build.bat.')
    return True


def baseline_only(src: Path) -> bool:
    """Record the manifest for a full pack that's already uploaded, without re-packing."""
    mods = mod_dirs(src)
    print(f"Recording {len(mods)} mods as the baseline (no archive is written)...")
    prints = {m: fingerprint(src, m) for m in mods}
    MANIFEST.write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"),
                                    "mods": prints}, indent=2), encoding="locale")
    print(f"Saved {MANIFEST.name}. Future pack_update.bat runs compare against this.")
    print("Only do this if your mods haven't changed since you made the uploaded full pack.")
    print("No checksum is recorded for it, so players' downloads of it aren't checked.")
    return True


def update_pack(src: Path, out: Path, level: int) -> bool:
    if not MANIFEST.exists():
        sys.exit("No pack_manifest.json found. Do a full pack (pack_mods.bat) first.")
    base = json.loads(MANIFEST.read_text(encoding="locale"))
    old = base["mods"]
    print(f"UPDATE pack vs. full pack from {base.get('created', '?')}")
    print("Comparing mods...")
    now = {m: fingerprint(src, m) for m in mod_dirs(src)}

    added = sorted(m for m in now if m not in old)
    changed = sorted(m for m in now if m in old and now[m] != old[m])
    removed = sorted(m for m in old if m not in now)
    for label, names in (("Added", added), ("Changed", changed), ("Removed", removed)):
        print(f"  {label}: {len(names)}")
        for n in names:
            print(f"    - {n}")

    if not (added or changed or removed):
        print("\nNo mod changes since the full pack.")
        print("If you only changed the load order or INIs, just run build.bat and send the new exe.")
        return True

    created = time.strftime("%Y-%m-%d %H:%M")
    info = {"added": added, "changed": changed, "removed": removed, "created": created}
    if not write_tar(src, added + changed, out, level, extra=info):
        return False
    digest = archive_checksum(out)
    LAST_UPDATE.write_text(json.dumps({"created": created, "sha256": digest, **info}, indent=2),
                           encoding="locale")
    print("\nNext:")
    print(f"  1. Upload {out.name} to Drive. If an older update is already there, use")
    print("     'Manage versions > Upload new version' so the file ID stays the same.")
    print('  2. Put its file ID in "update_file_id" in pack_config.json (first time only).')
    print("  3. Run build.bat and upload the new exe.")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Pack your Vortex mods folder into a tarball")
    ap.add_argument("source", nargs="?", help="mods folder (default: Vortex's Skyrim SE staging folder)")
    ap.add_argument("--update", action="store_true",
                    help="pack only mods added/changed since the last full pack")
    ap.add_argument("--baseline", action="store_true",
                    help="only record pack_manifest.json for an already-uploaded full pack")
    ap.add_argument("-o", "--output", help="output file (default: the kit folder)")
    ap.add_argument("--level", type=int, default=1, choices=range(1, 10),
                    help="gzip level: 1 = fast (default), 9 = smallest but much slower")
    args = ap.parse_args()

    if vortex_running():
        sys.exit("Vortex is open. Close it (check the system tray too) so no files are locked, then run again.")

    src = pick_source(args.source)
    default_name = "modpack_update.tar.gz" if args.update else "modpack.tar.gz"
    out = Path(args.output) if args.output else HERE / default_name
    if args.baseline:
        ok = baseline_only(src)
    else:
        ok = (update_pack if args.update else full_pack)(src, out, args.level)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled. Any half-written .part file can be deleted.")
