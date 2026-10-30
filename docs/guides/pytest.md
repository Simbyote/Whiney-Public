# Running the tests (pytest)

Every module in `src/whiney/` has a matching `tests/test_<module>.py`; a few
tests check the repo itself (`test_repo.py`, `test_docs.py`). What each file
covers is in `tests.md`. Each test runs in one of two modes:

- **software**: contract and known-answer tests on hand-built files. No Skyrim, any OS; pass/fail. The default.
- **live**: read-only checks against a real install on Windows Python. Writes what it found to `artifacts/` for review.

Tests outside the selected mode are deselected, not skipped, so the output
lists only what ran. A test with no mode marker, or both, is an error.

## 1. Setup (WSL)

```
make venv
```

That's it: the venv holds the app (installed editable from `src/`), pytest
and ruff. `pyproject.toml` points pytest at `tests/` and puts `src/` on the
import path, so no path arguments are needed.

## 2. Software tests (every change)

```
make check          lint, then the tests: the gate before a commit
make test           tests only
```

Expect every test to pass in about a second.

`make test` runs Python with `-X warn_default_encoding`, and `pyproject.toml`
turns the resulting `EncodingWarning` into an error: a file read or written
without an explicit `encoding=` fails the run. Windows defaults to cp1252, so
such a call passes on Linux and breaks on Windows (it did, in CI). Running
`pytest` directly skips the check; use `make test`.

Narrower runs:

```
make test ARGS="tests/test_doctor.py"       one module
make test ARGS='-k "sync and not pack"'     tests whose names match
make test ARGS="--lf"                       only what failed last time
make test ARGS="-x"                         stop at the first failure
```

### The GUI test

`test_gui.py` starts the real GUI in its own process and opens every tab. It
needs Tk and a display; in WSL, once:

```
sudo apt install python3-tk xvfb
```

Without them it is skipped with that reason; CI always runs it.

### The sandbox

Every software test runs inside the `sandbox` fixture (`tests/conftest.py`):
the work folder, AppData, Documents, Vortex staging and the kit folder all
point into a temp folder, `CONFIG` is a fixed test config, the OS is
`FakeWinapi`, Google Drive is `FakeGdown`, and network connections fail. A
software test can't read or change the real game, or reach the internet, even
by mistake. Use `sandbox.<folder>` to build the situation:

```python
def test_plugin_whose_master_is_not_active_fails(sandbox, game):
    write_plugin(game / "Data", "Patch.esp", ["Skyrim.esm", "Base.esp"])
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Patch.esp"], disabled=["Base.esp"])
    ...
```

The builders that write plugin headers, `plugins.txt`, game folders and mod
folders are in `tests/builders.py`; fixture files (crash logs, `wevtutil`
output) in `tests/fixtures/`.

The sandbox also replaces `winapi`, the app's only door to the OS, with a
`FakeWinapi` (`sandbox.winapi`). Set up the OS a test needs and check what the
app asked it to do:

```python
def test_the_server_starts_in_its_own_console_from_its_folder(sandbox, tmp_path):
    exe = tmp_path / "SkyrimTogetherReborn" / host.SERVER_EXE
    host.start_server(exe)
    assert sandbox.winapi.launched == [(str(exe), str(exe.parent), True)]
```

Google Drive is `sandbox.gdown`: put a local file behind a Drive file ID with
`sandbox.gdown.files[file_id] = path`, or set `sandbox.gdown.error`. Any other
network connection fails the test.

`set_reg(hive, key, name, value)` fills the registry; `running`, `outputs`
(command name to stdout) and `versions` hold the rest. A `winapi` function the
fake doesn't have fails the test rather than reaching the real OS, and
`test_winapi.py` fails until the fake has every function the real module does.

## 3. Live tests (on a Windows PC with Skyrim, now and then)

```
make live-deps      once
make test-live
```

They need Skyrim SE installed; without it they skip with the reason. Each test
writes to `artifacts/<timestamp>/<test name>/`: the detection results, the
real load order, a Doctor report. Compare a run with the previous one when
something changes (a game update, a new Vortex). Nothing is written outside
`artifacts/`.

From Windows directly (PowerShell in the repo): `py -m pytest --live`.

| Option | Effect |
| --- | --- |
| `--software --live` | both modes in one run |
| `--artifact-dir=DIR` | write live results somewhere other than `./artifacts` |

## 4. CI

`.github/workflows/ci.yml` runs lint and the software tests on Ubuntu and
Windows on every push. A red check means `make check` would have failed too;
run it locally to see why.

## Writing a test

1. Put it in `tests/test_<module>.py`, with `pytestmark = pytest.mark.software` (or `live`).
2. Name it for the behavior: `test_<situation>_<expected result>`.
3. Build the input with `builders.py` in the sandbox; never point a software test at a real path.
4. Comment where every expected number comes from (`_DOCUMENTATION.md`, Tests).
5. Add a line for a new file to `tests.md`.
