# Building and publishing the pack

> The maintainer's procedures: packing mods, building `Whiney.exe` and
> publishing both to the shared Drive. Every procedure runs a `.bat` file in
> the kit folder (the repository root) on Windows; no code changes are
> involved. The players' guide is `release/README.txt` and is published next
> to the exe.

---

## The kit

Commands, in the kit folder:

| File | Function |
| --- | --- |
| `build.bat` | Records the current Skyrim setup (`--snapshot`) and builds `dist\Whiney.exe` |
| `pack_mods.bat` | Full pack: `modpack.tar.gz` + `pack_manifest.json` (with the archive's SHA-256) |
| `pack_update.bat` | Update pack: `modpack_update.tar.gz` + `last_update.json` (with the archive's SHA-256) |
| `record_baseline.bat` | One-time: records the manifest of a full pack that is already uploaded. No checksum is recorded, so players' downloads of that pack aren't checked |
| `test_app.bat` | Runs the app from source, without building |

Local state, in the kit folder and never in the repository:

| File | Content |
| --- | --- |
| `pack_config.json` | Pack name, author and Drive file IDs. Created by `build.bat` on first run with placeholders |
| `pack_manifest.json` | Per-mod fingerprints of the last full pack (written by `pack_mods.bat`) |
| `last_update.json` | Contents of the last update (written by `pack_update.bat`) |

These three files are not tracked, so pulling new app versions never
overwrites them. They are needed for every later update and should be backed
up.

## The deployment inventory

`build.bat` also records which files each pack mod deployed into the game
folder (`_packinfo/files.json`); players' Doctor and final install check
compare against it. It is recorded from what is deployed on the building PC,
so build with every pack mod enabled and deployed in Vortex. A mod that is
disabled while building is left out and never checked.

Files the game writes into a mod's folder while it runs are left out of packs,
`files.json` and the check (`skyrim.RUNTIME_DIRS`): today that's Skyrim
Together's Chromium cache, `SkyrimTogetherReborn\cache`. Vortex pulls it into
the mod's staging folder after you play, and each PC's is different, so it would
otherwise be packed, re-packed in every update, and reported missing on players'
PCs.

## Checksums

Each pack run records the SHA-256 of the archive it wrote, and `build.bat`
bakes it into the exe. Players' installers refuse a download that doesn't
match. Two consequences:

- The exe on Drive and the archive on Drive must come from the same pack run.
  After every `pack_mods.bat` or `pack_update.bat`, run `build.bat` and
  replace the exe, as the procedures below do. An old exe refuses a new
  archive with "doesn't match … ask for the latest app".
- Upload exactly the file the `.bat` wrote. A re-compressed or renamed-and-
  re-zipped copy has a different checksum.

---

## Published on the shared Drive

- `Whiney.exe` (zipped, which browsers flag less) and `release/README.txt`
- `modpack.tar.gz`, and `modpack_update.tar.gz` once an update exists

Every file is shared as "Anyone with the link".

---

## Getting new app versions

The code is in a private GitHub repository.

1. First time: accept the GitHub invitation and clone the repository into the
   kit folder (GitHub Desktop: File > Clone repository; or
   `git clone https://github.com/Simbyote/Whiney.git`).
2. Copy `pack_config.json`, `pack_manifest.json` and `last_update.json` into
   the clone.
3. For each new version: Fetch/Pull (or `git pull`), then run `build.bat`.

---

## Procedures

### Migrating from the console installer (once)

1. Copy the kit's files into the existing kit folder (the one containing
   `vortex_import.py` and `pack_manifest.json`), replacing older files.
2. Run `build.bat`. It copies the Drive IDs from `vortex_import.py` into
   `pack_config.json`; they can also be entered there by hand.
3. Upload `dist\Whiney.exe` and `release/README.txt`.

Players who installed with the console installer are recognized as installed
and do not reinstall.

### First full pack

1. Close Vortex. Run `pack_mods.bat`. If the mods folder is not Vortex's
   default (`%APPDATA%\Vortex\skyrimse\mods`), drop the folder onto the `.bat`.
2. Upload `modpack.tar.gz`, share it as "Anyone with the link", and open the
   link in a private browser window to confirm it doesn't ask for a sign-in.
   The file ID is the part of the link between `/d/` and `/view`.
3. In `pack_config.json`, set `"drive_file_id"` and `"pack_name"`; leave
   `"update_file_id": ""`.
4. Run `build.bat`. Upload the exe and `release/README.txt`.

### Mods added, updated or removed

1. Close Vortex. Run `pack_update.bat`.
2. Upload `modpack_update.tar.gz`. If one is already on Drive, use
   right-click > Manage versions > Upload new version, which keeps the file ID.
3. First update only: set its file ID as `"update_file_id"`.
4. Run `build.bat` and replace the exe on Drive.

Players' Home section then reads "Update ready"; Install & Update in
"Update only" mode applies it.

Updates are cumulative: each one holds every change since the last full pack,
so a player who skipped an update still ends up current.

### Load order or INI settings changed only

Close Vortex, run `build.bat`, replace the exe on Drive. The load order and
INIs travel inside the exe, so no pack upload is needed.

### Starting over with a new full pack

For a large overhaul, or when the update has grown close to the full pack's
size: run `pack_mods.bat`, upload it as a new version of `modpack.tar.gz`, set
`"update_file_id": ""`, and run `build.bat`. Every player reinstalls the full
pack (Vortex asks to Replace each mod).

---

## Testing a change

`test_app.bat` runs the app from source. `build.bat` must have run once so the
packages and `_packinfo` exist. Errors are logged to
`Downloads\Whiney\app_log.txt`.

Development testing (pytest, make, WSL) is described in `pytest.md` and
`make.md`; what each section of the exe does is in `ui.md`.
