"""
test_installer.py  --  src/whiney/installer.py

pack_mods runs on the maintainer's PC and the installer on every player's; they share
only the archive format. These run the round trip (pack a staging folder,
unpack it as the installer does, get one zip per mod for Vortex), pin the
install plan each mode runs, and drive every step the player sees: the
download and its browser fallback, the Vortex hand-off, applying the load
order and INIs, the final check, resuming a stopped install, and updates.
Every download (automatic, from the browser, or an update reused from an
earlier run) is checked against the SHA-256 recorded when it was packed. A
A cancel stops at the next safe point and the next Start resumes. A
crafted archive (an entry outside the unpack folder, a link) stops the
install before anything outside is written, on Pythons with and without
tarfile's "data" filter.

--software  Real tarballs and zips in the sandbox; Google Drive is FakeGdown, the
            GUI is a scripted FakeUI, Vortex and the shell are FakeWinapi.
"""
import hashlib
import io
import json
import shutil
import tarfile
import threading
import zipfile

import pytest

from builders import make_game, make_mod, write_plugin, write_plugins_txt
from whiney import config, installer, pack_mods, paths, skyrim, util

pytestmark = pytest.mark.software


@pytest.fixture
def staging(sandbox):
    (sandbox.staging / "__vortex_staging_folder").write_text("", encoding="utf-8")
    make_mod(sandbox.staging, "Alpha-11111-1-0-1700000000", {"Alpha.esp": b"A", "textures/a.dds": b"tex"})
    make_mod(sandbox.staging, "Beta-22222-2-0-1700000000", {"Beta.esp": b"B"})
    return sandbox.staging


class FakeUI:
    """Stands in for the GUI the installer drives: records everything, answers from a script.

    answers: what ask() replies, in order (its default once they run out).
    on_wait: what the player does at each wait_for_user, in order. A wait with
        nothing scripted fails the test rather than looping like the real one.
    """
    def __init__(self, answers=(), on_wait=()):
        self.answers, self.on_wait = list(answers), list(on_wait)
        self.logs, self.steps, self.asked, self.told, self.waits = [], [], [], [], []

    def step(self, key, state): self.steps.append((key, state))
    def log(self, text): self.logs.append(text)
    def progress(self, fraction, text): pass
    def tell(self, message): self.told.append(message)

    def ask(self, question, default):
        self.asked.append(question)
        return self.answers.pop(0) if self.answers else default

    def wait_for_user(self, title, body, button, extras=()):
        self.waits.append((title, body))
        if not self.on_wait:
            raise RuntimeError(f"the installer waited for the player ({title!r}) and the test scripted nothing")
        self.on_wait.pop(0)()


def test_installer_unpacks_a_full_pack_into_one_zip_per_mod(sandbox, staging):
    # The packer wraps everything in mods/; find_pack_root must step through it
    archive = sandbox.work / "modpack.tar.gz"
    pack_mods.full_pack(staging, archive, level=1)
    inst = installer.Installer(FakeUI(), "fresh")
    inst.extract(archive, paths.EXTRACT_DIR)
    root = inst.find_pack_root(paths.EXTRACT_DIR)
    assert inst.build_zips(root, paths.ZIP_DIR) == 2
    with zipfile.ZipFile(paths.ZIP_DIR / "Alpha-11111-1-0-1700000000.zip") as zf:
        assert sorted(zf.namelist()) == ["Alpha.esp", "textures/a.dds"]


def _tar_with(archive, member):
    """A .tar.gz holding one good file, then `member` (a TarInfo the test crafted)."""
    with tarfile.open(archive, "w:gz") as tar:
        good = tarfile.TarInfo("mods/Alpha/Alpha.esp")
        good.size = 1
        tar.addfile(good, io.BytesIO(b"A"))
        tar.addfile(member, io.BytesIO(b"x" * member.size) if member.isfile() else None)


def _member(name, kind=tarfile.REGTYPE, link=""):
    m = tarfile.TarInfo(name)
    m.type, m.linkname = kind, link
    m.size = 1 if kind == tarfile.REGTYPE else 0
    return m


BAD_MEMBERS = [
    pytest.param(lambda out: _member("../escape.txt"), id="dotdot"),
    pytest.param(lambda out: _member("mods/../../escape.txt"), id="nested-dotdot"),
    pytest.param(lambda out: _member(str(out / "escape.txt")), id="absolute"),
    pytest.param(lambda out: _member("mods/link", tarfile.SYMTYPE, str(out)), id="symlink"),
    pytest.param(lambda out: _member("mods/hard", tarfile.LNKTYPE, "mods/Alpha/Alpha.esp"), id="hardlink"),
]


# Simulating an old Python makes this one call tar.extract unfiltered, which 3.12+ warns about
@pytest.mark.filterwarnings("ignore:Python 3.14 will:DeprecationWarning")
@pytest.mark.parametrize("has_data_filter", [True, False], ids=["data-filter", "old-python"])
@pytest.mark.parametrize("make_bad", BAD_MEMBERS)
def test_an_unsafe_archive_entry_stops_the_install_and_writes_nothing_outside(
        sandbox, monkeypatch, make_bad, has_data_filter):
    if not has_data_filter:
        # Python before 3.10.12 / 3.11.4: no "data" filter; the check must not depend on it
        monkeypatch.delattr(installer.tarfile, "data_filter", raising=False)
    archive = sandbox.work / "modpack.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    _tar_with(archive, make_bad(sandbox.root))
    with pytest.raises(installer.Abort, match="can't be unpacked safely"):
        installer.Installer(FakeUI(), "fresh").extract(archive, paths.EXTRACT_DIR)
    assert not (sandbox.root / "escape.txt").exists()
    assert not (sandbox.work / "escape.txt").exists()
    assert not archive.exists()     # deleted, so a retry downloads it again


def test_a_mod_that_is_only_an_archive_is_passed_to_vortex_as_is(sandbox):
    root = sandbox.work / "pack"
    make_mod(root, "Repack-44444-1-0-1700000000", {"Repack.7z": b"7z bytes"})
    ui = FakeUI()
    installer.Installer(ui, "fresh").build_zips(root, paths.ZIP_DIR)
    assert (paths.ZIP_DIR / "Repack-44444-1-0-1700000000.7z").read_bytes() == b"7z bytes"
    assert not (paths.ZIP_DIR / "Repack-44444-1-0-1700000000.zip").exists()


@pytest.mark.parametrize("update_id, mode, steps", [
    ("", "fresh", ["check", "download", "unpack", "prepare", "vortex", "order", "verify"]),
    ("u", "fresh", ["check", "download", "unpack", "prepare", "update", "vortex", "order", "verify"]),
    ("u", "update", ["check", "update", "vortex", "order", "verify"]),
])
def test_install_plan_adds_the_update_step_only_when_configured(update_id, mode, steps):
    config.CONFIG["update_file_id"] = update_id
    assert installer.plan(mode) == steps


# ---- a player's PC and the pack on Drive -----------------------------------------------------
BASE_ID = "drive-base"                   # the full pack's Drive file ID
UPDATE_ID = "drive-update"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """download() polls its worker thread every 0.5 s; the fake Drive is instant."""
    monkeypatch.setattr(installer.time, "sleep", lambda s: None)


@pytest.fixture
def drive(sandbox, staging):
    """The full pack, built by pack_mods from `staging` and served as Drive file BASE_ID."""
    archive = sandbox.root / "drive" / "modpack.tar.gz"
    pack_mods.full_pack(staging, archive, level=1)
    sandbox.gdown.files[BASE_ID] = archive
    config.CONFIG["drive_file_id"] = BASE_ID
    return archive


@pytest.fixture
def player(sandbox):
    """A player's PC: the game (with the pack's plugins already deployed), their own load order and INI,
    and the pack's load order, INI and requirements in _packinfo."""
    game = make_game(sandbox.root / "game")
    for name in ("Alpha.esp", "Beta.esp"):
        write_plugin(game / "Data", name)
    write_plugins_txt(paths.SKYRIM_APPDATA / "plugins.txt", enabled=["Theirs.esp"])
    skyrim.ini_dir().mkdir(parents=True)
    (skyrim.ini_dir() / "Skyrim.ini").write_text("[theirs]\n", encoding="utf-8")
    write_plugins_txt(sandbox.packinfo / "plugins.txt", enabled=["Alpha.esp", "Beta.esp"])
    (sandbox.packinfo / "Skyrim.ini").write_text("[pack]\n", encoding="utf-8")
    util.write_json(sandbox.packinfo / paths.REQ_FILE, {"base_version": "2026-10-01 12:00", "inis": ["Skyrim.ini"]})
    return game


def closes_vortex():
    """The player's part of the Vortex hand-off: install, deploy, close Vortex (nothing to fake)."""


def _states(ui):
    return dict(ui.steps)                # last state per step


# ---- a whole install ---------------------------------------------------------------------
def test_a_fresh_install_runs_every_step_and_records_the_install(sandbox, drive, player):
    ui = FakeUI(on_wait=[closes_vortex])
    installer.Installer(ui, "fresh", game=player).run()

    assert _states(ui) == {k: "done" for k in installer.plan("fresh")}
    assert sandbox.gdown.requested == [BASE_ID]
    assert sorted(p.name for p in paths.ZIP_DIR.glob("*.zip")) == \
        ["Alpha-11111-1-0-1700000000.zip", "Beta-22222-2-0-1700000000.zip"]
    assert str(paths.ZIP_DIR) in sandbox.winapi.opened           # the folder the player drags from
    # The pack's load order and INI replace the player's, which are kept as .bak
    assert skyrim.enabled_plugins(paths.SKYRIM_APPDATA / "plugins.txt") == ["Alpha.esp", "Beta.esp"]
    assert skyrim.enabled_plugins(paths.SKYRIM_APPDATA / "plugins.txt.bak") == ["Theirs.esp"]
    assert (skyrim.ini_dir() / "Skyrim.ini").read_text(encoding="utf-8") == "[pack]\n"
    assert (skyrim.ini_dir() / "Skyrim.ini.bak").read_text(encoding="utf-8") == "[theirs]\n"
    marker = util.read_json(paths.INSTALLED_MARKER)
    assert (marker["base"], marker["update"]) == ("2026-10-01 12:00", None)
    assert config.install_state() == "installed"


def test_a_stopped_install_resumes_without_downloading_again(sandbox, drive, player):
    # Requirement I4. The player forgot to Deploy: the final check stops the install
    (player / "Data" / "Beta.esp").unlink()
    first = FakeUI(on_wait=[closes_vortex])
    with pytest.raises(installer.Abort, match="1 plugin"):
        installer.Installer(first, "fresh", game=player).run()
    assert _states(first)["verify"] == "error" and not paths.INSTALLED_MARKER.exists()

    write_plugin(player / "Data", "Beta.esp")                    # they Deploy, then click Install again
    again = FakeUI(on_wait=[closes_vortex])
    installer.Installer(again, "fresh", game=player).run()
    assert [_states(again)[k] for k in ("download", "unpack", "prepare")] == ["skipped"] * 3
    assert sandbox.gdown.requested == [BASE_ID]                 # downloaded once, across both runs
    assert config.install_state() == "installed"


# ---- the download --------------------------------------------------------------------------
def test_an_archive_from_an_older_pack_is_downloaded_again(sandbox, drive, player):
    paths.WORK_DIR.mkdir()
    paths.ARCHIVE.write_bytes(b"an older pack")
    paths.ARCHIVE_ID.write_text("2026-08-01 09:00", encoding="locale")
    inst = installer.Installer(FakeUI(), "fresh", game=player)
    inst.get_base()
    assert sandbox.gdown.requested == [BASE_ID]
    assert paths.ARCHIVE.read_bytes() == drive.read_bytes()
    assert paths.ARCHIVE_ID.read_text(encoding="locale") == inst.base


def test_an_archive_of_this_pack_is_not_downloaded_again(sandbox, drive, player):
    inst = installer.Installer(FakeUI(), "fresh", game=player)
    paths.WORK_DIR.mkdir()
    paths.ARCHIVE.write_bytes(drive.read_bytes())
    paths.ARCHIVE_ID.write_text(inst.base, encoding="locale")
    assert inst.get_base() == "skipped" and sandbox.gdown.requested == []


def test_when_drive_refuses_the_player_downloads_it_in_the_browser(sandbox, drive, player):
    sandbox.gdown.error = RuntimeError("Too many users have viewed or downloaded this file recently")

    def downloads_it():
        paths.DOWNLOADS.mkdir(parents=True)
        (paths.DOWNLOADS / "modpack.tar.gz").write_bytes(drive.read_bytes())

    ui = FakeUI(on_wait=[downloads_it])
    installer.Installer(ui, "fresh", game=player).get_base()
    assert any(log.startswith("Automatic download failed: RuntimeError") for log in ui.logs)
    assert sandbox.winapi.urls == [f"https://drive.google.com/file/d/{BASE_ID}/view"]
    assert ui.asked == ["Use modpack.tar.gz (" + util.human(drive.stat().st_size) + ")?"]
    assert paths.ARCHIVE.read_bytes() == drive.read_bytes()
    assert not (paths.DOWNLOADS / "modpack.tar.gz").exists()    # moved, not copied


def test_the_browser_fallback_keeps_waiting_until_the_download_appears(sandbox, drive, player):
    del sandbox.gdown.files[BASE_ID]                            # gdown gives up without an error

    def still_downloading():
        paths.DOWNLOADS.mkdir(parents=True, exist_ok=True)

    def finished():
        (paths.DOWNLOADS / "modpack (1).tar.gz").write_bytes(drive.read_bytes())

    ui = FakeUI(on_wait=[still_downloading, finished])
    installer.Installer(ui, "fresh", game=player).get_base()
    assert len(ui.told) == 1 and ui.told[0].startswith("No .tar.gz file found")
    assert paths.ARCHIVE.exists()


# ---- cancelling -------------------------------------------------------------------------------
def test_cancelling_before_the_first_step_runs_nothing(sandbox, drive, player):
    cancel = threading.Event()
    cancel.set()                                       # Start, then Cancel straight away
    ui = FakeUI()
    with pytest.raises(installer.Cancelled):
        installer.Installer(ui, "fresh", game=player, cancel=cancel).run()
    assert ui.steps == [] and sandbox.gdown.requested == []


def test_cancelling_a_download_leaves_no_files_and_the_next_start_downloads_it_again(sandbox, drive, player):
    cancel = threading.Event()
    sandbox.gdown.midway = cancel.set
    ui = FakeUI(on_wait=[closes_vortex])
    with pytest.raises(installer.Cancelled):
        installer.Installer(ui, "fresh", game=player, cancel=cancel).run()
    assert _states(ui)["download"] == "cancelled"
    assert sorted(p.name for p in paths.WORK_DIR.iterdir()) == []   # no archive, no gdown leftover

    sandbox.gdown.midway = None
    again = FakeUI(on_wait=[closes_vortex])
    installer.Installer(again, "fresh", game=player, cancel=threading.Event()).run()
    assert sandbox.gdown.requested == [BASE_ID, BASE_ID] and config.install_state() == "installed"


def test_cancelling_at_the_vortex_hand_off_resumes_there(sandbox, drive, player):
    cancel = threading.Event()
    ui = FakeUI(on_wait=[cancel.set])                 # the player clicks Cancel instead of Done
    with pytest.raises(installer.Cancelled, match="click Start to pick up where it stopped"):
        installer.Installer(ui, "fresh", game=player, cancel=cancel).run()
    assert _states(ui)["vortex"] == "cancelled" and not paths.INSTALLED_MARKER.exists()

    again = FakeUI(on_wait=[closes_vortex])
    installer.Installer(again, "fresh", game=player).run()
    assert [_states(again)[k] for k in ("download", "unpack", "prepare")] == ["skipped"] * 3
    assert sandbox.gdown.requested == [BASE_ID]


def test_cancelling_while_unpacking_stops_before_the_next_entry(sandbox, drive, player):
    cancel = threading.Event()
    inst = installer.Installer(FakeUI(), "fresh", game=player, cancel=cancel)
    inst.get_base()
    cancel.set()
    with pytest.raises(installer.Cancelled):
        inst.unpack_base()
    assert paths.ARCHIVE.exists()                      # kept: the next Start unpacks it again


# ---- the checksum ----------------------------------------------------------------------------
def _record_checksums(sandbox, **hashes):
    """Add base_sha256 / update_sha256 to the requirements the exe was built with."""
    req = util.read_json(sandbox.packinfo / paths.REQ_FILE)
    util.write_json(sandbox.packinfo / paths.REQ_FILE, {**req, **hashes})


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_download_matching_the_recorded_checksum_is_used(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    ui = FakeUI()
    installer.Installer(ui, "fresh", game=player).get_base()
    assert paths.ARCHIVE.read_bytes() == drive.read_bytes()
    assert f"The mod pack matches the one {config.CONFIG['author']} packed." in ui.logs


def test_a_damaged_download_is_deleted_and_downloaded_again_next_run(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    good = drive.read_bytes()
    drive.write_bytes(good[: len(good) // 2])              # Drive served a cut-off file
    with pytest.raises(installer.Abort, match="doesn't match"):
        installer.Installer(FakeUI(), "fresh", game=player).get_base()
    assert not paths.ARCHIVE.exists() and not paths.ARCHIVE_ID.exists()

    drive.write_bytes(good)                                # the player clicks Start again
    installer.Installer(FakeUI(), "fresh", game=player).get_base()
    assert sandbox.gdown.requested == [BASE_ID, BASE_ID]
    assert paths.ARCHIVE.read_bytes() == good


def test_the_wrong_file_from_the_browser_fallback_is_refused(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    sandbox.gdown.error = RuntimeError("Too many users have viewed or downloaded this file recently")

    def downloads_something_else():
        paths.DOWNLOADS.mkdir(parents=True)
        (paths.DOWNLOADS / "other-mod.tar.gz").write_bytes(b"not the pack")

    with pytest.raises(installer.Abort, match="doesn't match"):
        installer.Installer(FakeUI(on_wait=[downloads_something_else]), "fresh", game=player).get_base()
    assert not paths.ARCHIVE.exists()


def test_with_no_recorded_checksum_the_download_is_used_unchecked(sandbox, drive, player):
    # A pack recorded with record_baseline.bat, or an exe built before checksums
    ui = FakeUI()
    installer.Installer(ui, "fresh", game=player).get_base()
    assert paths.ARCHIVE.exists()
    assert "No checksum recorded for the mod pack; skipping the integrity check." in ui.logs


# ---- before and after Vortex -----------------------------------------------------------------
def test_failed_checks_stop_the_install_unless_the_player_continues(sandbox, player):
    sandbox.packinfo.joinpath(paths.REQ_FILE).write_text('{"skse_dlls": ["skse64_1_6_1170.dll"]}', encoding="utf-8")
    with pytest.raises(installer.Abort, match="fix the failed checks"):
        installer.Installer(FakeUI(), "fresh", game=player).check()       # ask() defaults to No
    ui = FakeUI(answers=[True])
    installer.Installer(ui, "fresh", game=player).check()
    assert "SKSE for game version 1.6.1170 is missing" in ui.asked[0]


def test_the_vortex_step_waits_until_vortex_is_closed(sandbox, player):
    paths.ZIP_DIR.mkdir(parents=True)
    (paths.ZIP_DIR / "Alpha.zip").write_bytes(b"zip")
    sandbox.winapi.running = ["Vortex.exe"]

    def closes_it():
        sandbox.winapi.running.clear()

    ui = FakeUI(on_wait=[lambda: None, closes_it])                # first "Done" with Vortex still open
    installer.Installer(ui, "fresh", game=player).vortex()
    assert len(ui.waits) == 2 and ui.told[0].startswith("Vortex is still running")
    assert "A folder with 1 mod file(s)" in ui.waits[0][1]


def test_the_vortex_step_is_skipped_with_nothing_to_install(sandbox, player):
    paths.ZIP_DIR.mkdir(parents=True)
    assert installer.Installer(FakeUI(), "fresh", game=player).vortex() == "skipped"
    assert sandbox.winapi.opened == []


def test_load_order_needs_skyrims_settings_folder(sandbox, player):
    import shutil
    shutil.rmtree(paths.SKYRIM_APPDATA)
    with pytest.raises(installer.Abort, match="Launch Skyrim SE once"):
        installer.Installer(FakeUI(), "fresh", game=player).order()


def test_the_players_inis_are_left_alone_when_they_opt_out(sandbox, player):
    installer.Installer(FakeUI(), "fresh", game=player, apply_inis=False).order()
    assert (skyrim.ini_dir() / "Skyrim.ini").read_text(encoding="utf-8") == "[theirs]\n"
    assert not (skyrim.ini_dir() / "Skyrim.ini.bak").exists()
    assert (paths.SKYRIM_APPDATA / "plugins.txt.bak").exists()   # the load order is still applied


def test_verify_names_the_plugins_that_did_not_reach_the_game(sandbox, player):
    for name in ("Alpha.esp", "Beta.esp"):
        (player / "Data" / name).unlink()
    ui = FakeUI()
    with pytest.raises(installer.Abort, match="2 plugin"):
        installer.Installer(ui, "fresh", game=player).verify()
    assert "    - Alpha.esp" in ui.logs and "    - Beta.esp" in ui.logs


def test_verify_stops_when_pack_files_are_missing_unless_the_player_finishes_anyway(sandbox, player):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE,
                    {"Alpha-11111-1-0-1700000000": ["Data/Alpha.esp", "Data/textures/a.dds"]})
    ui = FakeUI()                                                # ask() defaults to No
    with pytest.raises(installer.Abort, match="mod files didn't make it"):
        installer.Installer(ui, "fresh", game=player).verify()
    assert "    Alpha: 1 of 2 files missing (e.g. Data/textures/a.dds)" in ui.logs
    installer.Installer(FakeUI(answers=[True]), "fresh", game=player).verify()


def test_verify_passes_when_every_recorded_file_is_deployed(sandbox, player):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {"Alpha-11111-1-0-1700000000": ["Data/Alpha.esp"]})
    ui = FakeUI()
    installer.Installer(ui, "fresh", game=player).verify()
    assert "Every file from the pack's mods is in place." in ui.logs and ui.asked == []


def test_an_empty_pack_stops_with_a_message(sandbox, player):
    paths.EXTRACT_DIR.mkdir(parents=True)
    with pytest.raises(installer.Abort, match="looks empty"):
        installer.Installer(FakeUI(), "fresh", game=player).prepare_base()


# ---- updates -------------------------------------------------------------------------------
@pytest.fixture
def update(sandbox, staging, drive):
    """After the full pack: Beta changes, Gamma is added, Alpha is removed. Served as Drive file UPDATE_ID."""
    (staging / "Beta-22222-2-0-1700000000" / "Beta.esp").write_bytes(b"B, changed")
    make_mod(staging, "Gamma-33333-1-0-1700000000", {"Gamma.esp": b"G"})
    import shutil
    shutil.rmtree(staging / "Alpha-11111-1-0-1700000000")
    archive = sandbox.root / "drive" / "modpack_update.tar.gz"
    pack_mods.update_pack(staging, archive, level=1)
    sandbox.gdown.files[UPDATE_ID] = archive
    config.CONFIG["update_file_id"] = UPDATE_ID
    return archive


def test_an_update_brings_new_and_changed_mods_and_drops_removed_ones(sandbox, update, player):
    paths.ZIP_DIR.mkdir(parents=True)
    (paths.ZIP_DIR / "Alpha-11111-1-0-1700000000.zip").write_bytes(b"left from the full pack")
    inst = installer.Installer(FakeUI(), "update", game=player)
    inst.get_update()
    assert sorted(p.name for p in paths.ZIP_DIR.glob("*.zip")) == \
        ["Beta-22222-2-0-1700000000.zip", "Gamma-33333-1-0-1700000000.zip"]
    # The player drags just the update's zips, from their own folder
    assert sorted(p.name for p in paths.UPDATE_ZIPS.iterdir()) == \
        ["Beta-22222-2-0-1700000000.zip", "Gamma-33333-1-0-1700000000.zip"]
    assert inst.update_info["removed"] == ["Alpha-11111-1-0-1700000000"]
    assert not paths.UPDATE_ARCHIVE.exists()                     # cleaned up once unpacked


def test_the_update_hand_off_lists_mods_to_remove_in_vortex(sandbox, update, player):
    inst = installer.Installer(FakeUI(), "update", game=player)
    inst.get_update()
    ui = inst.ui = FakeUI(on_wait=[closes_vortex])
    inst.vortex()
    assert "Remove these mods in Vortex" in ui.waits[0][1] and "      - Alpha" in ui.waits[0][1]


def _update_removing(removed):
    """An update archive whose _update_info.json lists `removed`, beside one mod."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in ((f"mods/{paths.UPDATE_INFO}", json.dumps({"removed": removed}).encode()),
                           ("mods/Gamma/Gamma.esp", b"G")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("removed", [
    pytest.param(["../../precious"], id="dotdot"),
    pytest.param(["..\\..\\precious"], id="backslash"),
    pytest.param(["C:precious"], id="drive"),
    pytest.param("precious", id="not-a-list"),
])
def test_an_update_cannot_remove_files_outside_the_vortex_folder(sandbox, player, removed):
    config.CONFIG["update_file_id"] = UPDATE_ID
    paths.ZIP_DIR.mkdir(parents=True)
    precious = paths.ZIP_DIR.parent.parent / "precious.zip"       # ToVortex/../../precious.zip
    precious.write_bytes(b"the player's own file")
    paths.UPDATE_ARCHIVE.write_bytes(_update_removing(removed))
    with pytest.raises(installer.Abort, match="removed mods can't be used safely"):
        installer.Installer(FakeUI(answers=[True]), "update", game=player).get_update()
    assert precious.read_bytes() == b"the player's own file"
    assert not paths.UPDATE_ARCHIVE.exists() and not paths.UPDATE_EXTRACT.exists()


def test_an_update_reused_from_an_earlier_run_is_checked_too(sandbox, update, player):
    # The player kept an older update than the one this exe was built for
    _record_checksums(sandbox, update_sha256=_sha(update))
    paths.WORK_DIR.mkdir()
    paths.UPDATE_ARCHIVE.write_bytes(b"an older update")
    with pytest.raises(installer.Abort, match="doesn't match"):
        installer.Installer(FakeUI(answers=[True]), "update", game=player).get_update()
    assert not paths.UPDATE_ARCHIVE.exists()                    # the next run downloads the right one


def test_an_update_downloaded_earlier_is_reused_if_the_player_agrees(sandbox, update, player):
    paths.WORK_DIR.mkdir()
    paths.UPDATE_ARCHIVE.write_bytes(update.read_bytes())
    ui = FakeUI(answers=[True])
    installer.Installer(ui, "update", game=player).get_update()
    assert sandbox.gdown.requested == [] and ui.asked[0].startswith("Found an update you already downloaded")


# ---- repair: some mods again (the Doctor's Repair button) ----------------------------------
ALPHA = "Alpha-11111-1-0-1700000000"
BETA = "Beta-22222-2-0-1700000000"


def _repair(player, mods, answers=(), on_wait=()):
    ui = FakeUI(answers=answers, on_wait=on_wait)
    return ui, installer.Installer(ui, "repair", game=player, repair=mods)


def _zip_names(mod):
    with zipfile.ZipFile(paths.REPAIR_DIR / f"{mod}.zip") as zf:
        return sorted(zf.namelist())


def test_repair_plan_gathers_hands_off_and_checks():
    assert installer.plan("repair") == ["gather", "vortex", "verify"]


def test_repair_reuses_the_last_installs_zip_when_this_pack_is_installed(sandbox, drive, player):
    installer.Installer(FakeUI(on_wait=[closes_vortex]), "fresh", game=player).run()
    sandbox.gdown.requested.clear()
    ui, job = _repair(player, [ALPHA])
    job.gather()
    assert sorted(p.name for p in paths.REPAIR_DIR.iterdir()) == [f"{ALPHA}.zip"]
    assert sandbox.gdown.requested == [] and ui.asked == []
    assert "Alpha: ready from the last install" in ui.logs


def test_repair_downloads_the_pack_when_nothing_is_left_and_unpacks_only_those_mods(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    ui, job = _repair(player, [ALPHA])
    job.gather()
    assert sandbox.gdown.requested == [BASE_ID] and "the mod pack is needed again" in ui.asked[0]
    assert sorted(p.name for p in paths.REPAIR_DIR.iterdir()) == [f"{ALPHA}.zip"]
    assert _zip_names(ALPHA) == ["Alpha.esp", "textures/a.dds"]
    assert not paths.REPAIR_EXTRACT.exists()
    # The pack is kept, as an install keeps it, so the next repair needn't download it
    assert paths.ARCHIVE.exists() and paths.ARCHIVE_ID.read_text(encoding="locale") == config.base_id()


def test_repair_ignores_zips_left_from_another_pack(sandbox, drive, player):
    paths.ZIP_DIR.mkdir(parents=True)
    (paths.ZIP_DIR / f"{ALPHA}.zip").write_bytes(b"an older pack's zip")    # nothing installed for this pack
    _, job = _repair(player, [ALPHA], answers=[True])
    job.gather()
    assert _zip_names(ALPHA) == ["Alpha.esp", "textures/a.dds"]


def test_repair_stops_if_the_player_wont_download_the_pack(sandbox, drive, player):
    _, job = _repair(player, [ALPHA], answers=[False])
    with pytest.raises(installer.Abort, match="isn't on this PC any more"):
        job.gather()
    assert sandbox.gdown.requested == []


def test_repair_checks_a_pack_left_on_disk_against_its_checksum(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    paths.WORK_DIR.mkdir()
    paths.ARCHIVE.write_bytes(b"not the pack")
    paths.ARCHIVE_ID.write_text(config.base_id(), encoding="locale")
    _, job = _repair(player, [ALPHA])
    with pytest.raises(installer.Abort, match="doesn't match"):
        job.gather()


def test_repair_takes_a_mod_the_update_changed_from_the_update(sandbox, update, player):
    _, job = _repair(player, [BETA])
    job.gather()
    assert sandbox.gdown.requested == [UPDATE_ID]                 # the full pack's Beta is older
    with zipfile.ZipFile(paths.REPAIR_DIR / f"{BETA}.zip") as zf:
        assert zf.read("Beta.esp") == b"B, changed"


def test_repair_of_a_mod_the_pack_doesnt_have_says_so(sandbox, update, player):
    _, job = _repair(player, ["Nope-99999-1-0-1700000000"])
    with pytest.raises(installer.Abort, match="aren't in the mod pack"):
        job.gather()
    assert sandbox.gdown.requested == [UPDATE_ID, BASE_ID]


def test_a_whole_repair_hands_over_just_those_mods_and_checks_their_files(sandbox, drive, player):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE,
                    {ALPHA: ["Data/Alpha.esp", "Data/textures/a.dds"], BETA: ["Data/Beta.esp"]})

    def player_reinstalls_alpha():
        (player / "Data" / "textures").mkdir(parents=True, exist_ok=True)
        (player / "Data" / "textures" / "a.dds").write_bytes(b"tex")

    ui, job = _repair(player, [ALPHA], on_wait=[player_reinstalls_alpha])
    job.run()
    assert _states(ui) == {"gather": "done", "vortex": "done", "verify": "done"}
    assert str(paths.REPAIR_DIR) in sandbox.winapi.opened
    assert "A folder with 1 mod file(s)" in ui.waits[0][1] and "Mod Type" in ui.waits[0][1]
    assert "All 1 repaired mod(s) are in place." in ui.logs
    assert not paths.INSTALLED_MARKER.exists()                     # a repair isn't an install


def test_a_repair_that_didnt_take_stops_and_says_where_the_files_went(sandbox, drive, player):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {ALPHA: ["Data/Alpha.esp", "Data/textures/a.dds"]})

    def vortex_puts_it_in_the_game_folder():
        (player / "textures").mkdir()
        (player / "textures" / "a.dds").write_bytes(b"tex")

    _, job = _repair(player, [ALPHA], on_wait=[vortex_puts_it_in_the_game_folder])
    with pytest.raises(installer.Abort, match="found in the game folder instead of Data") as e:
        job.run()
    assert "Mod Type" in str(e.value)


# ---- using what the player already has ----------------------------------------------------
def test_a_matching_pack_in_downloads_is_used_instead_of_downloading(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive), base_size=drive.stat().st_size)
    paths.DOWNLOADS.mkdir(parents=True)
    (paths.DOWNLOADS / "other.tar.gz").write_bytes(b"x" * drive.stat().st_size)   # same size, other file
    (paths.DOWNLOADS / "modpack (1).tar.gz").write_bytes(drive.read_bytes())       # the browser renamed it
    ui = FakeUI()
    installer.Installer(ui, "fresh", game=player).get_base()
    assert sandbox.gdown.requested == []
    assert paths.ARCHIVE.read_bytes() == drive.read_bytes()
    assert not (paths.DOWNLOADS / "modpack (1).tar.gz").exists()           # moved in, as the fallback does
    assert (paths.DOWNLOADS / "other.tar.gz").exists()
    assert any("Found the mod pack in Downloads (modpack (1).tar.gz)" in line for line in ui.logs)


def test_downloads_isnt_searched_without_a_checksum_to_recognise_the_pack(sandbox, drive, player):
    paths.DOWNLOADS.mkdir(parents=True)
    (paths.DOWNLOADS / "modpack.tar.gz").write_bytes(b"something else")
    installer.Installer(FakeUI(), "fresh", game=player).get_base()
    assert sandbox.gdown.requested == [BASE_ID]
    assert (paths.DOWNLOADS / "modpack.tar.gz").read_bytes() == b"something else"


def test_a_pack_file_the_player_picked_is_copied_not_downloaded(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    usb = sandbox.root / "usb" / "pack.tar.gz"
    usb.parent.mkdir()
    usb.write_bytes(drive.read_bytes())
    ui = FakeUI()
    installer.Installer(ui, "fresh", game=player, pack_file=usb).get_base()
    assert sandbox.gdown.requested == [] and paths.ARCHIVE.read_bytes() == drive.read_bytes()
    assert usb.exists()                                                      # theirs stays where it was
    assert "Using your copy of the mod pack: pack.tar.gz (no download needed)." in ui.logs


def test_a_picked_file_that_isnt_the_pack_stops_without_touching_it(sandbox, drive, player):
    _record_checksums(sandbox, base_sha256=_sha(drive))
    wrong = sandbox.root / "wrong.tar.gz"
    wrong.write_bytes(b"not it")
    with pytest.raises(installer.Abort, match="isn't .*'s mod pack or update"):
        installer.Installer(FakeUI(), "fresh", game=player, pack_file=wrong).get_base()
    assert wrong.read_bytes() == b"not it" and sandbox.gdown.requested == []


def test_a_picked_update_is_used_for_the_update(sandbox, update, player):
    _record_checksums(sandbox, base_sha256=_sha(sandbox.gdown.files[BASE_ID]), update_sha256=_sha(update))
    installer.Installer(FakeUI(), "update", game=player, pack_file=update).get_update()
    assert sandbox.gdown.requested == [] and (paths.UPDATE_ZIPS / "Gamma-33333-1-0-1700000000.zip").exists()


def test_update_only_keeps_tovortex_so_a_full_reinstall_downloads_nothing(sandbox, update, player):
    util.write_json(sandbox.packinfo / paths.REQ_FILE,
                    {**util.read_json(sandbox.packinfo / paths.REQ_FILE), "update_version": "2026-10-20 12:00"})
    installer.Installer(FakeUI(on_wait=[closes_vortex]), "fresh", game=player).run()     # full pack + update
    installer.Installer(FakeUI(on_wait=[closes_vortex]), "update", game=player).run()    # the update again
    assert paths.BASE_READY.exists()                                    # ToVortex survived "Update only"
    sandbox.gdown.requested.clear()
    ui = FakeUI(on_wait=[closes_vortex])
    installer.Installer(ui, "fresh", game=player).run()
    assert sandbox.gdown.requested == []
    assert _states(ui)["download"] == "skipped" and _states(ui)["update"] == "skipped"
    assert sorted(p.name for p in paths.ZIP_DIR.glob("*.zip")) == \
        ["Beta-22222-2-0-1700000000.zip", "Gamma-33333-1-0-1700000000.zip"]


def test_running_update_only_again_rebuilds_the_hand_off_without_downloading(sandbox, update, player):
    util.write_json(sandbox.packinfo / paths.REQ_FILE,
                    {**util.read_json(sandbox.packinfo / paths.REQ_FILE), "update_version": "2026-10-20 12:00"})
    installer.Installer(FakeUI(), "update", game=player).get_update()
    sandbox.gdown.requested.clear()
    shutil.rmtree(paths.UPDATE_ZIPS)
    inst = installer.Installer(FakeUI(), "update", game=player)
    assert inst.get_update() == "skipped" and sandbox.gdown.requested == []
    assert sorted(p.name for p in paths.UPDATE_ZIPS.iterdir()) == \
        ["Beta-22222-2-0-1700000000.zip", "Gamma-33333-1-0-1700000000.zip"]
    assert inst.update_info["removed"] == ["Alpha-11111-1-0-1700000000"]


# ---- every mod already in the game: straight to the load order and settings -----------------
def _all_deployed(sandbox):
    util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {ALPHA: ["Data/Alpha.esp"], BETA: ["Data/Beta.esp"]})


def test_with_every_mod_in_the_game_install_skips_to_the_load_order(sandbox, drive, player):
    _all_deployed(sandbox)
    ui = FakeUI(answers=[True])
    installer.Installer(ui, "fresh", game=player).run()
    assert sandbox.gdown.requested == [] and ui.waits == []                 # no download, no Vortex hand-off
    assert _states(ui) == {"check": "done", "download": "skipped", "unpack": "skipped", "prepare": "skipped",
                           "vortex": "skipped", "order": "done", "verify": "done"}
    assert "Every mod in the pack is already in your game" in ui.asked[0]
    assert (paths.SKYRIM_APPDATA / "plugins.txt.bak").exists()             # the pack's order was applied
    assert (skyrim.ini_dir() / "Skyrim.ini").read_text(encoding="utf-8") == "[pack]\n"
    assert config.install_state() == "installed"


def test_the_player_can_still_reinstall_every_mod(sandbox, drive, player):
    _all_deployed(sandbox)
    ui = FakeUI(answers=[False], on_wait=[closes_vortex])
    installer.Installer(ui, "fresh", game=player).run()
    assert sandbox.gdown.requested == [BASE_ID] and _states(ui)["download"] == "done"


@pytest.mark.parametrize("missing", ["a file", "a plugin", "no file list"])
def test_a_missing_mod_or_no_way_to_tell_runs_the_whole_install(sandbox, drive, player, missing):
    _all_deployed(sandbox)
    if missing == "a file":
        util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {ALPHA: ["Data/Alpha.esp", "Data/textures/a.dds"]})
    elif missing == "a plugin":
        (player / "Data" / "Beta.esp").unlink()
        util.write_json(sandbox.packinfo / paths.INVENTORY_FILE, {ALPHA: ["Data/Alpha.esp"]})
    else:
        (sandbox.packinfo / paths.INVENTORY_FILE).unlink()
    inst = installer.Installer(FakeUI(), "fresh", game=player)
    assert not inst.all_mods_in_place()
