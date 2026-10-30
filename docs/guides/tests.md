# What each test file covers

> One line per file: what it proves, and what it deliberately leaves out.
> Run them with `make test` / `make test-live` (`pytest.md`).

| File | Mode | Proves | Not covered |
| --- | --- | --- | --- |
| `test_paths.py` | software | the kit folder is the repo root beside `build.bat` | |
| `test_util.py` | software | size formatting; replacing a file keeps the old one as `.bak` | opening paths, process lookup |
| `test_config.py` | software | config merge over the defaults; the player's settings; install state none/installed/update | |
| `test_skyrim.py` | software | plugins.txt reading; the sync code; game, SKSE, CC and ENB detection; Steam libraries and the game found through Steam's registry key (fake registry) | |
| `test_vortex.py` | software | readable mod names; finding Vortex.exe through uninstall entries (name filter, per-user first, 32-bit view, stale entries, quoted and unquoted icons); registry path parsing | the nxm:// handler (needs a real drive path: `test_windows.py`) |
| `test_winapi.py` | software | `FakeWinapi` matches every real function's parameters; running commands, missing registry keys, process lookup on any OS; registry, version resource, Documents and hung-window reads on Windows | anything that writes |
| `test_windows.py` | software (Windows CI only) | game and Vortex detection against the real registry: Steam path and libraries, nxm:// handler and its precedence, uninstall entries | runs only with `GITHUB_ACTIONS=true` on Windows; writes and removes HKCU keys |
| `test_snapshot.py` | software | config migration; what snapshot writes to `_packinfo/`; every requirement the app reads is one snapshot writes | asking for the game folder when it isn't found |
| `test_doctor_report.py` | software | the whole Doctor report for a setup with a problem in every check group, word for word against golden text | |
| `test_doctor.py` | software | plugin header parsing incl. `XXXX` fields; effective load order; each check group's FAIL/WARN on a known-bad setup; the report format | Address Library check (needs a real game version) |
| `test_crashsquatch.py` | software | crash log exception line; suspect ranking and noise filtering; mapping files to Vortex mods; summaries; history cap; Windows crash events from `wevtutil`; the watcher on a fake process (SKSE launch, normal exit, crash with a log); the `crash_history.json` format: exact keys, every earlier shape loads and round-trips, old entries untouched by a save; freeze detection and the loop's timing on a fake clock (20 s threshold, one report per freeze, reset on recovery, 90 s start deadline, stopping) | the real `IsHungAppWindow` (Windows-only; `test_winapi.py` checks it returns False for a live process) |
| `test_pack_mods.py` | software | mod fingerprints; full pack layout and manifest; the cumulative update diff | interactive prompts (folder pick, low disk) |
| `test_installer.py` | software | packer → installer round trip; the install plan per mode; a whole fresh install; resuming a stopped install without downloading again; the download and its browser fallback; failed checks; the Vortex hand-off; load order and INIs (with `.bak`); the final check; updates (new, changed, removed mods) | the real Google Drive (`FakeGdown` serves local files) |
| `test_host.py` | software | server port from STServer.ini; the CGNAT range; server start (own console) and stop; firewall rule check and elevated add | IP lookups (network) |
| `test_manage.py` | software | save backup/restore never loses current saves; settings restore; free space keeps the install marker | |
| `test_repo.py` | software | `.bat` files CRLF and run the right modules; `build.bat` names only existing files; pins; Makefile targets; modules import only from lower layers; only `winapi` talks to the OS; pytest runs with encoding warnings; mypy runs in `make lint` and CI | an actual PyInstaller build |
| `test_docs.py` | software | module docstrings have Purpose/Main package/Flow; test files name target and mode; the docs index is complete | prose quality |
| `test_gui.py` | software (needs Tk and a display) | the real GUI starts, waits out the splash, and opens every tab with no exception; each page builds; Doctor cards, a crash's details, live status and Home's last-crash notice render | clicking anything; skipped without Tk or a display (WSL: `sudo apt install python3-tk xvfb`) |
| `test_live.py` | live | detection on a real PC (game, version resource, Vortex, Documents); every real plugin header parses; the Doctor runs every group | anything that writes |

Shared code: `conftest.py` (modes, the sandbox, `artifacts`), `builders.py`
(plugin headers, plugins.txt, game and mod folders), `fake_winapi.py` (the OS:
a dict registry, processes, recorded launches), `fixtures/` (a synthetic Crash
Logger log and `wevtutil` output).
