# Whiney Documentation

Whiney distributes a Skyrim SE mod pack and keeps players' installs identical
to it. The player side is `Whiney.exe`, a Windows GUI with six sections:
Home, Install & Update, Doctor, Crash Squatch, Host Server and Manage. It
installs the pack through Vortex, applies the pack's load order and settings,
checks the setup, records and explains crashes, and runs a Skyrim Together
server. The maintainer side, in the same repository, packs the maintainer's
Vortex mods into archives and builds the exe.

---

## Start here

| To… | Read |
| --- | --- |
| Know what each section of the exe does: controls, states, files | `guides/ui.md` |
| Understand the whole system: the two PCs, the modules, where files live | `architecture.md` |
| Look up a term (master, ESL, SKSE, Address Library, sync code, CGNAT…) | `concepts.md` |
| Know what the app must do, and what's proven so far | `requirements.md` |
| Write or review code and docs to the project's standard | `_DOCUMENTATION.md` |
| Run any dev command without remembering its flags: `make` lists them | `guides/make.md` |
| Run the tests | `guides/pytest.md` |
| Know what each test file covers | `guides/tests.md` |
| Build the exe, pack mods, publish an update (maintainer) | `guides/build.md` |
| Contribute: setup, what a change needs, pull requests | `../CONTRIBUTING.md` |
| Install and use the app (players' guide, shipped with the exe) | `../release/README.txt` |

---

## Layout

```
docs/
    guides/
        build.md            maintainer's steps: build.bat, pack_mods.bat, pack_update.bat, Drive
        make.md             the Makefile: every dev command by a short name
        pytest.md           running the tests: software and live modes, the sandbox
        tests.md            what each test file covers
        ui.md               each section of the exe: controls, states, files written
    images/                 screenshots used by the root README
    _DOCUMENTATION.md       the documentation standard
    architecture.md         two machines, modules, paths, known structural debt
    concepts.md             the terms the docs use, explained once
    README.md               this page
    requirements.md         requirements, how each is checked, status
```

---

## Conventions used everywhere

| | Convention |
| --- | --- |
| Commands | Development runs in WSL from the repo root through `make`; the maintainer's commands are the `.bat` files on Windows |
| Code | The package is `src/whiney/`; imports are absolute and by module (`from whiney import paths`, then `paths.WORK_DIR`); a module imports only from lower layers (`architecture.md`) |
| Windows | Every registry read, Win32 call, process and shell action goes through `winapi`; nothing else imports `winreg`, `ctypes`, `subprocess`, `psutil` or `webbrowser`. Network I/O is not in `winapi` (`host`, `installer`; `architecture.md`) |
| Paths | Every real-world location is a constant in `paths` (plus the folder lookups in `skyrim` and `vortex`); nothing else builds those paths (`architecture.md`, "Where files live") |
| Text files | Every `open`, `read_text`, `write_text` and text-mode `subprocess` call names its encoding: `"locale"` in the app (game files, Windows tool output, the app's own files, as before), `"utf-8"` in tests. `make test` fails on any that doesn't |
| Plugin names | Compared lowercased; shown as written |
| Findings | Doctor results are `OK` / `WARN` / `FAIL`; a FAIL means the game will crash or the install will fail |
| Types | Every function is annotated; mypy checks the package in `make lint` and CI, as on Windows (`platform = win32`), and rejects an unannotated function. Pages reach the window only through `ui.widgets.AppShell`; the installer reaches its UI only through `installer.InstallerUI` |
| Tests | One file per module, one mode marker per test, the name says the behavior (`guides/pytest.md`) |
| Before a commit | `make check` passes |

---

## Current status

The app is in use: players install from the shared Drive, and the full feature
set (install, Doctor, Crash Squatch, Host, Manage) works. The restructured
code has been built with `build.bat` and published, and `make test-live` passes
on the maintainer's install (2026-10-30). `requirements.md` has the
per-requirement status. The most important open items:

- Players' first installs with this build: the deployment check on their PCs (I9)
- A first multiplayer session through Play Skyrim Together (H2)
- Real Crash Logger, Trainwreck and .NET Script Framework logs as test fixtures (D3, D7)
- The structural debt in `architecture.md`: partial type hints, the app's own files in the locale encoding, small leftovers
