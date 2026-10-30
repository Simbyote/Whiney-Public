# Requirements

> What Whiney must do, how each requirement is checked, and what's proven so
> far. "Software" means a passing test on fixtures (`make test`); "live" means
> checked on a real install (`make test-live`) or by hand on a player's PC.
> Update the status when a check is added or a run proves it.

---

## Install

| ID | Requirement | Checked by | Status |
| --- | --- | --- | --- |
| I1 | A player ends up with the pack's exact enabled plugins, in the pack's order | `installer.order` and `verify` (`test_installer.py`: a whole install); Doctor's Sync check (`test_doctor.py`) | Software. Live: by hand only |
| I2 | Every mod in the pack reaches Vortex as one installable archive | `test_installer.py` round trip | Software |
| I3 | An update carries everything changed since the last full pack, so skipping an update is safe | `test_pack_mods.py` update diff | Software |
| I4 | A stopped install can be restarted and skips finished work | `BASE_READY` marker, download reuse (`test_installer.py`) | Software |
| I5 | The player's own plugins.txt and INIs can be restored | `.bak` files; `test_manage.py` | Software |
| I6 | A player who installed with the old console installer is recognized as installed | `install_state` marker compare (`test_config.py`) | Partly: the compare is tested; an old marker file is not in fixtures |
| I7 | Unpacking a pack archive or a save backup never writes outside its target folder, on any supported Python | `util.safe_member_path`; `test_installer.py` (escaping paths, absolute paths, links; with and without tarfile's `data` filter), `test_manage.py`, `test_util.py` | Software |
| I8 | A download that differs from the archive the maintainer packed (cut off, damaged, the wrong file) is never installed, and the next run downloads it again | `installer.check_download` against `base_sha256` / `update_sha256`; `test_installer.py` (automatic and browser downloads, a reused update), `test_pack_mods.py`, `test_snapshot.py` | Software. Not checked when the pack was recorded with `record_baseline.bat` |
| I9 | Every file the pack's mods deploy reaches the player's game folder, and a player whose game already matches the pack isn't sent through an install | `snapshot.deployed_inventory`, `doctor.check_deployment` / `setup_check`, `installer.verify` (`test_snapshot.py`, `test_doctor.py`, `test_installer.py`, `test_gui.py` setup card) | Software. Live: the first build recorded the inventory from the maintainer's deployment (2026-10-30); the check on players' PCs is pending their first installs with this build |
| I10 | An install can be cancelled at any point; nothing finished is lost, no partial download is left, and Start resumes | `installer.Cancelled` checks; `test_installer.py` (before the first step, mid-download, at the Vortex hand-off, while unpacking), `test_gui.py` (a cancelled wait for the player) | Software |
| I11 | Restoring saves never loses one: Merge keeps saves made since, and Replace deletes only what the safety backup provably holds | `manage.restore_saves`, `_clear_saves` (`test_manage.py`: replace, merge, a failed or incomplete safety backup, an empty folder) | Software |

## Diagnose

| ID | Requirement | Checked by | Status |
| --- | --- | --- | --- |
| D1 | Every known startup-crash cause is reported as FAIL with a fix: missing master, master after dependent, over 254 full plugins, wrong game version, missing SKSE, missing CC content | `test_doctor.py` | Software. Live: `make test-live` passed on the maintainer's install (2026-10-30): every check group runs on the real setup without crashing. The FAIL cases themselves are proven on fixtures only |
| D2 | A plugin header the game can read, the Doctor can read (including `XXXX` fields) | `test_doctor.py`; `test_live.py` parses every header in the real load order | Software. Live: passed on the maintainer's load order (`make test-live`, 2026-10-30) |
| D3 | After a crash with a log, the most likely mod is named | `test_crashsquatch.py` on a synthetic log | Software. Real Crash Logger logs: not yet in fixtures |
| D4 | A freeze is reported after 20 s "Not Responding" | `CrashSquatcher` on a fake clock (`test_crashsquatch.py`): 20 s threshold, once per freeze, reset on recovery | Software |
| D5 | A crash is only ever explained by this session's evidence: crash logs and Windows events from before the game started are ignored, in any time zone | `new_crash_logs`, `parse_crash_events` (`test_crashsquatch.py`: logs before and during the session, UTC event dates under UTC-5 and UTC+9, a start time Windows won't give) | Software |
| D6 | A suspect file shipped by several mods is attributed to the mod whose copy the game loaded, and never to just one of them by chance | `crashsquatch.file_owner` (`test_crashsquatch.py`: hard-linked and copied deployments, no game, nothing deployed, identical copies, two versions of one mod, through the watcher and Windows' faulting module) | Software |
| D7 | With several crash loggers installed, every log of the crash is used, and each logger's stack format is read (Crash Logger, Trainwreck, .NET Script Framework's parenthesized frames) | `analyze_logs`, `analyze_log` (`test_crashsquatch.py`: a .NET Script Framework-style log, two logs merged, the main log, the history shape, the watcher end to end; `test_gui.py` log buttons) | Software. Real .NET Script Framework and Trainwreck logs: not yet in fixtures |

## Host

| ID | Requirement | Checked by | Status |
| --- | --- | --- | --- |
| H1 | The host sees the port to forward and whether forwarding can work (CGNAT) | `test_host.py` | Software |
| H2 | Play Skyrim Together starts the multiplayer client, and Crash Squatch follows the game it starts | `host.find_client`, `CrashSquatcher(launcher=...)` (`test_host.py`, `test_crashsquatch.py`, `test_gui.py` button states) | Software. Live: pending a first multiplayer session (the game process under the client is expected to be `SkyrimSE.exe`) |

## Build

| ID | Requirement | Checked by | Status |
| --- | --- | --- | --- |
| B1 | `build.bat` names only files that exist, and bundles assets where the app looks | `test_repo.py` | Software |
| B2 | A build is reproducible: same commit, same dependency versions | pinned `requirements*.txt`; `test_repo.py` | Software |
| B3 | The batch files run under cmd.exe | CRLF check in `test_repo.py` | Software. Live: `build.bat` built the exe on the maintainer's PC (2026-10-30); that build is the one published |
| B4 | Every requirement a player's app checks is one the maintainer's build records | `test_snapshot.py`: keys read ⊆ keys written | Software |
