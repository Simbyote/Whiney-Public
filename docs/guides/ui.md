# Application sections

> Reference for every section of `Whiney.exe`: what each control does,
> the states it shows, the files it reads and writes, and the module behind it.
> Labels are quoted exactly as they appear. `{pack_name}` and `{author}` come
> from `pack_config.json` (`config.CONFIG`).

**Code:** `src/whiney/ui/` · **Tests:** `test_gui.py` (starts the window, opens every section, renders Doctor results and a crash)

---

## Startup

1. A borderless splash (`ui/splash.py`) is shown for at least 2.8 s while the
   first status is gathered off the GUI thread: the game folder
   (`skyrim.find_game_dir`), the install state (`config.install_state`), the
   sync code (`skyrim.sync_code`) and the setup check (`doctor.setup_check`:
   Doctor's plugin, load order and deployment checks against the pack).
2. The main window is built and faded in on **Home**.
3. If `SkyrimSE.exe` is already running, a dialog offers **Watch it** /
   **No thanks**. "Watch it" attaches Crash Squatch without launching the game
   (this works without a known game folder).

An unhandled exception in a GUI callback is reported in a "Something went
wrong" dialog; the traceback goes to `Downloads\Whiney\app_log.txt`.

---

## Window and sidebar

| Element | Behavior |
| --- | --- |
| Logo, `{pack_name}`, "by `{author}`" | Static header |
| Navigation | **Home**, **Install & Update**, **Doctor**, **Crash Squatch**, **Host Server**, **Manage**. One page is shown at a time; each page's `on_show()` refreshes it |
| Status lines | "Skyrim found ✓" / "Skyrim not found"; "Pack installed ✓" / "Update available" / "Pack not installed"; "Crash Squatch: on" while watching |

Long-running work (downloads, checks, IP lookups) runs on worker threads and
posts its result back to the GUI thread (`App.run_bg`, `App.post`); the window
stays responsive throughout.

---

## Home

The readiness summary: install state, game, sync code and the main actions.

| Element | Content |
| --- | --- |
| Title | `{pack_name}`, then "by `{author}`" and the build time from `requirements.json` ("built …") |
| **📖 Installation guide** | Top right. Opens the players' guide (`release/README.txt`, bundled into the exe by `build.bat`; `paths.GUIDE`) in a read-only window, with **Open in Notepad**. While the pack isn't installed, the Mod pack card points to it |
| **Mod pack** card | "Installed" (button reads **Reinstall**), "Update ready" (**Update**), or "Not installed" (**Install**) |
| **Game** card | "Skyrim SE {version}" with "SKSE ready" / "SKSE not installed", or "Not found" with a pointer to Manage |
| **Sync code** card | The `XXXX-XXXX` code of the active load order; **Copy** puts it on the clipboard |
| **Setup check** card | Whether the game already matches the pack: "Matches the pack ✓" (same load order, every file of the pack's mods deployed), "N difference(s) from the pack" with the first three, or "Not checked" (no game, or no pack load order in this build). **See details** opens Doctor and runs it. **Apply the pack's load order** shows when the load order differs but every pack mod is already in the game (`doctor.all_mods_in_place`): after Vortex is closed and the player chooses load order only or load order + INIs, it writes them like the install's `order` step (`installer.apply_load_order`; theirs kept as `.bak`) without installing anything. Gathered at startup and on every status refresh |
| **▶ Play (SKSE)** | Single-player: launches `skse64_loader.exe` (or `SkyrimSE.exe` without SKSE) from the game folder and starts Crash Squatch. Disabled when the game isn't found; asks first when the pack isn't installed |
| **⇄ Play Skyrim Together** | Multiplayer: launches `Data\SkyrimTogetherReborn\SkyrimTogether.exe` from its own folder and starts Crash Squatch, which follows `SkyrimSE.exe`. Only the deployed copy is used; disabled when it isn't deployed |
| Hint | Which button starts what, or why one is disabled |
| **Install** / **Update** / **Reinstall** | Opens Install & Update |
| **Run Doctor** | Opens Doctor and starts the checks |
| Notice | One of, in this order: "Your game already matches the pack…" with **Use my current setup** (not installed, but the setup check matches: records the pack as installed without running the installer; the pack's INIs are not applied), "An update from `{author}` is ready…" with **Get the update**, or the last crash or freeze from Crash Squatch's history with **See details** |

---

## Install & Update

Runs `installer.Installer` on a worker thread; `GuiBridge` relays its calls to
the page. Each step is re-runnable: completed work is detected and skipped.

| Element | Behavior |
| --- | --- |
| **Mode** | **Full install** (download the full pack, then the update if one is configured) or **Update only** (download and apply the update) |
| **I already have the file...** | Picks a copy of the full pack or the update (e.g. from a USB stick) to use instead of downloading it; the label names it, **Don't use it** clears it. It's checked against the recorded SHA-256 when it's needed and copied, never moved; a file that is neither stops the install untouched |
| "Use `{author}`'s game settings (INIs)" | When cleared, the pack's `Skyrim.ini` / `SkyrimCustom.ini` are not applied; the load order still is |
| **Start** | Runs the steps below; reads **Working...** while running |
| **Cancel** | Shown while running. After a confirmation ("Cancel install" / "Keep going") the installer stops at the next safe point: between steps, between download chunks (gdown's `cancel`), between archive entries, mods being zipped and checksum blocks, and at the Vortex and browser-download waits. The step shows as cancelled, the log says so, and nothing finished is lost: **Start** resumes, skipping finished steps. A cancelled download leaves no partial files |
| **STEPS** | Each step is shown as active, done, skipped, failed or cancelled |
| Log and progress bar | Every step's messages; the download shows size and speed |
| Action area | Appears when the installer needs the player: confirmation questions, the browser download, the Vortex hand-off |

| Step | Shown as | What it does |
| --- | --- | --- |
| `check` | Check your PC | Doctor's preflight checks; a failure asks whether to continue. Then, when every plugin the pack enables is in `Data` and every file in `files.json` is in the game, it offers to skip straight to `order`: the steps from `download` to `vortex` show as skipped (builds without `files.json` always run in full) |
| `download` | Download the mod pack | Skipped when `ToVortex` was prepared from this pack (`.base_ready`). Otherwise uses, in order: the picked file, a `.gz` in `Downloads` with the recorded SHA-256 (only files of the recorded size are hashed; moved in), or downloads `modpack.tar.gz` from Google Drive and checks it against the SHA-256 recorded when it was packed; a mismatch deletes it and stops (the next **Start** downloads it again). If Drive refuses, the file page opens in the browser and the step waits for the download in `Downloads` (**It's downloaded**, **Open download page again**, **Open Downloads folder**) |
| `unpack` | Unpack it | Extracts the archive (needs ~3x its size free). An entry that would land outside the unpack folder, or a link, deletes the archive and stops the install |
| `prepare` | Prepare mods for Vortex | One `.zip` per mod in `Downloads\Whiney\ToVortex`, up to 4 mods at a time (`installer.ZIP_WORKERS`); files that are already compressed (audio, images, nested archives) are stored, the rest deflated |
| `update` | Get the latest update | Skipped when `ToVortex` already holds this update (`.update_ready`). Otherwise gets `modpack_update.tar.gz` the same way as the pack (or reuses one from an earlier run), checks its SHA-256, and applies it to `ToVortex`: new and changed mods are zipped, removed mods' zips are dropped. **Update only** also copies the update's zips into `ToVortex_Update` for the hand-off, so `ToVortex` stays whole and a later Full install needn't download anything |
| `vortex` | Install in Vortex (your turn) | Opens the zip folder (`ToVortex`; `ToVortex_Update` for Update only) and starts Vortex, then waits for **Done, Vortex is closed**. Lists mods to remove in Vortex after an update. Repeats the wait while Vortex is still running |
| `order` | Set load order & settings | Copies the pack's `plugins.txt`, `loadorder.txt` and INIs into place; the replaced files are kept as `.bak` |
| `verify` | Make sure everything's in place | Every plugin the pack enables must exist in `Data`; otherwise it stops and lists the missing ones. Then every file the pack's mods deployed on the maintainer's PC (`files.json`) must be in the game folder; missing ones are logged per mod and the player chooses to stop or finish anyway |

On success `installed.json` records the full pack and update installed; Home and
the sidebar then read "Installed".

**Repair** (the Doctor's **Repair** button) runs the installer's `repair` mode on
just that card's mods and starts at once; the page shows these steps instead:

| Step | Shown as | What it does |
| --- | --- | --- |
| `gather` | Find the mods to repair | One zip per mod in `Downloads\Whiney\Repair`. Taken from `ToVortex` while this pack is the one installed; otherwise unpacked from the update (first: a mod it changed is older in the full pack) and then the full pack, each checked against its SHA-256 and, if it's gone, downloaded again after asking. Only those mods' entries are unpacked. A mod in neither stops the repair |
| `vortex` | Install in Vortex (your turn) | As above, on the `Repair` folder; also says that a mod whose files went to another folder needs its Mod Type matched, which reinstalling doesn't change |
| `verify` | Make sure everything's in place | The deployment check on just the repaired mods; anything still missing stops with where the files are and the fix |

A repair doesn't touch `installed.json`, the load order or the INIs.

---

## Doctor

Runs `doctor.run_all` and shows one card per finding, most severe first.

| Element | Behavior |
| --- | --- |
| **Run checks** / **Run again** | Runs every check group: basics (Vortex, game, version, SKSE, Creation Club, ENB), plugins (missing files, masters, order, the 254 full-plugin limit, sync with the pack), SKSE plugins (Address Library, crash logger), deployment (every file the pack's mods deploy is in the game folder: FAIL for a mod with none, WARN for one missing some; missing files found in another folder are named with where they are, which means Vortex gave the mod another Mod Type than the maintainer's), mods (pack mods present in Vortex), system (disk space, Vortex open) |
| Counts | "N problems" (FAIL), "N warnings" (WARN), "N fine" (OK) |
| Status line | "Found problems…", "Nothing serious…" or "Everything looks healthy." |
| Finding card | Area, title, detail lines, and "→ fix" for WARN and FAIL. A Sync card has **Apply the pack's load order** when every pack mod is in the game (as on Home). A deployment card also has **Repair N mod(s)**: opens Install & Update and reinstalls just those mods (see Repair above) |
| **Copy report** | The full text report (`doctor.report_text`) to the clipboard |
| **Save report** | Writes `Downloads\Whiney\doctor_report_<date>-<time>.txt` and opens the folder |

A FAIL means the game will crash or the install will fail; a WARN is worth a
look. The report format is fixed by `test_doctor_report.py`.

---

## Crash Squatch

The face of `crashsquatch.CrashSquatcher`, which runs on its own thread.

| Element | Behavior |
| --- | --- |
| Status | "Not watching", "Starting Skyrim..." (waiting up to 90 s for the process), "Skyrim is running, watching" with play time and RAM, "Skyrim froze", or "Skyrim closed normally after …" |
| **▶ Play (SKSE)**, **⇄ Play Skyrim Together** | Same as Home; disabled while a session is starting |
| **Watch running game** | Attaches to a running `SkyrimSE.exe` without launching it |
| **Stop watching** | Stops the watcher; the game keeps running |
| **HISTORY** | Crashes and freezes from `crash_history.json` (newest 50), newest first. Selecting one shows its details |
| Details | Time and summary; **SUSPECTS (most likely first)** with the mod and file; **Open crash log**; **Copy for `{author}`**; **Run Doctor** |

How an ending is classified ("this session" starts when the game process started; when Windows won't give that time, e.g. for a game run as administrator, when watching started):

| Ending | Source | Recorded |
| --- | --- | --- |
| Crash with a log | Every Crash Logger / Trainwreck / .NET Script Framework log written since the game started (older logs belong to earlier sessions and are ignored). With several crash loggers installed, each log is analyzed and the suspects merged: a file several logs point at adds up its scores. The details then offer **Open crash log** and **Log 2**, … for each: DLLs ranked by call-stack depth, plugins by mentions, each mapped to its Vortex mod (when several mods ship that file name, the one whose copy is deployed in the game, by hard link or identical bytes; otherwise all of them, "Mod A or Mod B") | Yes |
| Crash without a log | Windows' Application Error event from this session (wevtutil's UTC dates are compared as UTC): the faulting module and exception code | Yes |
| Freeze | The game window "Not Responding" for 20 s | Yes |
| Normal exit | None of the above | No |

On a crash or freeze the window is brought to the front and switches to this
section.

---

## Host Server

Skyrim Together Reborn server management for the hosting player
(`host.py`).

| Element | Behavior |
| --- | --- |
| **SERVER** | "Running", "Stopped" or "Server not found" (the server is looked up in the deployed `Data` folder, then in Vortex's staging folder), with its path |
| **Start server** / **Stop** | Starts `SkyrimTogetherServer.exe` in its own console window / terminates it |
| **ADDRESS TO SHARE** | `<public IP>:<port>` (the port is `uPort` in `STServer.ini`, default 10578), plus the LAN address for players on the same network |
| **Copy address** / **Refresh** | Copies the public address / re-checks everything |
| Windows Firewall | Whether an inbound UDP rule exists for the port. **Allow through firewall** adds it through a UAC prompt |
| **IF FRIENDS CAN'T CONNECT** | Port forwarding, the firewall, and CGNAT (where a VPN such as Tailscale or Radmin replaces port forwarding) |

---

## Manage

Maintenance actions, each a thin call into `manage.py`.

| Section | Controls | Behavior |
| --- | --- | --- |
| Saves | **Back up saves now**, **Open backups folder**, **Restore** per backup | Backups are zips in `Downloads\Whiney\save_backups`. Restoring backs up the current saves first, then asks: **Merge** (the default: adds the backup's files back; saves made since stay, same-named ones are overwritten) or **Replace** (the folder becomes exactly the backup; everything else is deleted, only after the safety backup is read back and holds every current file). A backup with an entry outside the saves folder is refused before anything changes |
| Your original settings | **Restore my settings** | Puts back the `.bak` copies of `plugins.txt`, `loadorder.txt` and the INIs that installing made |
| Disk space | **Free up space** (shows the size) | Deletes the downloaded and extracted pack files; keeps `installed.json` and settings, so updates still work |
| Folders | **Game folder**, **Skyrim settings**, **Saves**, **Crash logs**, **App files**; **Change game folder**, **Change Vortex mods folder** | Opens each folder in Explorer. The two pickers save the choice in `settings.json`; the game folder must contain `SkyrimSE.exe` |
| Remove the pack | **Uninstall pack...** | Restores the original settings, deletes the downloaded files and forgets the install. Mods are removed in Vortex (Mods > select > Remove > Deploy) |

---

## Files the application writes

All under `Downloads\Whiney` unless noted (`paths.py`):

| File | Written by |
| --- | --- |
| `modpack.tar.gz`, `modpack_update.tar.gz`, `extracted\`, `ToVortex\` | Install & Update (removed by Manage > Free up space) |
| `installed.json` | Install & Update, on success |
| `settings.json` | Manage > Change game folder / Change Vortex mods folder |
| `crash_history.json` | Crash Squatch |
| `save_backups\Saves-<date>-<time>.zip` | Manage > Saves |
| `doctor_report_<date>-<time>.txt` | Doctor > Save report |
| `app_log.txt` | Errors from the windowed exe |
| `plugins.txt`, `loadorder.txt` (+ `.bak`) in `%LOCALAPPDATA%\Skyrim Special Edition` | Install & Update > Set load order |
| `Skyrim.ini`, `SkyrimCustom.ini` (+ `.bak`) in `Documents\My Games\Skyrim Special Edition` | Install & Update > Set load order (unless cleared) |
