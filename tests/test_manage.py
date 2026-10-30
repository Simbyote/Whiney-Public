"""
test_manage.py  --  src/whiney/manage.py

Manage is where players can lose data: saves, their own INIs, the install
marker. These pin that a restore never destroys the current saves (and that a
backup with an entry outside the saves folder is refused untouched), that
"replace" only deletes saves the safety backup provably holds, that the
player's settings come back from the .bak files install made, and that
freeing space keeps what updates need.

--software  Fake saves and settings in the sandbox.
"""
import zipfile

import pytest

from whiney import config, manage, paths, skyrim, util

pytestmark = pytest.mark.software


@pytest.fixture
def saves(sandbox):
    d = skyrim.saves_dir()
    d.mkdir(parents=True)
    (d / "Save1.ess").write_bytes(b"one")
    return d


def test_backup_of_no_saves_writes_nothing(sandbox):
    assert manage.backup_saves() is None
    assert manage.list_save_backups() == []


def test_restore_backs_up_the_current_saves_first(saves, monkeypatch):
    first = manage.backup_saves()
    (saves / "Save2.ess").write_bytes(b"two")
    # Backups are named to the second; force a distinct name for the second one
    monkeypatch.setattr(manage.time, "strftime", lambda fmt: "20990101-000000")
    safety = manage.restore_saves(first)
    assert safety.name == "Saves-20990101-000000.zip"
    assert (saves / "Save1.ess").read_bytes() == b"one"
    assert (saves / "Save2.ess").exists()      # restore adds back, it doesn't wipe


@pytest.mark.parametrize("name", ["../escape.ess", "../../escape.ess"])
def test_a_backup_with_an_entry_outside_the_saves_folder_is_refused(saves, sandbox, name):
    bad = paths.SAVE_BACKUPS / "Saves-20990101-000000.zip"
    bad.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("Save9.ess", b"nine")
        zf.writestr(name, b"evil")
    with pytest.raises(util.UnsafeArchive):
        manage.restore_saves(bad)
    assert manage.list_save_backups() == [bad]          # no safety backup either: nothing happened
    assert not (saves / "Save9.ess").exists()
    assert not any(p.name == "escape.ess" for p in sandbox.root.rglob("*"))


def _two_backups(saves, monkeypatch):
    """A backup holding Save1, then Save2 made since; returns the backup."""
    backup = manage.backup_saves()
    (saves / "Save2.ess").write_bytes(b"two")
    (saves / "Save2.skse").write_bytes(b"co-save")
    monkeypatch.setattr(manage.time, "strftime", lambda fmt: "20990101-000000")
    return backup


def test_replace_makes_the_saves_folder_exactly_the_backup(saves, monkeypatch):
    backup = _two_backups(saves, monkeypatch)
    (saves / "Save1.ess").write_bytes(b"one, overwritten in game")
    safety = manage.restore_saves(backup, replace=True)
    assert sorted(p.name for p in saves.iterdir()) == ["Save1.ess"]
    assert (saves / "Save1.ess").read_bytes() == b"one"
    with zipfile.ZipFile(safety) as zf:                         # what replace removed is in the safety backup
        assert sorted(zf.namelist()) == ["Save1.ess", "Save2.ess", "Save2.skse"]


def test_merge_is_still_the_default(saves, monkeypatch):
    backup = _two_backups(saves, monkeypatch)
    manage.restore_saves(backup)
    assert sorted(p.name for p in saves.iterdir()) == ["Save1.ess", "Save2.ess", "Save2.skse"]


def test_replace_deletes_nothing_when_the_safety_backup_fails(saves, monkeypatch):
    backup = _two_backups(saves, monkeypatch)

    def disk_full(progress=None):
        raise OSError("No space left on device")
    monkeypatch.setattr(manage, "backup_saves", disk_full)
    with pytest.raises(OSError, match="No space"):
        manage.restore_saves(backup, replace=True)
    assert sorted(p.name for p in saves.iterdir()) == ["Save1.ess", "Save2.ess", "Save2.skse"]


def test_replace_deletes_nothing_when_the_safety_backup_is_incomplete(saves, monkeypatch):
    backup = _two_backups(saves, monkeypatch)
    real = manage.backup_saves

    def then_a_new_save_appears(progress=None):
        made = real(progress)
        (saves / "Save3.ess").write_bytes(b"autosave while restoring")
        return made
    monkeypatch.setattr(manage, "backup_saves", then_a_new_save_appears)
    with pytest.raises(OSError, match="doesn't hold every current save"):
        manage.restore_saves(backup, replace=True)
    assert (saves / "Save2.ess").exists() and (saves / "Save3.ess").exists()


def test_replace_into_an_empty_or_missing_saves_folder_just_restores(saves, monkeypatch):
    backup = manage.backup_saves()
    for p in saves.iterdir():
        p.unlink()
    assert manage.restore_saves(backup, replace=True) is None    # nothing to back up first
    assert sorted(p.name for p in saves.iterdir()) == ["Save1.ess"]


def test_restore_settings_puts_back_the_players_own_files(sandbox):
    plugins = paths.SKYRIM_APPDATA / "plugins.txt"
    plugins.write_text("pack's", encoding="utf-8")
    plugins.with_name("plugins.txt.bak").write_text("mine", encoding="utf-8")
    assert manage.restore_settings() == ["plugins.txt"]
    assert plugins.read_text(encoding="utf-8") == "mine"


def test_free_space_keeps_the_install_marker_and_settings(sandbox):
    paths.WORK_DIR.mkdir()
    paths.ARCHIVE.write_bytes(b"x" * 10)
    paths.ZIP_DIR.mkdir()
    (paths.ZIP_DIR / "Mod.zip").write_bytes(b"y" * 5)
    util.write_json(paths.INSTALLED_MARKER, {"base": "B"})
    config.save_setting("game_dir", "G")
    assert manage.free_space() == 15
    assert not paths.ARCHIVE.exists() and not paths.ZIP_DIR.exists()
    assert paths.INSTALLED_MARKER.exists() and paths.SETTINGS_FILE.exists()


def test_uninstall_forgets_the_install(sandbox):
    util.write_json(paths.INSTALLED_MARKER, {"base": "B"})
    manage.uninstall()
    assert not paths.INSTALLED_MARKER.exists()
