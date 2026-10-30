"""
test_crashsquatch.py  --  src/whiney/crashsquatch.py

After a crash, Crash Squatch names the mod most likely at fault. These pin the
log analysis that ranks suspects (call-stack depth, plugin mentions, noise
filtering, mapping files back to Vortex mods) and the plain-English summary
built from it. The watcher's loop runs on a fake process; hang detection, which needs
20 s of a "Not Responding" window, is not covered.

--software  A synthetic Crash Logger log (tests/fixtures/) and a fake Vortex staging folder.
"""
import calendar
import json
import os
import time
from pathlib import Path

import pytest

from builders import make_mod
from fake_clock import FakeClock
from whiney import crashsquatch, paths, skyrim, winapi

pytestmark = pytest.mark.software

# Synthetic, in Crash Logger SSE's layout: exception line, PROBABLE CALL STACK, REGISTERS
LOG = Path(__file__).parent / "fixtures" / "crashlogger_access_violation.log"


def test_exception_line_is_reduced_to_type_and_location():
    assert crashsquatch.analyze_log(LOG).exception == "Error: EXCEPTION_ACCESS_VIOLATION at SkyrimSE.exe+0C3D4D4"


def test_suspects_are_ranked_dlls_by_stack_depth_then_plugins_by_mentions():
    # BadHooks.dll: frames 1 and 3 -> (10-1) + (10-3) = 16; OtherPlugin.dll: frame 4 -> 6.
    # Immersive Bandits.esp: quoted once (+1) and in "Modified by" (+2) = 3; Bandit Patch.esp: +2.
    # SkyrimSE.exe, ntdll.dll and Skyrim.esm are noise and never suspects.
    suspects = crashsquatch.analyze_log(LOG).suspects
    assert [(s.file, s.kind, s.score) for s in suspects] == [
        ("BadHooks.dll", "SKSE plugin", 16),
        ("OtherPlugin.dll", "SKSE plugin", 6),
        ("Immersive Bandits.esp", "plugin", 3),
        ("Bandit Patch.esp", "plugin", 2),
    ]


def test_suspect_files_are_traced_back_to_their_vortex_mod(sandbox):
    make_mod(sandbox.staging, "Bad Hooks NG-54321-1-2-1700000000", {"SKSE/Plugins/BadHooks.dll": b""})
    top = crashsquatch.analyze_log(LOG).suspects[0]
    assert top.mod == "Bad Hooks NG"


# ---- two mods shipping the same file name ------------------------------------------------------
DLL = "SKSE/Plugins/BadHooks.dll"


@pytest.fixture
def two_owners(sandbox):
    """Two mods that both ship BadHooks.dll, with different contents; the game folder, nothing deployed yet."""
    a = make_mod(sandbox.staging, "Bad Hooks NG-54321-1-2-1700000000", {DLL: b"NG build"})
    b = make_mod(sandbox.staging, "Hooks Bundle-99999-3-0-1700000000", {DLL: b"bundled build"})
    game = sandbox.root / "game"
    (game / "Data" / "SKSE" / "Plugins").mkdir(parents=True)
    return a, b, game


def test_the_mod_whose_copy_vortex_hard_linked_into_the_game_is_named(two_owners):
    a, b, game = two_owners
    os.link(b / DLL, game / "Data" / DLL)                       # Vortex's default deployment: a hard link
    assert crashsquatch.file_owner("BadHooks.dll", game) == "Hooks Bundle"


def test_the_mod_whose_bytes_match_the_deployed_copy_is_named(two_owners):
    a, b, game = two_owners
    (game / "Data" / DLL).write_bytes(b"NG build")             # a copy, not a link
    assert crashsquatch.file_owner("BadHooks.dll", game) == "Bad Hooks NG"


@pytest.mark.parametrize("situation", ["no game folder", "not deployed", "identical copies"])
def test_when_the_deployed_copy_cant_tell_them_apart_both_mods_are_named(two_owners, situation):
    a, b, game = two_owners
    if situation == "identical copies":
        (b / DLL).write_bytes(b"NG build")
        (game / "Data" / DLL).write_bytes(b"NG build")
    folder = None if situation == "no game folder" else game
    assert crashsquatch.file_owner("BadHooks.dll", folder) == "Bad Hooks NG or Hooks Bundle"


def test_two_versions_of_one_mod_are_named_once(sandbox):
    make_mod(sandbox.staging, "Bad Hooks NG-54321-1-2-1700000000", {DLL: b"1.2"})
    make_mod(sandbox.staging, "Bad Hooks NG-54321-1-3-1710000000", {DLL: b"1.3"})
    assert crashsquatch.file_owner("BadHooks.dll") == "Bad Hooks NG"


def test_a_file_no_mod_ships_has_no_owner(sandbox):
    assert crashsquatch.file_owner("SkyrimSE.exe", sandbox.root / "game") is None


def test_the_watcher_names_the_deployed_owner_in_a_saved_crash(sandbox, watch, two_owners):
    a, b, game = two_owners
    os.link(a / DLL, game / "Data" / DLL)
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    logs = skyrim.my_games_dir() / "SKSE" / "Crashlogs"
    logs.mkdir(parents=True)
    (logs / "crash-2026-10-29.log").write_text(LOG.read_text(encoding="utf-8"), encoding="utf-8")
    crash = watch()[1]
    assert crash.analysis.suspects[0].mod == "Bad Hooks NG"
    assert crash.summary.splitlines()[0] == "Most likely involved: Bad Hooks NG (BadHooks.dll)"


def test_windows_faulting_module_names_the_deployed_owner(two_owners):
    a, b, game = two_owners
    os.link(b / DLL, game / "Data" / DLL)
    text = crashsquatch.summarize(crashsquatch.CrashEvent("crash", module="BadHooks.dll"), game)
    assert text.endswith("That file comes from the mod: Hooks Bundle")


# ---- .NET Script Framework logs, and several loggers for one crash -----------------------------
# Synthetic, in .NET Script Framework's layout: module+offset in parentheses on each stack frame
NSF_LOG = Path(__file__).parent / "fixtures" / "netscriptframework_native_exception.txt"


def test_a_net_script_framework_log_names_modules_without_their_parentheses():
    # "(SkyrimSE.exe+C3D4D4)" once read as the file "(SkyrimSE.exe", which slipped past the noise
    # filter as the top suspect and never matched a mod
    a = crashsquatch.analyze_log(NSF_LOG)
    assert [(s.file, s.score) for s in a.suspects] == [("BadHooks.dll", 9), ("MortalEnemies.dll", 8)]
    assert a.exception == "Error: native exception at SkyrimSE.exe+C3D4D4"


def test_one_log_is_analyzed_as_before():
    assert crashsquatch.analyze_logs([LOG]) == crashsquatch.analyze_log(LOG)


def test_logs_from_two_loggers_are_merged_and_agreement_ranks_higher():
    a = crashsquatch.analyze_logs([NSF_LOG, LOG])
    # BadHooks.dll: 9 (NSF) + 16 (Crash Logger); MortalEnemies.dll only in NSF; OtherPlugin.dll only in Crash Logger
    assert [(s.file, s.score) for s in a.suspects[:3]] == [
        ("BadHooks.dll", 25), ("MortalEnemies.dll", 8), ("OtherPlugin.dll", 6)]
    assert (a.log, a.other_logs) == (str(NSF_LOG), (str(LOG),))
    assert a.exception == "Error: native exception at SkyrimSE.exe+C3D4D4"     # the newest log's


def test_the_main_log_is_the_newest_one_that_names_a_suspect(tmp_path):
    empty = tmp_path / "crash-empty.log"
    empty.write_text("Crash Logger started; the game exited before it could write the stack.\n",
                     encoding="utf-8")
    a = crashsquatch.analyze_logs([empty, LOG])
    assert (a.log, a.other_logs) == (str(LOG), (str(empty),))
    assert a.exception.startswith("Error: EXCEPTION_ACCESS_VIOLATION")


def test_a_merged_analysis_round_trips_and_single_log_entries_keep_their_shape():
    merged = crashsquatch.analyze_logs([NSF_LOG, LOG])
    saved = merged.to_json()
    assert list(saved) == ["exception", "suspects", "log", "other_logs"]
    assert crashsquatch.Analysis.from_json(saved) == merged
    assert list(crashsquatch.analyze_log(LOG).to_json()) == ["exception", "suspects", "log"]


def test_the_watcher_combines_every_crash_log_of_the_session(sandbox, watch):
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    crash_logger = skyrim.my_games_dir() / "SKSE" / "Crashlogs"
    crash_logger.mkdir(parents=True)
    (crash_logger / "crash-2026-10-30.log").write_text(LOG.read_text(encoding="utf-8"), encoding="utf-8")
    nsf = sandbox.root / "game" / "Data" / "NetScriptFramework" / "Crash"
    nsf.mkdir(parents=True)
    (nsf / "Crash_2026_10_30.txt").write_text(NSF_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    crash = watch()[1]
    assert len(crash.analysis.other_logs) == 1 and crash.analysis.suspects[0].score == 25
    assert "Combined from 2 crash logs (more than one crash logger is installed)." in crash.summary.splitlines()
    assert crashsquatch.load_history()[0].analysis.other_logs == crash.analysis.other_logs


def test_summary_names_the_top_suspect_and_the_others():
    event = crashsquatch.CrashEvent("crash", analysis=crashsquatch.analyze_log(LOG))
    lines = crashsquatch.summarize(event).splitlines()
    assert lines[0] == "Most likely involved: BadHooks.dll (BadHooks.dll)"
    assert lines[1] == "Also mentioned: OtherPlugin.dll, Immersive Bandits.esp, Bandit Patch.esp"
    assert lines[2].startswith("Error: EXCEPTION_ACCESS_VIOLATION")


def test_summary_without_a_log_falls_back_to_the_windows_faulting_module(sandbox):
    make_mod(sandbox.staging, "Bad Hooks NG-54321-1-2-1700000000", {"SKSE/Plugins/BadHooks.dll": b""})
    text = crashsquatch.summarize(crashsquatch.CrashEvent("crash", module="BadHooks.dll"))
    assert text == "Windows says it crashed in: BadHooks.dll\nThat file comes from the mod: Bad Hooks NG"


@pytest.mark.parametrize("kind, text", [
    ("hang", "Skyrim stopped responding (froze)."),
    ("exit", "Skyrim closed normally."),
])
def test_summary_of_hangs_and_normal_exits(kind, text):
    assert crashsquatch.summarize(crashsquatch.CrashEvent(kind)) == text


def test_history_keeps_the_newest_50_events(sandbox):
    for i in range(55):
        crashsquatch.save_event(crashsquatch.CrashEvent("crash", time=str(i)))
    hist = crashsquatch.load_history()
    assert len(hist) == 50 and hist[0].time == "54"
    assert paths.CRASH_HISTORY.exists()


# ---- Windows' own crash record (wevtutil) ------------------------------------------------
# Synthetic, in `wevtutil qe Application /f:text` layout: newest first, another app's crash on top
EVENTS = (Path(__file__).parent / "fixtures" / "wevtutil_application_errors.txt").read_text(encoding="utf-8")


def test_the_newest_skyrim_event_is_found_past_other_apps():
    assert crashsquatch.parse_crash_events(EVENTS, since=0) == {"module": "BadHooks.dll", "code": "0xc0000005"}


def test_an_event_from_before_this_session_is_ignored():
    # The event is 2026-10-29; a session starting the next day can't have caused it
    assert crashsquatch.parse_crash_events(EVENTS, since=time.mktime((2026, 10, 30, 0, 0, 0, 0, 0, -1))) is None


# The fixture's Skyrim event is at 2026-10-29T20:51:47Z (UTC, as wevtutil writes it)
SKYRIM_EVENT_UTC = calendar.timegm((2026, 10, 29, 20, 51, 47, 0, 0, 0))


@pytest.fixture(params=["America/New_York", "Asia/Tokyo"])
def local_timezone(request, monkeypatch):
    """Run in a time zone west, then east, of UTC: reading a UTC date as local time is wrong in both."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on Windows; CI's Ubuntu run covers this")
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


def test_an_event_an_hour_into_the_session_is_found_in_any_time_zone(local_timezone):
    assert crashsquatch.parse_crash_events(EVENTS, since=SKYRIM_EVENT_UTC - 3600) is not None


def test_an_event_an_hour_before_the_session_is_ignored_in_any_time_zone(local_timezone):
    # West of UTC, reading the date as local time made this earlier session's crash look new
    assert crashsquatch.parse_crash_events(EVENTS, since=SKYRIM_EVENT_UTC + 3600) is None


def test_a_date_without_z_is_local_time():
    local = EVENTS.replace("2026-10-29T20:51:47.5550000Z", "2026-10-29T20:51:47")
    start = time.mktime((2026, 10, 29, 20, 0, 0, 0, 0, -1))
    assert crashsquatch.parse_crash_events(local, since=start) is not None
    assert crashsquatch.parse_crash_events(local, since=start + 2 * 3600) is None


def test_no_skyrim_event_means_none():
    assert crashsquatch.parse_crash_events(EVENTS.split("Event[1]")[0], since=0) is None


def test_crash_events_are_read_through_wevtutil_on_windows(sandbox, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    sandbox.winapi.outputs["wevtutil"] = EVENTS
    assert crashsquatch.windows_crash_event(since=0)["module"] == "BadHooks.dll"
    assert sandbox.winapi.commands[0][:3] == ["wevtutil", "qe", "Application"]


def test_crash_events_are_none_when_wevtutil_cannot_run(sandbox, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    assert crashsquatch.windows_crash_event(since=0) is None


# ---- the watcher, on a fake process ---------------------------------------------------------
@pytest.fixture
def clock(monkeypatch):
    """crashsquatch's clock: sleeps are instant and scripted events fire on time."""
    fake = FakeClock(start=1000.0)
    monkeypatch.setattr(crashsquatch, "time", fake)
    return fake


@pytest.fixture
def watcher(sandbox, clock):
    """A CrashSquatcher whose events are collected in watcher.events."""
    events = []
    w = crashsquatch.CrashSquatcher(sandbox.root / "game", events.append)
    w.events = events
    return w


@pytest.fixture
def watch(watcher):
    """Run the watcher's loop to the end on the calling thread; returns its events."""
    def run(launched="skse64_loader.exe"):
        watcher._run(started=0.0, launched=launched)
        return watcher.events
    return run


def test_launch_starts_skse_when_its_loader_is_there(sandbox):
    game = sandbox.root / "game"
    game.mkdir()
    (game / "skse64_loader.exe").write_bytes(b"MZ")
    assert crashsquatch.CrashSquatcher(game, print).launch() == "skse64_loader.exe"
    assert sandbox.winapi.launched == [(str(game / "skse64_loader.exe"), str(game), False)]


def test_a_game_that_exits_without_a_crash_log_is_a_normal_exit(sandbox, watch):
    sandbox.winapi.running = [crashsquatch.GAME_EXE]          # found, then process_stats says it's gone
    events = watch()
    assert [type(e).__name__ for e in events] == ["Status", "CrashEvent", "Status"]
    assert (events[1].kind, events[1].summary) == ("exit", "Skyrim closed normally.")
    assert crashsquatch.load_history() == []                   # normal exits aren't kept


def test_a_game_that_exits_leaving_a_crash_log_is_a_crash_with_its_analysis(sandbox, watch):
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    logs = skyrim.my_games_dir() / "SKSE" / "Crashlogs"
    logs.mkdir(parents=True)
    (logs / "crash-2026-10-29.log").write_text(LOG.read_text(encoding="utf-8"), encoding="utf-8")
    crash = watch()[1]
    assert crash.kind == "crash" and crash.analysis.suspects[0].file == "BadHooks.dll"
    assert crashsquatch.load_history()[0].kind == "crash"


def _crash_log(mtime):
    logs = skyrim.my_games_dir() / "SKSE" / "Crashlogs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "crash-2026-10-29.log"
    log.write_text(LOG.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(log, (mtime, mtime))
    return log


def test_a_crash_log_from_an_earlier_session_is_not_this_sessions_crash(sandbox, watch):
    # The game started at 1_800_000_000; the only log is from the day before
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    sandbox.winapi.create_times[crashsquatch.GAME_EXE] = 1_800_000_000.0
    _crash_log(1_800_000_000 - 86_400)
    exit_ = watch()[1]
    assert (exit_.kind, exit_.analysis) == ("exit", None)
    assert crashsquatch.load_history() == []


def test_a_crash_log_written_during_the_session_is_used(sandbox, watch):
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    sandbox.winapi.create_times[crashsquatch.GAME_EXE] = 1_800_000_000.0
    _crash_log(1_800_000_000 + 600)
    assert watch()[1].kind == "crash"


def test_a_game_whose_start_time_windows_wont_give_is_still_watched(sandbox, watch, clock):
    # psutil reports create_time as None when access is denied (a game run as administrator);
    # the watch then counts from when it started watching instead of crashing its thread
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    sandbox.winapi.create_times[crashsquatch.GAME_EXE] = None
    sandbox.winapi.stats[crashsquatch.GAME_EXE] = (True, 1024)
    clock.at(1010.0, lambda: sandbox.winapi.stats.update({crashsquatch.GAME_EXE: (False, 0)}))
    events = watch()
    running = next(e for e in events if isinstance(e, crashsquatch.Status) and e.state == "running")
    assert running.uptime == 1000.0                         # since watching started (started=0.0 in `watch`)
    assert [e.kind for e in events if isinstance(e, crashsquatch.CrashEvent)] == ["exit"]


# ---- the crash history file (crash_history.json on players' PCs) -------------------------
# Its shape is a file format: history written by any version must keep loading, so
# these pin the exact keys, in order, that a saved crash has
def test_a_crash_with_a_log_is_saved_with_its_analysis(sandbox, watch):
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    logs = skyrim.my_games_dir() / "SKSE" / "Crashlogs"
    logs.mkdir(parents=True)
    (logs / "crash-2026-10-29.log").write_text(LOG.read_text(encoding="utf-8"), encoding="utf-8")
    watch()
    [saved] = json.loads(paths.CRASH_HISTORY.read_text(encoding="utf-8"))
    assert list(saved) == ["time", "uptime", "kind", "analysis", "summary"]
    assert list(saved["analysis"]) == ["exception", "suspects", "log"]
    assert saved["analysis"]["suspects"][0] == {"file": "BadHooks.dll", "kind": "SKSE plugin", "score": 16,
                                                "mod": None}


def test_a_crash_known_only_to_windows_is_saved_with_its_module(sandbox, watch, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    sandbox.winapi.outputs["wevtutil"] = EVENTS
    watch()
    [saved] = json.loads(paths.CRASH_HISTORY.read_text(encoding="utf-8"))
    assert list(saved) == ["time", "uptime", "kind", "module", "code", "summary"]
    assert (saved["kind"], saved["module"], saved["code"]) == ("crash", "BadHooks.dll", "0xc0000005")


# History written by earlier versions: one entry of each shape they wrote
HISTORY = Path(__file__).parent / "fixtures" / "crash_history_v1.json"


def test_history_written_by_earlier_versions_loads_every_entry_shape(sandbox):
    paths.CRASH_HISTORY.parent.mkdir(parents=True)
    paths.CRASH_HISTORY.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")
    log_crash, windows_crash, hang = crashsquatch.load_history()
    assert log_crash.analysis.suspects[0] == crashsquatch.Suspect("BadHooks.dll", "SKSE plugin", 16, "Bad Hooks NG")
    assert (windows_crash.analysis, windows_crash.module, windows_crash.code) == (None, "BadHooks.dll", "0xc0000005")
    assert (hang.kind, hang.uptime) == ("hang", 412.5)


def test_every_entry_shape_round_trips_to_the_same_json():
    # Saving must not change how an entry looks on disk, or the file drifts with every crash
    for entry in json.loads(HISTORY.read_text(encoding="utf-8")):
        assert crashsquatch.CrashEvent.from_json(entry).to_json() == entry
        assert list(crashsquatch.CrashEvent.from_json(entry).to_json()) == list(entry)


def test_saving_a_crash_leaves_earlier_entries_untouched(sandbox):
    paths.CRASH_HISTORY.parent.mkdir(parents=True)
    paths.CRASH_HISTORY.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")
    crashsquatch.save_event(crashsquatch.CrashEvent("hang", "2026-10-30 09:00:00", 5.0, "froze"))
    saved = json.loads(paths.CRASH_HISTORY.read_text(encoding="utf-8"))
    assert saved[1:] == json.loads(HISTORY.read_text(encoding="utf-8"))


def test_a_missing_or_partial_entry_takes_defaults(sandbox):
    paths.CRASH_HISTORY.parent.mkdir(parents=True)
    paths.CRASH_HISTORY.write_text('[{"kind": "hang"}, "not an entry", {}]', encoding="utf-8")
    hang, unknown = crashsquatch.load_history()
    assert (hang.kind, hang.time, hang.uptime, hang.summary) == ("hang", "", 0, "")
    assert unknown.kind == "crash" and unknown.analysis is None


def test_a_misspelt_kind_or_state_fails_where_it_is_made():
    with pytest.raises(ValueError, match="hnag"):
        crashsquatch.CrashEvent("hnag")
    with pytest.raises(ValueError, match="runing"):
        crashsquatch.Status("runing")


def test_launching_without_a_game_folder_says_so(sandbox):
    # Watching a running game works without its folder; launching it can't
    with pytest.raises(ValueError, match="needs its folder"):
        crashsquatch.CrashSquatcher(None, print).launch()
    assert sandbox.winapi.launched == []


# ---- freezes ("Not Responding") and the watch loop's timing ------------------------------------
# On the fake clock the game started at 0 s and watching begins at 1000 s; the
# loop polls every 2 s, so a window first seen hung at T is a freeze at T + 20
PID = 1000                               # FakeWinapi's pid for the first running process
GB = 1024 ** 3


@pytest.fixture
def game(sandbox):
    """Skyrim running and responsive, using 2 GB; scripts change sandbox.winapi as the clock moves."""
    sandbox.winapi.running = [crashsquatch.GAME_EXE]
    sandbox.winapi.stats[crashsquatch.GAME_EXE] = (True, 2 * GB)
    return sandbox.winapi


def hangs(game):
    return lambda: game.hung.add(PID)


def recovers(game):
    return lambda: game.hung.discard(PID)


def exits(game):
    return lambda: game.stats.__setitem__(crashsquatch.GAME_EXE, (False, 0))


def _hangs_in(events):
    return [e for e in events if isinstance(e, crashsquatch.CrashEvent) and e.kind == "hang"]


def test_a_window_not_responding_for_20_seconds_is_recorded_as_a_freeze(game, clock, watch):
    clock.at(1010, hangs(game))
    clock.at(1100, exits(game))
    [freeze] = _hangs_in(watch())
    # First seen hung at the 1010 poll; 20 s later is the 1030 poll
    assert freeze.uptime == 1030 and freeze.summary == "Skyrim stopped responding (froze)."
    assert [e.kind for e in crashsquatch.load_history()] == ["hang"]


def test_a_window_that_recovers_within_20_seconds_is_not_a_freeze(game, clock, watch):
    clock.at(1010, hangs(game))
    clock.at(1028, recovers(game))       # hung from the 1010 poll to the 1026 poll: 16 s
    clock.at(1100, exits(game))
    assert _hangs_in(watch()) == [] and crashsquatch.load_history() == []


def test_a_long_freeze_is_reported_once(game, clock, watch):
    clock.at(1010, hangs(game))
    clock.at(1300, exits(game))          # hung for almost 5 minutes
    assert len(_hangs_in(watch())) == 1


def test_a_second_freeze_after_recovering_is_reported_again(game, clock, watch):
    clock.at(1010, hangs(game))
    clock.at(1040, recovers(game))
    clock.at(1060, hangs(game))
    clock.at(1100, exits(game))
    assert [f.uptime for f in _hangs_in(watch())] == [1030, 1080]
    assert len(crashsquatch.load_history()) == 2


def test_a_game_that_ends_frozen_is_a_freeze_then_an_exit(game, clock, watch):
    # A frozen game killed from Task Manager: the freeze is kept, the exit isn't a crash
    clock.at(1010, hangs(game))
    clock.at(1040, exits(game))
    events = [e for e in watch() if isinstance(e, crashsquatch.CrashEvent)]
    assert [e.kind for e in events] == ["hang", "exit"]


def test_while_running_the_status_carries_play_time_and_memory(game, clock, watch):
    clock.at(1005, exits(game))
    running = [e for e in watch() if isinstance(e, crashsquatch.Status) and e.state == "running"]
    assert [(s.uptime, s.ram) for s in running] == [(1000, 2 * GB), (1002, 2 * GB), (1004, 2 * GB)]


def test_a_game_that_never_starts_is_given_up_on_after_90_seconds(sandbox, clock, watch):
    events = watch()
    assert events[-1] == crashsquatch.Status("stopped", note="Skyrim never started.")
    assert clock.now == 1090


def test_attaching_when_skyrim_is_not_running_says_so(sandbox, clock, watch):
    assert watch(launched=None)[-1] == crashsquatch.Status("stopped", note="Skyrim isn't running.")


def test_a_game_that_takes_a_while_to_start_is_still_watched(sandbox, clock, watch):
    # SKSE's loader starts SkyrimSE.exe a few seconds later; the watcher keeps looking for 90 s
    clock.at(1030, lambda: sandbox.winapi.running.append(crashsquatch.GAME_EXE))
    clock.at(1030, lambda: sandbox.winapi.stats.__setitem__(crashsquatch.GAME_EXE, (True, GB)))
    clock.at(1040, exits(sandbox.winapi))
    events = watch()
    assert any(isinstance(e, crashsquatch.Status) and e.state == "running" for e in events)
    assert events[-2].kind == "exit"


def test_stopping_the_watch_ends_it_without_judging_the_session(game, clock, watcher, watch):
    clock.at(1020, watcher.stop)
    events = watch()
    assert events[-1] == crashsquatch.Status("stopped", note="Stopped watching.")
    assert not any(isinstance(e, crashsquatch.CrashEvent) for e in events)


def test_a_skyrim_together_session_launches_the_client_from_its_own_folder(sandbox):
    client = sandbox.root / "game" / "Data" / "SkyrimTogetherReborn" / "SkyrimTogether.exe"
    assert crashsquatch.CrashSquatcher(sandbox.root / "game", print, launcher=client).launch() == "SkyrimTogether.exe"
    assert sandbox.winapi.launched == [(str(client), str(client.parent), False)]
