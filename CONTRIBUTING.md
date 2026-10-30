# Contributing to Whiney

Thanks for helping. Bug reports, crash logs, fixes, features and docs are all
welcome. This page says how to get set up, what a change needs before it
can be merged, and where the rules come from.

## Reporting a bug

Open an issue with the **Bug report** form. The most useful attachments:

- **Doctor > Copy report**, pasted into the issue.
- For a crash: the crash log Crash Squatch read (**Open crash log**), and
  which crash logger you use (Crash Logger SSE, Trainwreck, .NET Script
  Framework). Real logs become test fixtures.
- `Downloads\Whiney\app_log.txt` and `install_log.txt`, if the app or an
  install failed.

Security problems go through [`SECURITY.md`](SECURITY.md), not a public issue.

## Setting up

Development runs in WSL or Linux through `make`. The app itself only runs
fully on Windows.

```
git clone https://github.com/<you>/Whiney.git
cd Whiney
make venv       # .venv with the app, pytest, ruff and mypy
make check      # lint, type check, software tests
make            # lists every command
```

The GUI test needs Tk and a display: `sudo apt install python3-tk xvfb`.
Without them it is skipped locally (CI always runs it). The live tests
(`make test-live`) need Windows Python and a real Skyrim install; see
[`docs/guides/pytest.md`](docs/guides/pytest.md).

## Making a change

1. Fork, then branch from `main` (`fix/…`, `feature/…`, `docs/…`).
2. Make the change with its tests and docs (below).
3. Run `make check` until it passes.
4. Open a pull request. The template asks what changed, why, and how it was
   tested. CI runs lint, mypy and the full test suite on Ubuntu and Windows,
   and must pass before merging.

Keep pull requests to one concern; a refactor and a feature are two PRs.

## What a change needs

- **Tests.** Every behaviour change comes with a software test that fails
  without it. Software tests run in a sandbox: every real path is redirected
  to a temp folder, Windows is `FakeWinapi`, Google Drive is `FakeGdown`, and
  the network is blocked ([`docs/guides/tests.md`](docs/guides/tests.md)).
  Changing existing behaviour? Pin it with a test first, then change it.
- **Types.** Every function is annotated, and mypy fails the build
  otherwise. Pages use the window only through `ui.widgets.AppShell`; a new
  `App` method that pages call goes in `AppShell` too (`test_repo.py` checks
  that the two match).
- **Docs.** [`docs/_DOCUMENTATION.md`](docs/_DOCUMENTATION.md) is the standard.
  Module docstrings open with Purpose, Main package and Flow (a test checks).
  A change a player can see updates [`docs/guides/ui.md`](docs/guides/ui.md),
  and the players' guide `release/README.txt` if it changes what they do.
  A new requirement, or new evidence for one, goes in
  [`docs/requirements.md`](docs/requirements.md).
- **The architecture rules** in [`docs/architecture.md`](docs/architecture.md),
  each enforced by `tests/test_repo.py`:
  - Modules import only from lower layers.
  - Only `winapi` talks to Windows (registry, Win32, processes, the shell).
  - Only `paths` builds real-world locations.
  - Only `ui/` imports tkinter.
  - Import modules, not names (`from whiney import paths`, then `paths.WORK_DIR`).
- **Explicit encodings.** Every text file read or write names its encoding;
  the tests fail on any that doesn't.
- **Compatibility.** `crash_history.json` and `requirements.json` are file
  formats that players' existing files and older exes depend on. Change them
  only additively; the round-trip and contract tests say when you haven't.

## Commit messages

A short imperative subject ("Check every archive entry before unpacking"),
then a body that says what was wrong or missing and why the change is right.
Mention what the tests cover.

## Code of conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
