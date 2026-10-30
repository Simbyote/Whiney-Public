"""
test_doctor.py  --  src/whiney/doctor.py

The Doctor is what players run when the game won't start, so a check that
passes a broken setup is the costly failure. These pin the plugin header
reader against hand-built TES4 records, the effective load order the game
uses, and that each check group turns a known-bad setup into its FAIL/WARN,
including the deployment check against the pack's recorded files.

--software  Fake game folders and plugin files in the sandbox. No Skyrim.
"""
import pytest

from builders import make_game, make_mod, plugin_bytes, write_plugin, write_plugins_txt
from whiney import doctor, paths, util

pytestmark = pytest.mark.software


def _levels(findings, area=None):
    return [(f.level, f.title) for f in findings if area is None or f.area == area]


# ---- the plugin header reader -----------------------------------------------------------
def test_header_reads_masters_in_order_and_the_esm_esl_flags(tmp_path):
    p = tmp_path / "Patch.esp"
    p.write_bytes(plugin_bytes(["Skyrim.esm", "Mod Ä.esp"], esm=True, esl=True))
    assert doctor.read_plugin_header(p) == {"masters": ["Skyrim.esm", "Mod Ä.esp"], "esm": True, "esl": True}


def test_header_follows_xxxx_fields_over_64kb(tmp_path):
    # A field after XXXX takes its size from the XXXX payload; misreading it
    # skips straight past the masters and every master check passes silently
    p = tmp_path / "Big.esp"
    p.write_bytes(plugin_bytes(["Skyrim.esm"], big_field=True))
    assert doctor.read_plugin_header(p)["masters"] == ["Skyrim.esm"]


@pytest.mark.parametrize("content", [b"", b"TES3" + b"\0" * 40, b"TES4\0\0"])
def test_header_of_a_non_tes4_or_truncated_file_is_none(tmp_path, content):
    p = tmp_path / "bad.esp"
    p.write_bytes(content)
    assert doctor.read_plugin_header(p) is None


def test_header_of_a_missing_file_is_none(tmp_path):
    assert doctor.read_plugin_header(tmp_path / "missing.esp") is None


# ---- effective load order ------------------------------------------------------------
def test_official_masters_load_first_even_when_not_listed(sandbox):
    game = make_game(sandbox.root / "game")
    write_plugin(game / "Data", "A.esp", ["Skyrim.esm"])
    txt = write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["A.esp"])
    order, _, _ = doctor.active_load_order(game, txt)
    assert order == ["Skyrim.esm", "Update.esm", "A.esp"]


def test_masters_load_before_plugins_keeping_their_relative_order(sandbox):
    # The game hoists every master (by extension or ESM flag) above regular plugins
    game = make_game(sandbox.root / "game", official=("Skyrim.esm",))
    write_plugin(game / "Data", "A.esp")
    write_plugin(game / "Data", "FlaggedMaster.esp", esm=True)
    write_plugin(game / "Data", "B.esm", esm=True)
    write_plugin(game / "Data", "Light.esl")
    txt = write_plugins_txt(sandbox.appdata / "plugins.txt",
                            enabled=["A.esp", "FlaggedMaster.esp", "B.esm", "Light.esl"])
    order, _, _ = doctor.active_load_order(game, txt)
    assert order == ["Skyrim.esm", "FlaggedMaster.esp", "B.esm", "Light.esl", "A.esp"]


# ---- check_plugins ---------------------------------------------------------------------
@pytest.fixture
def game(sandbox):
    return make_game(sandbox.root / "game")


def test_clean_load_order_is_ok(sandbox, game):
    write_plugin(game / "Data", "A.esp", ["Skyrim.esm"])
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["A.esp"])
    assert _levels(doctor.check_plugins(game, {})) == [("OK", "3 plugins load cleanly")]


def test_enabled_plugin_missing_from_data_fails(sandbox, game):
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Gone.esp"])
    assert ("FAIL", "1 enabled plugin(s) are missing from Data") in _levels(doctor.check_plugins(game, {}))


def test_plugin_whose_master_is_not_active_fails(sandbox, game):
    write_plugin(game / "Data", "Patch.esp", ["Skyrim.esm", "Base.esp"])
    write_plugin(game / "Data", "Base.esp")
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Patch.esp"], disabled=["Base.esp"])
    found = doctor.check_plugins(game, {})
    fail = next(f for f in found if "missing a master" in f.title)
    assert fail.level == "FAIL" and fail.detail == "Patch.esp needs: Base.esp"


def test_plugin_loading_before_its_master_fails(sandbox, game):
    write_plugin(game / "Data", "Patch.esp", ["Base.esp"])
    write_plugin(game / "Data", "Base.esp")
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Patch.esp", "Base.esp"])
    found = doctor.check_plugins(game, {})
    assert ("FAIL", "Load order has plugins before their masters") in _levels(found)


def test_more_full_plugins_than_the_limit_fails(sandbox, game):
    # ESL-flagged and .esl files don't count: they share one slot
    names = [f"P{i:03}.esp" for i in range(doctor.FULL_PLUGIN_LIMIT)]
    for n in names:
        write_plugin(game / "Data", n)
    write_plugin(game / "Data", "Light.esp", esl=True)
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=names + ["Light.esp"])
    titles = [t for _, t in _levels(doctor.check_plugins(game, {}))]
    # 2 official masters + 254 = 256 full plugins
    assert f"256 full plugins enabled (limit is {doctor.FULL_PLUGIN_LIMIT})" in titles


def test_no_plugins_txt_yet_is_a_warning_not_a_failure(sandbox, game):
    assert _levels(doctor.check_plugins(game, {})) == [("WARN", "No load order file yet")]


def test_load_order_differing_from_the_pack_warns_with_both_sides(sandbox, game):
    for n in ("A.esp", "B.esp", "Mine.esp"):
        write_plugin(game / "Data", n)
    write_plugins_txt(sandbox.packinfo / "plugins.txt", enabled=["A.esp", "B.esp"])
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["A.esp", "Mine.esp"])
    sync = next(f for f in doctor.check_plugins(game, {}) if f.area == "Sync")
    assert sync.level == "WARN"
    assert sync.detail == "Not enabled for you: b.esp\nExtra on your side: mine.esp"


def test_load_order_matching_the_pack_is_ok(sandbox, game):
    write_plugin(game / "Data", "A.esp")
    write_plugins_txt(sandbox.packinfo / "plugins.txt", enabled=["A.esp"])
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["A.esp"])
    sync = next(f for f in doctor.check_plugins(game, {}) if f.area == "Sync")
    assert sync.level == "OK"


# ---- check_deployment ----------------------------------------------------------------------
INVENTORY = {"Alpha-11111-1-0-1700000000": ["Data/Alpha.esp", "Data/textures/a.dds"],
             "SKSE-30379-2-2-6-1700000000": ["skse64_loader.exe"]}


def _deploy(game, *rels):
    for rel in rels:
        p = game / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_every_recorded_file_in_place_is_ok_whatever_its_case(sandbox, game):
    _deploy(game, "Data/ALPHA.ESP", "Data/Textures/A.dds", "skse64_loader.exe")
    assert _levels(doctor.check_deployment(game, INVENTORY)) == [("OK", "All 2 pack mods are deployed")]


def test_a_mod_with_none_of_its_files_fails_and_one_missing_some_warns(sandbox, game):
    _deploy(game, "Data/Alpha.esp")
    found = doctor.check_deployment(game, INVENTORY)
    assert _levels(found) == [("FAIL", "1 pack mod(s) aren't deployed in the game"),
                              ("WARN", "1 pack mod(s) are missing files")]
    assert found[0].detail == "SKSE"
    assert found[1].detail == "Alpha: 1 of 2 files missing (e.g. Data/textures/a.dds)"


TOGETHER = {"Skyrim Together Reborn-69993-1-6-1700000000": ["Data/SkyrimTogetherReborn/SkyrimTogether.exe",
                                                            "Data/SkyrimTogetherReborn/SkyrimTogetherServer.exe"]}


def test_a_mod_deployed_to_the_game_folder_instead_of_data_says_where_its_files_are(sandbox, game):
    # The player's Vortex gave Skyrim Together a game-folder Mod Type; the maintainer's put it in Data
    _deploy(game, "SkyrimTogetherReborn/SkyrimTogether.exe", "SkyrimTogetherReborn/SkyrimTogetherServer.exe")
    found = doctor.check_deployment(game, TOGETHER)
    assert _levels(found) == [("FAIL", "1 pack mod(s) aren't deployed in the game")]
    assert found[0].detail == "Skyrim Together Reborn: 2 found in the game folder instead of Data"
    assert "Mod Type" in found[0].fix and "Reinstalling the mod doesn't change it" in found[0].fix


@pytest.mark.parametrize("deployed, where", [
    pytest.param("Data/skse64_loader.exe", "SKSE: 1 found in Data instead of the game folder", id="into-data"),
    pytest.param("Data/Data/skse64_loader.exe", "SKSE: 1 found in Data\\Data instead of the game folder",
                 id="data-twice"),
])
def test_a_mod_deployed_into_the_wrong_folder_is_found_there(sandbox, game, deployed, where):
    _deploy(game, "Data/Alpha.esp", "Data/textures/a.dds", deployed)
    found = doctor.check_deployment(game, INVENTORY)
    assert found[0].detail == where


def test_a_partly_missing_mod_says_where_the_rest_went(sandbox, game):
    _deploy(game, "Data/Alpha.esp", "textures/a.dds", "skse64_loader.exe")
    found = doctor.check_deployment(game, INVENTORY)
    assert found[0].detail == ("Alpha: 1 of 2 files missing (e.g. Data/textures/a.dds); "
                               "1 found in the game folder instead of Data")
    assert "Mod Type" in found[0].fix


def test_a_missing_file_matches_the_copy_whose_path_ends_like_it(sandbox, game):
    # Another mod's readme.txt sits in Data; the moved one ends in SkyrimTogetherReborn/readme.txt
    by_name = {"readme.txt": ["Data/Other/readme.txt", "SkyrimTogetherReborn/readme.txt"]}
    assert doctor.misplaced(["Data/SkyrimTogetherReborn/readme.txt"], by_name) == ("Data", "", 1)
    assert doctor.misplaced(["Data/SkyrimTogetherReborn/gone.dll"], by_name) is None


def test_files_nowhere_in_the_game_get_no_mod_type_advice(sandbox, game):
    found = doctor.check_deployment(game, TOGETHER)
    assert found[0].detail == "Skyrim Together Reborn" and "Mod Type" not in found[0].fix


def test_a_build_without_an_inventory_reports_nothing(sandbox, game):
    assert doctor.check_deployment(game, {}) == []


def test_run_all_includes_the_deployment_check(sandbox, game):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, INVENTORY)
    assert any(f.area == "Deployment" for f in doctor.run_all(game, {}))


# ---- the setup check on Home ---------------------------------------------------------------
def _pack_setup(sandbox, game):
    """A game that matches the pack: its load order, and every recorded file deployed."""
    write_plugin(game / "Data", "Alpha.esp")
    write_plugins_txt(sandbox.packinfo / "plugins.txt", enabled=["Alpha.esp"])
    write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Alpha.esp"])
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {"Alpha-11111-1-0-1700000000": ["Data/Alpha.esp"]})


def test_a_game_set_up_like_the_pack_matches_it(sandbox, game):
    _pack_setup(sandbox, game)
    assert doctor.matches_pack(doctor.setup_check(game, {}))


@pytest.mark.parametrize("change", ["load order", "undeployed file", "no pack load order"])
def test_any_difference_from_the_pack_is_not_a_match(sandbox, game, change):
    _pack_setup(sandbox, game)
    if change == "load order":
        write_plugin(game / "Data", "Mine.esp")
        write_plugins_txt(sandbox.appdata / "plugins.txt", enabled=["Alpha.esp", "Mine.esp"])
    elif change == "undeployed file":
        util.write_json(sandbox.packinfo / paths.INVENTORY_FILE,
                        {"Alpha-11111-1-0-1700000000": ["Data/Alpha.esp", "Data/meshes/a.nif"]})
    else:                                           # nothing to compare against
        (sandbox.packinfo / "plugins.txt").unlink()
    assert not doctor.matches_pack(doctor.setup_check(game, {}))


# ---- preflight, SKSE, mods ----------------------------------------------------------------
def test_preflight_without_a_game_fails_and_stops(sandbox):
    found = doctor.preflight({}, None)
    assert _levels(found, "Game") == [("FAIL", "Couldn't find Skyrim Special Edition")]


def test_preflight_fails_when_the_packs_skse_runtime_is_missing(sandbox, game):
    found = doctor.preflight({"skse_dlls": ["skse64_1_6_1170.dll"]}, game)
    assert ("FAIL", "SKSE for game version 1.6.1170 is missing") in _levels(found, "SKSE")
    (game / "skse64_loader.exe").write_bytes(b"")
    (game / "skse64_1_6_1170.dll").write_bytes(b"")
    assert _levels(doctor.preflight({"skse_dlls": ["skse64_1_6_1170.dll"]}, game), "SKSE") == \
        [("OK", "SKSE installed")]


def test_preflight_fails_when_the_game_version_differs_from_the_pack(sandbox, game):
    # SKSE and its plugins work on exactly one game version
    sandbox.winapi.versions[str(game / "SkyrimSE.exe")] = "1.6.640.0"
    found = doctor.preflight({"game_version": "1.6.1170.0"}, game)
    assert ("FAIL", "Game version 1.6.640.0 doesn't match the pack (1.6.1170.0)") in _levels(found, "Game")
    found = doctor.preflight({"game_version": "1.6.640.0"}, game)
    assert ("OK", "Game version 1.6.640.0 matches") in _levels(found, "Game")


@pytest.mark.parametrize("missing, title", [
    (1, "Missing Creation Club files"),
    (5, "Missing 5 Creation Club files"),       # over 4 means no Anniversary Edition at all
])
def test_preflight_fails_on_missing_creation_club_content(sandbox, game, missing, title):
    req = {"cc_plugins": [f"cc{i}.esl" for i in range(missing)]}
    assert ("FAIL", title) in _levels(doctor.preflight(req, game), "Game")


def test_skse_plugins_without_skse_fail(sandbox, game):
    plugins = game / "Data" / "SKSE" / "Plugins"
    plugins.mkdir(parents=True)
    (plugins / "Something.dll").write_bytes(b"")
    found = doctor.check_skse_plugins(game, {})
    assert ("FAIL", "1 SKSE plugins installed but SKSE itself isn't") in _levels(found)
    assert ("WARN", "No crash logger installed") in _levels(found)


def test_pack_mods_missing_from_vortex_are_listed_by_short_name(sandbox):
    make_mod(sandbox.staging, "SkyUI-12604-5-2SE-1700000000", {"SkyUI_SE.esp": b""})
    req = {"mods": ["SkyUI-12604-5-2SE-1700000000", "Missing Mod-99999-1-0-1700000000"]}
    [found] = doctor.check_mods(req)
    assert (found.level, found.detail) == ("WARN", "Missing Mod")


def test_mods_present_under_a_different_install_timestamp_still_count(sandbox):
    # Vortex renames a mod folder when it's reinstalled; the short name still matches
    make_mod(sandbox.staging, "SkyUI-12604-5-2SE-1800000000", {"SkyUI_SE.esp": b""})
    [found] = doctor.check_mods({"mods": ["SkyUI-12604-5-2SE-1700000000"]})
    assert found.level == "OK"


# ---- run_all and the report ----------------------------------------------------------------
def test_run_all_turns_a_crashing_check_into_a_warning(sandbox, game, monkeypatch):
    def boom(game, req):
        raise RuntimeError("bad header")
    monkeypatch.setattr(doctor, "check_plugins", boom)
    found = doctor.run_all(game=game, req={})
    assert ("WARN", "Couldn't run the plugins check") in _levels(found, "Plugins")


def test_report_lists_fixes_only_for_problems(sandbox):
    text = doctor.report_text([doctor.Finding("OK", "A", "fine", fix="never shown"),
                               doctor.Finding("FAIL", "B", "broken", "line1\nline2", "do this")])
    assert "never shown" not in text
    assert "[FAIL] B: broken\n    line1\n    line2\n    Fix: do this" in text


def test_a_finding_with_a_misspelt_level_fails_where_it_is_made():
    # As a dict, "FIAL" rendered with no color and was left out of the counts
    with pytest.raises(ValueError, match="FIAL"):
        doctor.Finding("FIAL", "Game", "typo")
