"""Whiney: installs, checks and runs a shared Skyrim SE mod pack through Vortex.

Purpose:
    Package root. The modules split by job: paths, util, config, skyrim and
    vortex (shared by everything), installer, doctor, crashsquatch, host,
    manage, snapshot and pack_mods (the maintainer's side), and app (the
    GUI). docs/architecture.md maps how they depend on each other.

Main package:
    __version__: the app version shown in builds and reports.

Flow:
    python -m whiney runs __main__, which starts the GUI or, with --snapshot,
    records the maintainer's setup.
"""

__version__ = "0.1.0"
