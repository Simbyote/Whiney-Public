"""
test_gui.py  --  src/whiney/ui/ (the whole GUI, started for real)

Nothing else starts the GUI, so a page that fails to build, a widget helper
that moved, or the theme being set up too late would only show on a player's
PC. This starts the real App in its own process on a fake game with Skyrim
Together deployed, waits out the splash, opens every tab and fails on any
exception. Home, AppData and Documents point at a
temp folder; the registry, on Windows, is only read.

--software  Needs Tk and a display: on Linux a virtual one (xvfb-run); in WSL,
            `sudo apt install python3-tk xvfb`. Skipped with the reason otherwise;
            on CI a missing Tk or display fails instead.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.software

SMOKE = Path(__file__).parent / "gui_smoke.py"
SRC = Path(__file__).resolve().parents[1] / "src"


# On CI a missing Tk or display is a broken runner, not a reason to skip: fail so it's seen
_unavailable = pytest.fail if os.environ.get("GITHUB_ACTIONS") == "true" else pytest.skip


def _command() -> list[str]:
    if importlib.util.find_spec("tkinter") is None:
        _unavailable("no Tk in this Python (WSL/Ubuntu: sudo apt install python3-tk)")
    cmd = [sys.executable, "-X", "warn_default_encoding", str(SMOKE)]
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        if shutil.which("xvfb-run") is None:
            _unavailable("no display and no xvfb-run (sudo apt install xvfb)")
        cmd = ["xvfb-run", "-a", *cmd]
    return cmd


@pytest.fixture(scope="module")
def gui(tmp_path_factory):
    """Run the smoke script once for this file; its JSON report."""
    home = tmp_path_factory.mktemp("home")
    # A game with Skyrim Together deployed, saved as the player's game folder
    game = home / "Games" / "Skyrim Special Edition"
    (game / "Data" / "SkyrimTogetherReborn").mkdir(parents=True)
    (game / "SkyrimSE.exe").write_bytes(b"MZ")
    (game / "Data" / "SkyrimTogetherReborn" / "SkyrimTogether.exe").write_bytes(b"MZ")
    settings = home / "Downloads" / "Whiney" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"game_dir": str(game)}), encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(SRC),
           "LOCALAPPDATA": str(home / "AppData" / "Local"), "APPDATA": str(home / "AppData" / "Roaming")}
    out = subprocess.run(_command(), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_gui_starts_and_every_tab_opens_without_an_exception(gui):
    assert gui["errors"] == []


def test_every_tab_builds_its_page(gui):
    assert sorted(gui["pages"]) == ["crash", "doctor", "home", "host", "install", "manage"]
    # Smallest page today has ~30 widgets; one with a handful means its build() bailed out early
    assert all(sum(counts.values()) > 10 for counts in gui["pages"].values()), gui["pages"]


def test_both_play_buttons_are_enabled_with_the_game_and_skyrim_together_deployed(gui):
    assert gui["play_buttons"] == {page: {"skse": "normal", "together": "normal"} for page in ("home", "crash")}


def test_home_shows_the_setup_check_in_each_state(gui):
    # The fake game has no plugins.txt yet, so the real startup check finds one difference
    assert gui["home"]["startup_setup"] == "1 difference(s) from the pack"
    assert gui["home"]["setup"] == {"no game": "Not checked", "matches": "Matches the pack ✓",
                                    "differs": "2 difference(s) from the pack", "nothing to compare": "Not checked"}
    assert gui["home"]["already_set_up_notice"] == "Use my current setup"


def test_home_opens_the_installation_guide(gui):
    # From source the guide is release/README.txt; the exe bundles the same file (build.bat)
    assert gui["home"]["guide_lines"] > 100


def test_cancelling_releases_an_install_waiting_for_the_player(gui):
    assert gui["install"] == {"wait": "cancelled", "action_card_shown": False}


def test_a_crash_with_two_loggers_logs_offers_both(gui):
    assert gui["crash"]["buttons"][:2] == ["Open crash log", "Log 2"]
