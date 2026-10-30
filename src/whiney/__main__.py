"""Entry point for `python -m whiney` and for the PyInstaller exe.

Purpose:
    Starts the GUI, or with --snapshot records the maintainer's Skyrim setup
    for build.bat. The snapshot path never imports tkinter, so it runs on a
    console-only Python.

Main package:
    None; it only dispatches to snapshot.snapshot() or ui.app.main().

Flow:
    1. Give print() and tracebacks a log file when the windowed exe has no console.
    2. --snapshot: record the setup into _packinfo/ and exit.
    3. Otherwise start the GUI.
"""
import os
import sys
from pathlib import Path

# A windowed exe has no console: give print()/tracebacks somewhere to go.
# The folder matches paths.LOG_FILE; it is spelled out because nothing is imported yet
if sys.stdout is None or sys.stderr is None:
    try:
        _logdir = Path.home() / "Downloads" / "Whiney"
        _logdir.mkdir(parents=True, exist_ok=True)
        _log = open(_logdir / "app_log.txt", "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        _log = open(os.devnull, "w", encoding="locale")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

from whiney import snapshot  # noqa: E402  (after the log redirect, so import errors are logged)


def main() -> None:
    if "--snapshot" in sys.argv:
        snapshot.snapshot()
        return
    from whiney.ui import app
    app.main()


if __name__ == "__main__":
    main()
