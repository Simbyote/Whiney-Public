"""
test_config.py  --  src/whiney/config.py

config answers "which pack is this and is it installed?". A wrong answer
sends players through a full reinstall, or hides an update from them. These
pin the config merge, the player's settings and the install-state compare.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
import json

import pytest

from whiney import config, paths, util

pytestmark = pytest.mark.software

# Taken at import, before the sandbox swaps in its test config
REAL_DEFAULTS = dict(config.DEFAULT_CONFIG)


def test_the_code_defaults_are_placeholders_not_a_real_pack():
    # Real IDs here skip snapshot's "fill in your Drive ID" stop for every fresh
    # kit and put the pack's Drive links in source; they belong in pack_config.json
    assert REAL_DEFAULTS["drive_file_id"] == "PASTE_FILE_ID_HERE", "put real IDs in pack_config.json"
    assert REAL_DEFAULTS["update_file_id"] == "", "put real IDs in pack_config.json"


def test_load_config_merges_the_kit_file_over_the_defaults(sandbox):
    cfg_file = sandbox.kit / paths.CONFIG_NAME
    cfg_file.write_text(json.dumps({"drive_file_id": "abc", "pack_name": "P"}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["drive_file_id"] == "abc" and cfg["pack_name"] == "P"
    assert cfg["author"] == config.DEFAULT_CONFIG["author"] and cfg["update_file_id"] == ""


def test_load_config_falls_back_to_defaults_on_a_broken_file(sandbox):
    (sandbox.kit / paths.CONFIG_NAME).write_text("{not json", encoding="utf-8")
    assert config.load_config() == config.DEFAULT_CONFIG


def test_settings_round_trip_through_the_work_folder(sandbox):
    config.save_setting("game_dir", "D:/Games/Skyrim")
    assert config.settings() == {"game_dir": "D:/Games/Skyrim"}
    assert (sandbox.work / "settings.json").exists()


def _installed(sandbox, base, update=None):
    util.write_json(paths.INSTALLED_MARKER, {"base": base, "update": update})


def test_install_state_is_none_until_the_marker_matches_this_pack(sandbox):
    req = {"base_version": "2026-09-01 10:00"}
    assert config.install_state(req) == "none"
    _installed(sandbox, "2026-08-01 10:00")          # an older full pack
    assert config.install_state(req) == "none"
    _installed(sandbox, "2026-09-01 10:00")
    assert config.install_state(req) == "installed"


def test_install_state_reports_an_update_only_when_one_is_configured(sandbox):
    req = {"base_version": "B", "update_version": "U2"}
    _installed(sandbox, "B", update="U1")
    assert config.install_state(req) == "installed"    # no update_file_id: nothing to fetch
    config.CONFIG["update_file_id"] = "drive-id"
    assert config.install_state(req) == "update"
    _installed(sandbox, "B", update="U2")
    assert config.install_state(req) == "installed"


def test_base_id_falls_back_to_the_drive_id_without_a_manifest_date():
    config.CONFIG["drive_file_id"] = "drive-id"
    assert config.base_id({}) == "drive-id"
    assert config.base_id({"base_version": "2026-09-01 10:00"}) == "2026-09-01 10:00"
