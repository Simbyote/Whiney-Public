"""
test_live.py  --  the app's detection and the Doctor, against the real Windows install

Software tests prove the logic on hand-built files; these check that the same
code finds and reads a real setup: Steam's library list, SkyrimSE.exe's
version resource, Vortex in the registry, a real plugins.txt. Each writes what
it found to artifacts/<timestamp>/<test>/ so a run can be compared with the
last one. Nothing here writes outside artifacts/.

--live  Windows Python with Skyrim SE installed (make test-live from WSL).
"""
import json

import pytest

from whiney import doctor, paths, skyrim, vortex, winapi

pytestmark = [pytest.mark.live, pytest.mark.usefixtures("windows")]


@pytest.fixture
def game():
    found = skyrim.find_game_dir()
    if found is None:
        pytest.skip("Skyrim SE not found on this PC")
    return found


def test_detection_finds_the_game_and_reads_its_version(game, artifacts):
    version = winapi.file_version(game / "SkyrimSE.exe")
    found = {
        "game": str(game),
        "game_version": version,
        "skse_dlls": skyrim.skse_dlls(game),
        "cc_plugins": len(skyrim.cc_plugins(game)),
        "uses_enb": skyrim.uses_enb(game),
        "vortex": str(vortex.find_vortex()),
        "staging": str(vortex.staging_dir()),
        "documents": str(skyrim.documents_dir()),
        "sync_code": skyrim.sync_code(),
    }
    (artifacts / "detection.json").write_text(json.dumps(found, indent=2), encoding="utf-8")
    # Four dotted numbers, e.g. 1.6.1170.0: anything else means the resource read broke
    assert version and len(version.split(".")) == 4


def test_plugin_headers_of_the_real_load_order_all_parse(game, artifacts):
    plugins_txt = paths.SKYRIM_APPDATA / "plugins.txt"
    if not plugins_txt.exists():
        pytest.skip("no plugins.txt yet: launch the game once")
    order, headers, idx = doctor.active_load_order(game, plugins_txt)
    unreadable = [n for n in order if n.lower() in idx and headers.get(n.lower()) is None]
    (artifacts / "load_order.txt").write_text("\n".join(order), encoding="utf-8")
    assert unreadable == []


def test_doctor_runs_every_check_group_without_crashing(game, artifacts):
    results = doctor.run_all(game=game)
    (artifacts / "doctor_report.txt").write_text(doctor.report_text(results), encoding="utf-8")
    crashed = [r.title for r in results if r.title.startswith("Couldn't run the")]
    assert crashed == []
