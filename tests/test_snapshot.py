"""
test_snapshot.py  --  src/whiney/snapshot.py

The snapshot is what every player is checked against: if it records the
wrong game version, plugins or mods, the Doctor and the installer enforce
the wrong thing. These pin the config migration from the old console
installer and what snapshot() writes into _packinfo/, including the archive
checksums the installer checks downloads against.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
import json
import re
from pathlib import Path

import pytest

from builders import make_game, make_mod, write_plugins_txt
from whiney import config, paths, skyrim, snapshot

pytestmark = pytest.mark.software


def test_migrate_config_copies_ids_from_the_old_console_script(sandbox):
    (sandbox.kit / "vortex_import.py").write_text(
        'DRIVE_FILE_ID = "base123"\nUPDATE_FILE_ID = "upd456"\nPACK_NAME = "Old Pack"\n', encoding="utf-8")
    assert snapshot.migrate_config_from_old_script() is True
    cfg = json.loads((sandbox.kit / paths.CONFIG_NAME).read_text(encoding="utf-8"))
    assert (cfg["drive_file_id"], cfg["update_file_id"], cfg["pack_name"]) == ("base123", "upd456", "Old Pack")


def test_migrate_config_never_overwrites_a_filled_in_config(sandbox):
    (sandbox.kit / paths.CONFIG_NAME).write_text(json.dumps({"drive_file_id": "mine"}), encoding="utf-8")
    (sandbox.kit / "vortex_import.py").write_text('DRIVE_FILE_ID = "theirs"\n', encoding="utf-8")
    assert snapshot.migrate_config_from_old_script() is False
    assert json.loads((sandbox.kit / paths.CONFIG_NAME).read_text(encoding="utf-8"))["drive_file_id"] == "mine"


@pytest.fixture
def maintainer(sandbox):
    """The maintainer's PC: a pack config with a Drive ID, a game, a load order, INIs and two staged mods."""
    (sandbox.kit / paths.CONFIG_NAME).write_text(json.dumps({"drive_file_id": "drive-id"}), encoding="utf-8")
    game = make_game(sandbox.root / "game")
    (game / "skse64_loader.exe").write_bytes(b"")
    (game / "skse64_1_6_1170.dll").write_bytes(b"")
    config.save_setting("game_dir", str(game))
    write_plugins_txt(paths.SKYRIM_APPDATA / "plugins.txt", enabled=["A.esp"])
    ini_dir = skyrim.ini_dir()
    ini_dir.mkdir(parents=True)
    (ini_dir / "Skyrim.ini").write_text("[General]\n", encoding="utf-8")
    (ini_dir / "SkyrimPrefs.ini").write_text("[Display]\n", encoding="utf-8")      # per-PC: must not be shipped
    make_mod(sandbox.staging, "Alpha-11111-1-0-1700000000", {"Alpha.esp": b""})
    make_mod(sandbox.staging, "Beta-22222-1-0-1700000000", {"Beta.esp": b""})
    (sandbox.staging / "__vortex_staging_folder").mkdir()
    return game


def test_snapshot_copies_the_load_order_and_only_the_shared_inis(sandbox, maintainer):
    snapshot.snapshot()
    assert sorted(p.name for p in sandbox.packinfo.iterdir()) == \
        sorted(["Skyrim.ini", "plugins.txt", paths.REQ_FILE, paths.INVENTORY_FILE])


def test_snapshot_records_what_the_pack_was_built_against(sandbox, maintainer):
    snapshot.snapshot()
    req = json.loads((sandbox.packinfo / paths.REQ_FILE).read_text(encoding="utf-8"))
    assert req["skse_dlls"] == ["skse64_1_6_1170.dll"]
    assert req["mods"] == ["Alpha-11111-1-0-1700000000", "Beta-22222-1-0-1700000000"]
    assert req["inis"] == ["Skyrim.ini"]
    assert (req["cc_plugins"], req["uses_enb"]) == ([], False)


@pytest.mark.parametrize("update_file_id, update_sha", [("drive-update", "bbb"), ("", None)],
                         ids=["update-published", "no-update"])
def test_snapshot_carries_the_pack_checksums(sandbox, maintainer, update_file_id, update_sha):
    # An update's checksum only counts once its Drive ID is configured, like its version
    config_file = sandbox.kit / paths.CONFIG_NAME
    config_file.write_text(json.dumps({"drive_file_id": "drive-id", "update_file_id": update_file_id}),
                           encoding="utf-8")
    (sandbox.kit / "pack_manifest.json").write_text(
        json.dumps({"created": "2026-10-01 12:00", "sha256": "aaa", "size": 111, "mods": {}}), encoding="utf-8")
    (sandbox.kit / "last_update.json").write_text(
        json.dumps({"created": "2026-10-20 12:00", "sha256": "bbb", "size": 222}), encoding="utf-8")
    snapshot.snapshot()
    req = json.loads((sandbox.packinfo / paths.REQ_FILE).read_text(encoding="utf-8"))
    assert (req["base_sha256"], req["update_sha256"]) == ("aaa", update_sha)
    assert (req["base_size"], req["update_size"]) == (111, 222 if update_sha else None)


def test_the_inventory_records_only_what_is_deployed_and_where(sandbox, maintainer):
    # Alpha is deployed (one file into Data, one fomod leftover that Vortex didn't deploy);
    # an SKSE-type mod deploys to the game folder itself; Beta is in Vortex but disabled
    alpha = sandbox.staging / "Alpha-11111-1-0-1700000000"
    (alpha / "Textures").mkdir()
    (alpha / "Textures" / "a.dds").write_bytes(b"tex")
    (alpha / "fomod").mkdir()
    (alpha / "fomod" / "ModuleConfig.xml").write_text("<config/>", encoding="utf-8")
    make_mod(sandbox.staging, "SKSE-30379-2-2-6-1700000000", {"skse64_loader.exe": b"MZ"})
    (maintainer / "Data" / "textures").mkdir(parents=True)
    (maintainer / "Data" / "textures" / "a.dds").write_bytes(b"tex")         # case differs: still found
    (maintainer / "Data" / "Alpha.esp").write_bytes(b"")
    snapshot.snapshot()
    inventory = json.loads((sandbox.packinfo / paths.INVENTORY_FILE).read_text(encoding="utf-8"))
    assert inventory == {
        "Alpha-11111-1-0-1700000000": ["Data/Alpha.esp", "Data/Textures/a.dds"],
        "SKSE-30379-2-2-6-1700000000": ["skse64_loader.exe"],      # make_game's loader stands in for it
    }


def test_snapshot_stops_until_a_drive_id_is_filled_in(sandbox, maintainer):
    (sandbox.kit / paths.CONFIG_NAME).unlink()
    with pytest.raises(SystemExit, match="drive_file_id"):
        snapshot.snapshot()
    # It leaves the template behind to be filled in
    cfg = json.loads((sandbox.kit / paths.CONFIG_NAME).read_text(encoding="utf-8"))
    assert cfg["drive_file_id"] == "PASTE_FILE_ID_HERE"


def test_every_requirement_the_app_reads_is_one_snapshot_writes(sandbox, maintainer):
    # requirements.json is the contract between the maintainer's build and every player's
    # app: a key read but never written silently disables that check
    snapshot.snapshot()
    written = set(json.loads((sandbox.packinfo / paths.REQ_FILE).read_text(encoding="utf-8")))
    src = Path(snapshot.__file__).parent
    read = set()
    for f in src.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        read |= set(re.findall(r"""\breq(?:uirements)?(?:\.get\(|\[)["']([a-z_]+)["']""", text))
    assert read, "the key pattern matched nothing: update it"
    assert read <= written, f"read but never written: {sorted(read - written)}"
