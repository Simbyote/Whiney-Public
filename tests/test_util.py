"""
test_util.py  --  src/whiney/util.py

The small helpers the GUI and the installer show sizes and replace files
with, and the check every archive entry passes before it's unpacked. A wrong
size unit or a lost .bak file reaches players directly; an archive entry that
escapes its folder can overwrite anything the player can write.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
import hashlib

import pytest

from whiney import util

pytestmark = pytest.mark.software


@pytest.mark.parametrize("n, text", [
    (0, "0.0 B"),
    (1023, "1023.0 B"),
    (1024, "1.0 KB"),
    (5 * 1024 ** 3, "5.0 GB"),
    (2048 * 1024 ** 4, "2048.0 TB"),     # TB is the last unit: it never rolls over to PB
])
def test_human_picks_the_largest_unit_under_1024(n, text):
    assert util.human(n) == text


def test_backup_and_copy_keeps_the_previous_file_as_bak(tmp_path):
    src, dst = tmp_path / "new.ini", tmp_path / "out" / "Skyrim.ini"
    src.write_text("new", encoding="utf-8")
    util.backup_and_copy(src, dst)
    assert dst.read_text(encoding="utf-8") == "new" and not dst.with_name("Skyrim.ini.bak").exists()
    dst.write_text("player's own", encoding="utf-8")
    util.backup_and_copy(src, dst)
    assert dst.with_name("Skyrim.ini.bak").read_text(encoding="utf-8") == "player's own"


@pytest.mark.parametrize("name", ["Mod/a.esp", "Mod/", "a/../b.esp", "."])
def test_an_entry_inside_the_folder_is_allowed(tmp_path, name):
    assert util.safe_member_path(tmp_path, name).is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("name", ["../escape.txt", "Mod/../../escape.txt", "{abs}"])
def test_an_entry_outside_the_folder_is_refused(tmp_path, name):
    dest = tmp_path / "dest"
    with pytest.raises(util.UnsafeArchive):
        util.safe_member_path(dest, name.format(abs=tmp_path / "escape.txt"))


def test_sha256_file_reads_the_whole_file_in_blocks(tmp_path):
    data = b"x" * (3 * 1024 * 1024 + 17)         # several 1 MB blocks and a partial one
    f = tmp_path / "pack.tar.gz"
    f.write_bytes(data)
    seen = []
    assert util.sha256_file(f, seen.append) == hashlib.sha256(data).hexdigest()
    assert len(seen) == 4 and seen[-1] == 1.0
