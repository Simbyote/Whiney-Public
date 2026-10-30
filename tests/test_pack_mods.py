"""
test_pack_mods.py  --  src/whiney/pack_mods.py

pack_mods decides what the maintainer uploads. These pin the mod fingerprints that
decide what an update carries, the archive layout (everything under mods/),
the cumulative update diff with its _update_info.json, and the archive
checksums every player's download is checked against.
test_installer.py checks the other side of that archive.

--software  Fake staging folders and real tarballs in the sandbox.
"""
import hashlib
import json
import shutil
import tarfile

import pytest

from builders import make_mod
from whiney import pack_mods

pytestmark = pytest.mark.software


@pytest.fixture
def staging(sandbox):
    (sandbox.staging / "__vortex_staging_folder").write_text("", encoding="utf-8")
    make_mod(sandbox.staging, "Alpha-11111-1-0-1700000000", {"Alpha.esp": b"A", "textures/a.dds": b"tex"})
    make_mod(sandbox.staging, "Beta-22222-2-0-1700000000", {"Beta.esp": b"B"})
    return sandbox.staging


def test_mod_dirs_skip_vortex_bookkeeping_folders(staging):
    (staging / "__vortex_internal").mkdir()
    assert pack_mods.mod_dirs(staging) == ["Alpha-11111-1-0-1700000000", "Beta-22222-2-0-1700000000"]


def test_fingerprint_changes_when_a_file_changes_size(staging):
    before = pack_mods.fingerprint(staging, "Beta-22222-2-0-1700000000")
    assert before == pack_mods.fingerprint(staging, "Beta-22222-2-0-1700000000")
    (staging / "Beta-22222-2-0-1700000000" / "Beta.esp").write_bytes(b"B2")
    assert pack_mods.fingerprint(staging, "Beta-22222-2-0-1700000000") != before


def test_full_pack_writes_archive_and_manifest_and_clears_the_last_update(sandbox, staging):
    pack_mods.LAST_UPDATE.write_text("{}", encoding="utf-8")
    out = sandbox.kit / "modpack.tar.gz"
    assert pack_mods.full_pack(staging, out, level=1)
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
    assert names == ["mods/Alpha-11111-1-0-1700000000/Alpha.esp",
                     "mods/Alpha-11111-1-0-1700000000/textures/a.dds",
                     "mods/Beta-22222-2-0-1700000000/Beta.esp"]
    manifest = json.loads(pack_mods.MANIFEST.read_text(encoding="utf-8"))
    assert sorted(manifest["mods"]) == ["Alpha-11111-1-0-1700000000", "Beta-22222-2-0-1700000000"]
    assert manifest["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert manifest["size"] == out.stat().st_size        # lets players' installers spot a copy they have
    assert not pack_mods.LAST_UPDATE.exists()     # a fresh full pack has no update yet


def test_update_pack_carries_only_added_and_changed_mods(sandbox, staging):
    pack_mods.full_pack(staging, sandbox.kit / "modpack.tar.gz", level=1)
    (staging / "Beta-22222-2-0-1700000000" / "Beta.esp").write_bytes(b"B, changed")
    make_mod(staging, "Gamma-33333-1-0-1700000000", {"Gamma.esp": b"G"})
    shutil.rmtree(staging / "Alpha-11111-1-0-1700000000")

    out = sandbox.kit / "modpack_update.tar.gz"
    assert pack_mods.update_pack(staging, out, level=1)
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
        info = json.load(tar.extractfile(f"mods/{pack_mods.UPDATE_INFO}"))
    assert names == ["mods/Beta-22222-2-0-1700000000/Beta.esp", "mods/Gamma-33333-1-0-1700000000/Gamma.esp",
                     f"mods/{pack_mods.UPDATE_INFO}"]
    assert (info["added"], info["changed"], info["removed"]) == \
        (["Gamma-33333-1-0-1700000000"], ["Beta-22222-2-0-1700000000"], ["Alpha-11111-1-0-1700000000"])
    last = json.loads(pack_mods.LAST_UPDATE.read_text(encoding="utf-8"))
    assert last["created"] == info["created"]
    assert last["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert last["size"] == out.stat().st_size


def test_update_pack_with_no_changes_writes_nothing(sandbox, staging):
    pack_mods.full_pack(staging, sandbox.kit / "modpack.tar.gz", level=1)
    out = sandbox.kit / "modpack_update.tar.gz"
    assert pack_mods.update_pack(staging, out, level=1)
    assert not out.exists()


def _with_together_cache(staging, cache_bytes):
    mod = make_mod(staging, "Skyrim Together Reborn-69993-1-6-1700000000",
                   {"SkyrimTogetherReborn/SkyrimTogether.exe": b"MZ"})
    cache = mod / "SkyrimTogetherReborn" / "cache" / "Local State"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(cache_bytes)
    return mod


def test_skyrim_togethers_cache_is_left_out_of_the_pack(sandbox, staging):
    _with_together_cache(staging, b"maintainer's session")
    out = sandbox.kit / "modpack.tar.gz"
    pack_mods.full_pack(staging, out, level=1)
    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert "mods/Skyrim Together Reborn-69993-1-6-1700000000/SkyrimTogetherReborn/SkyrimTogether.exe" in names
    assert not any("/cache/" in n for n in names)


def test_a_new_game_session_doesnt_make_skyrim_together_look_updated(sandbox, staging):
    mod = _with_together_cache(staging, b"session one")
    before = pack_mods.fingerprint(staging, "Skyrim Together Reborn-69993-1-6-1700000000")
    (mod / "SkyrimTogetherReborn" / "cache" / "Local State").write_bytes(b"session two, a longer cache")
    (mod / "SkyrimTogetherReborn" / "cache" / "new.bin").write_bytes(b"x")
    assert pack_mods.fingerprint(staging, "Skyrim Together Reborn-69993-1-6-1700000000") == before
