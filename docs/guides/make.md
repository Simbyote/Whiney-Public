# The Makefile: every development command in one place

> `make` lists every command, grouped by what it's for. Each one is a short
> name for the full `python -m ...` command, so nobody has to remember flags.

**File:** `Makefile` · **Tests:** `test_repo.py` (every target expands, every target is `.PHONY`)

---

## Where it runs

In **WSL**, from the repo root. The Makefile is for development; the maintainer's
commands stay `.bat` files on Windows (`build.md`), where make is never needed.

```
make                        the list
make venv                   once: .venv with the app (editable), pytest and ruff
make check                  lint (ruff + mypy) + software tests: run before every commit
make test ARGS="-k doctor"  narrower runs; ARGS goes straight to pytest
make test-live              the live tests, on Windows Python
make run                    the GUI from source (WSLg shows the window)
```

`make run` needs Tk in WSL's Python (`sudo apt install python3-tk`) and
WSLg for the window; the Windows-only parts (registry, Steam, Vortex) find
nothing there.

Commands use `.venv/bin/python` when it exists, else `python3`, so the venv
needn't be activated. Every command is printed before it runs.

## Live tests from WSL

The live tests need the Windows registry, Steam and Vortex, so `make test-live`
runs them on **Windows Python**, which WSL can start directly (`py.exe`). It
reads the repo through `\\wsl.localhost\...`, so no copy is needed.

One-time setup, from WSL:

```
make live-deps              pip install --user the app's packages and pytest into Windows Python
```

If the Windows launcher isn't `py.exe`, say which: `make test-live WINPY=python.exe`.

## Options

| Option | Effect |
| --- | --- |
| `ARGS="..."` | passed straight to the command: `make test ARGS="-x --lf"` |
| `WINPY=...` | the Windows Python for `test-live` / `live-deps` (default `py.exe`) |
| `VENV_DIR=...` | the venv `venv` creates and the commands use (default `.venv`) |

## Adding a target

1. Put it under the right `##@` group with a `## comment`; the comment is its line in `make help`.
2. Add it to `.PHONY`; `test_repo.py` fails until it is listed.
3. If it has a guide, name the guide in the comment, as the others do.
