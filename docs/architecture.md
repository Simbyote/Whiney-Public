# Architecture

> How Whiney is put together: the two machines it runs on, what flows between
> them, the modules and their dependencies, where files live, and the known
> structural debt to pay down next.

---

## Two machines, one archive

```
The maintainer's PC                                Each player's PC
───────────────────────────                        ───────────────────────────
Vortex staging folder                              Whiney.exe
   │                                                  │
   ├─ pack_mods.bat ──► modpack.tar.gz ──► Drive ──►  ├─ Install: download, unpack, zip per mod
   │                    modpack_update.tar.gz         │      └─► player drags zips into Vortex
   │                                                  │  then: apply load order + INIs, verify
   └─ build.bat                                       ├─ Doctor: checks against requirements.json
        1. snapshot: plugins.txt, INIs,               ├─ Crash Squatch: launch, watch, explain crashes
           requirements.json ─► _packinfo/            ├─ Host: Skyrim Together server
        2. PyInstaller: app + _packinfo +             └─ Manage: backups, restore, cleanup
           pack_config.json ──► Whiney.exe ──► Drive
```

The archive format is the only contract between the two sides: mod folders
under `mods/`, plus `mods/_update_info.json` in an update.
`tests/test_installer.py` packs with one side and unpacks with the other.

The exe carries the maintainer's load order and settings (`_packinfo/`), so a load-order
change means a new exe even when no mod changed (`guides/build.md`).

---

## Modules

Ten layers: five for the app's logic, then the GUI on top. A module imports
only from layers below it; `tests/test_repo.py` fails the build otherwise.

```
 9   __main__ ────────────────────── entry point: GUI, or --snapshot for build.bat
 8   ui.app ──────────────────────── the window: sidebar, page switching, background work, status
 7   ui.pages.{home, install, doctor, crash, host, manage} ── one per tab; never import each other
 6   ui.widgets  ui.splash ───────── shared building blocks; the startup splash
 5   ui.theme ────────────────────── colors, fonts, customtkinter's appearance
 4   installer ───────────────────── install/update steps; runs doctor's preflight
 3   doctor  crashsquatch  host  manage  snapshot  pack_mods
 2   skyrim  vortex ──────────────── the game install; Vortex and its mod folders
 1   config ──────────────────────── pack config, requirements, player settings, install state
 0   paths  util  winapi ─────────── every location; small helpers; the only door to Windows
```

| Module | Owns | Main package |
| --- | --- | --- |
| `paths` | every real-world location: kit, bundle, work folder, AppData, Vortex | the path constants |
| `util` | JSON files, sizes, replacing a file with a `.bak`, the archive entry check (`safe_member_path`) | none |
| `winapi` | every OS call: registry, version resources, Documents, processes, launching, consoles, hung windows, UAC, opening paths and URLs; `IS_WINDOWS` | none (plain values; `Proc` handles) |
| `config` | the pack's config, requirements.json, the player's settings, install state | `CONFIG`, `install_state()` |
| `skyrim` | the game folder, Documents, version, SKSE, Creation Club, ENB, plugins.txt, sync code | the game folder, the enabled plugin list |
| `vortex` | Vortex.exe, its staging folder, readable mod names | the staging folder |
| `doctor` | health checks; the installer's preflight | `Finding` |
| `crashsquatch` | launching, watching, explaining crashes; the crash history file | `CrashEvent` (with `Analysis`, `Suspect`), `Status` |
| `host` | Skyrim Together: the server (find, start, stop, port, firewall) and the client launcher Play Skyrim Together starts | plain values |
| `manage` | backups, restore, cleanup, uninstall | a save backup zip |
| `snapshot` | the maintainer's setup into `_packinfo/` for build.bat | `requirements.json` |
| `pack_mods` | full and update archives on the maintainer's PC | the archives, `pack_manifest.json` |
| `installer` | the install/update steps, independent of the GUI | `installed.json` |
| `ui.theme` | colors, fonts, `mix()`; sets customtkinter's dark theme on import | the color constants |
| `ui.widgets` | `Card`, `btn`, `label`, `box`, `set_on`, `chip`, `Dialog`, the `Page` base | `Page` |
| `ui.splash` | the animated startup splash | `Splash` |
| `ui.pages.*` | one tab each: Home, Install & Update (with `GuiBridge`, the installer's UI), Doctor, Crash Squatch, Host, Manage | the page class |
| `ui.app` | the window: sidebar, page switching, `run_bg`/`post`, status, dialogs, Crash Squatch wiring | `App` |
| `__main__` | entry point: GUI, or `--snapshot` for build.bat | none |

Rules the layout keeps:

- **Only `winapi` talks to Windows.** No other module imports `winreg`, `ctypes`, `subprocess`, `psutil` or `webbrowser`, or calls `os.startfile` (`test_repo.py` checks). The rule covers Windows integration (registry, Win32 calls, processes, the shell), not all I/O: files are read and written where they're owned, and the network is used directly by `host` (`requests` for the public IP, a UDP `socket` for the LAN address) and by `installer` through `gdown`. Software tests block every socket instead (`conftest.py`). Decisions stay in the module that owns them (which registry key wins, how a crash event is read), as plain code over `winapi`'s return values, so software tests run them against `FakeWinapi`.
- **Archives are unpacked entry by entry, checked first.** Every tar and zip entry passes `util.safe_member_path` (it must land inside the target folder) before anything is written, and the installer accepts only plain files and folders from a tar. The check doesn't rely on tarfile's `data` filter, which Pythons before 3.10.12 / 3.11.4 lack (`test_installer.py` runs both).
- **Only `ui/` imports tkinter** (`test_repo.py` checks). Everything else runs headless, which is what lets the packer, `--snapshot` and the tests import it.
- **`installer` talks to the GUI only through its UI protocol** (`step`, `log`, `progress`, `ask`, `tell`, `wait_for_user`) and a `cancel` event, so it can be driven by a `FakeUI` in tests. Cancelling raises `installer.Cancelled` (an `Abort`) at the next safe point; every step already resumes after an interruption, so a cancel needs no cleanup beyond gdown's partial files.
- **Import modules, not names**: `from whiney import paths` then `paths.WORK_DIR`, never `from whiney.paths import WORK_DIR`. A name imported directly is a copy the test sandbox can't redirect. The one exception is inside `ui/`: theme colors and widget helpers are imported by name (`from whiney.ui.theme import GOLD`), because nothing ever patches them and it keeps the pages readable. (`pack_mods` builds its own `HERE`, `MANIFEST` and `LAST_UPDATE` from `paths.KIT_DIR` at import; the sandbox patches those in `pack_mods` itself, and fails any test where a whiney module still holds a real path.)
- **Imports are absolute** (`from whiney import config`), so the same code runs as a package, from PyInstaller, and under pytest.
- **`crash_history.json` is a file format**: `CrashEvent.to_json` writes the exact shape earlier versions wrote and `from_json` reads all of them; `test_crashsquatch.py` round-trips a fixture of every shape.
- **`requirements.json` is a contract**: `snapshot` writes it on the maintainer's PC and `config`, `doctor` and `installer` read it on every player's. `test_snapshot.py` fails if the app reads a key snapshot doesn't write.

---

## Where files live

| Name | Where | What's there |
| --- | --- | --- |
| `paths.KIT_DIR` | the repo root | `.bat` files, `pack_config.json`, manifests, `_packinfo/` (from source only) |
| `paths.BUNDLE_DIR` | `KIT_DIR` from source; PyInstaller's `_MEIPASS` in the exe | `pack_config.json`, `_packinfo/`, `assets/` as bundled |
| `paths.WORK_DIR` | `Downloads\Whiney` | downloads, extracted pack, zips for Vortex, `installed.json`, settings, logs, save backups |
| `paths.SKYRIM_APPDATA` | `%LOCALAPPDATA%\Skyrim Special Edition` | `plugins.txt`, `loadorder.txt` |
| `skyrim.my_games_dir()` | `Documents\My Games\Skyrim Special Edition` | INIs, saves, SKSE crash logs |
| `vortex.staging_dir()` | Vortex's mods folder (setting, else `%APPDATA%\Vortex\skyrimse\mods`) | one folder per installed mod |

`paths.py` sits at `src/whiney/paths.py`, so `KIT_DIR` is `parents[2]` of it.
`tests/test_paths.py` checks that `build.bat` is really there, and the test
sandbox fails any run where a path constant in `paths.py` isn't redirected.

---

## Testing

Two modes, one marker each (`guides/pytest.md`):

- **software**: pure logic on hand-built files, inside a sandbox that redirects every path above into a temp folder and replaces `winapi` with `FakeWinapi` (a dict registry, a process list, recorded launches). Any OS; CI runs it on Ubuntu and Windows on every push. On the Windows runner only, `test_windows.py` also writes the registry entries Steam and Vortex create and checks detection against the real API, and `test_winapi.py` reads real Win32 values.
- **live**: read-only checks on Windows Python against a real install; output in `artifacts/`.

Meta-tests keep the non-Python parts honest: `test_repo.py` (the `.bat` files, the build command, pins, the Makefile) and `test_docs.py` (this documentation standard).

---

## Known structural debt

The baseline moved the code without redesigning it, so these are recorded
here rather than fixed silently. Each is a candidate for a small, tested step.

1. **customtkinter has no types.** The whole package is annotated and mypy rejects an unannotated function (`make lint`, CI). Widgets, though, are `Any` to mypy (`ui.widgets.Widget`), so widget calls aren't checked, and `App`, which subclasses customtkinter's `CTk`, would pass for any protocol. The window's contract with its pages, `ui.widgets.AppShell`, is therefore checked from the source by `test_repo.py`; `GuiBridge` against the installer's `InstallerUI` is checked by mypy. Function docstrings predate the standard and are brought up to it as code is touched (`_DOCUMENTATION.md`).
2. **Untested paths**: the real Google Drive (the installer is tested against `FakeGdown`; how Drive answers today is only seen on a real install). The GUI is started and every tab opened (`test_gui.py`), but no button is clicked.
3. **App files use the Windows locale encoding** (`encoding="locale"`, explicit since the CI fix, but unchanged behavior). Right for game files and tool output; the app's own JSON and marker files could move to UTF-8 deliberately, once old players' files are known to be ASCII (JSON is, by default).
4. **Small leftovers**: `pack_mods.human` duplicates `util.human`; `doctor.check_plugins` and `check_skse_plugins` take a `req` they don't use.
