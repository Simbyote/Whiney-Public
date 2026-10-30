"""Launches Skyrim, watches it in the background, and explains crashes.

Purpose:
    A crash report is only useful if it points at a mod. This watches the
    game process, and when it ends or freezes, finds the newest crash log
    (Crash Logger SSE, Trainwreck, .NET Script Framework) or failing that the
    Windows "Application Error" event, scores the DLLs and plugins it
    mentions, and maps them back to the Vortex mod that installed them.

Main package:
    CrashEvent: how a watched session ended ("crash" | "hang" | "exit"), with
    its Analysis (Suspects) or Windows' faulting module, and a summary.
    Crashes and hangs are kept in crash_history.json (newest 50); to_json /
    from_json keep that file's format. Status: the live waiting / running /
    stopped updates. Both reach the GUI through on_event.

Flow:
    1. CrashSquatcher.start: optionally launch through skse64_loader, find the process.
    2. Poll it: running status, and a hang after HANG_SECONDS "Not Responding".
    3. On exit: this session's crash logs (one per installed crash logger) -> analyze_logs;
       else the Windows event; else a normal exit.
    4. summarize the event in plain English, save it, send it to the GUI.
"""
import calendar
import filecmp
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal

from whiney import paths, skyrim, util, vortex, winapi

GAME_EXE = "SkyrimSE.exe"
HANG_SECONDS = 20
NOISE_MODULES = {
    "skyrimse.exe", "ntdll.dll", "kernel32.dll", "kernelbase.dll", "ucrtbase.dll", "msvcp140.dll",
    "vcruntime140.dll", "user32.dll", "win32u.dll", "d3d11.dll", "dxgi.dll", "skse64_loader.exe",
    "combase.dll", "gdi32.dll", "nvwgf2umx.dll", "amdxx64.dll", "atidxx64.dll", "igd10iumd64.dll",
}
NOISE_PLUGINS = {m.lower() for m in skyrim.OFFICIAL_MASTERS}


# ---- what the watcher reports -------------------------------------------------------
@dataclass(frozen=True)
class Suspect:
    """A file a crash log points at, and the Vortex mod it came from (None if no installed mod has it)."""
    file: str
    kind: str            # "SKSE plugin" | "plugin"
    score: int           # higher is likelier: DLLs weigh by call-stack depth, plugins by mentions
    mod: str | None


@dataclass(frozen=True)
class Analysis:
    """What a crash log says: the exception line and the suspects, most likely first."""
    exception: str | None        # "Error: EXCEPTION_ACCESS_VIOLATION at SkyrimSE.exe+0C3D4D4"
    suspects: tuple[Suspect, ...]
    log: str                     # the crash log's path (the main one, when several loggers wrote one)
    other_logs: tuple[str, ...] = ()     # the other crash loggers' logs for the same crash

    def to_json(self) -> dict:
        d: dict[str, Any] = {"exception": self.exception, "suspects": [asdict(s) for s in self.suspects],
                             "log": self.log}
        if self.other_logs:                   # only then: single-log entries keep the shape they always had
            d["other_logs"] = list(self.other_logs)
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Analysis":
        suspects = tuple(Suspect(s.get("file", ""), s.get("kind", ""), s.get("score", 0), s.get("mod"))
                         for s in d.get("suspects") or [])
        return cls(d.get("exception"), suspects, d.get("log", ""), tuple(d.get("other_logs") or ()))


KINDS = ("crash", "hang", "exit")


@dataclass(frozen=True)
class CrashEvent:
    """How a watched session ended. A crash has an analysis (from a crash log) or a module (from Windows) or neither."""
    kind: Literal["crash", "hang", "exit"]
    time: str = ""                   # local, "%Y-%m-%d %H:%M:%S"
    uptime: float = 0                # seconds the game ran
    summary: str = ""
    analysis: Analysis | None = None
    module: str | None = None        # Windows' faulting module, when no crash log was written
    code: str | None = None          # Windows' exception code, e.g. "0xc0000005"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"CrashEvent kind must be one of {KINDS}, not {self.kind!r}")

    def to_json(self) -> dict:
        """The crash_history.json entry, in the exact shape (keys and order) earlier versions wrote."""
        if self.kind == "hang":
            d = {"kind": self.kind, "time": self.time, "uptime": self.uptime}
        else:
            d = {"time": self.time, "uptime": self.uptime, "kind": self.kind}
            if self.analysis:
                d["analysis"] = self.analysis.to_json()
            elif self.kind == "crash":
                d.update(module=self.module, code=self.code)
        d["summary"] = self.summary
        return d

    @classmethod
    def from_json(cls, d: dict) -> "CrashEvent":
        """Reads any entry a version of the app wrote; missing fields take their defaults."""
        analysis = Analysis.from_json(d["analysis"]) if d.get("analysis") else None
        return cls(d.get("kind", "crash"), d.get("time", ""), d.get("uptime") or 0, d.get("summary") or "",
                   analysis, d.get("module"), d.get("code"))


STATES = ("waiting", "running", "stopped")


@dataclass(frozen=True)
class Status:
    """A live update while watching: waiting for the game, running (with uptime and RAM), or stopped."""
    state: Literal["waiting", "running", "stopped"]
    uptime: float = 0        # seconds, while running
    ram: int = 0             # bytes, while running
    note: str | None = None  # why it stopped, when there's something to say

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"Status state must be one of {STATES}, not {self.state!r}")


# ---- crash log discovery ----------------------------------------------------------
def crash_log_dirs(game: Path | str | None) -> list[Path]:
    dirs = [skyrim.my_games_dir() / "SKSE", skyrim.my_games_dir() / "SKSE" / "Crashlogs"]
    if game:
        dirs.append(Path(game) / "Data" / "NetScriptFramework" / "Crash")
    return dirs


def new_crash_logs(game: Path | str | None, since: float) -> list[Path]:
    """Crash logs written since the game started (`since`, epoch seconds; 2 s of slack), newest first.

    Older logs belong to earlier sessions: a crash without a log of its own
    must not be explained by the last one that had a log.
    """
    found = []
    for d in crash_log_dirs(game):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            name = f.name.lower()
            if f.is_file() and (name.startswith("crash") and name.endswith((".log", ".txt"))):
                try:
                    if f.stat().st_mtime >= since - 2:
                        found.append(f)
                except OSError:
                    pass
    return sorted(found, key=lambda f: f.stat().st_mtime, reverse=True)


def windows_crash_event(since: float) -> dict[str, str | None] | None:
    """Most recent Application Error event for SkyrimSE.exe after `since`, or None."""
    if not winapi.IS_WINDOWS:
        return None
    out = winapi.run(
        ["wevtutil", "qe", "Application", "/q:*[System[(EventID=1000)]]", "/c:10", "/rd:true", "/f:text"],
        timeout=15)
    if out is None:
        return None
    return parse_crash_events(out, since)


def parse_crash_events(out: str, since: float) -> dict[str, str | None] | None:
    """The newest SkyrimSE.exe Application Error in wevtutil's text output, if at or after `since`.

    Inputs:
        out: `wevtutil qe Application ... /f:text` output, newest event first.
        since: Epoch seconds the game started; events more than 5 s older are ignored.
            Dates ending in Z are UTC (what wevtutil writes); others are local time.

    Outputs:
        {"module": faulting module or None, "code": exception code or None}, or None.
    """
    for block in out.split("Event[")[1:]:
        if GAME_EXE.lower() not in block.lower():
            continue
        m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z?)", block)
        if m:
            try:
                parsed = time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
                # wevtutil writes UTC with a trailing Z; read as local time it would shift by the
                # UTC offset, letting an earlier session's crash pass (west of UTC) or a fresh one fail
                ts = calendar.timegm(parsed) if m.group(2) else time.mktime(parsed)
                if ts < since - 5:
                    continue
            except ValueError:
                pass
        mod = re.search(r"Faulting module name:\s*([^\s,]+)", block)
        code = re.search(r"Exception code:\s*(0x[0-9a-fA-F]+)", block)
        return {"module": mod.group(1) if mod else None, "code": code.group(1) if code else None}
    return None


# ---- crash log analysis ----------------------------------------------------------
# staging folder -> {file name: [(mod folder, path inside it), ...]}
_mod_index_cache: dict[Path, dict[str, list[tuple[str, str]]]] = {}


def file_owner_index() -> dict[str, list[tuple[str, str]]]:
    """lowercase file name -> every (mod folder, path inside it) shipping it, for plugins and SKSE DLLs
    in Vortex's staging. Several entries when mods ship the same file name; file_owner picks between them."""
    staging = vortex.staging_dir()
    if staging in _mod_index_cache:
        return _mod_index_cache[staging]
    idx: dict[str, list[tuple[str, str]]] = {}
    if staging.is_dir():
        for mod in sorted(staging.iterdir()):
            if not mod.is_dir() or mod.name.startswith("__"):
                continue
            found = {p for pattern in ("*.es[pml]", "SKSE/Plugins/*.dll", "skse/plugins/*.dll")
                     for p in mod.glob(pattern)}          # a set: the two SKSE patterns match the same files
            for p in sorted(found):
                idx.setdefault(p.name.lower(), []).append((mod.name, p.relative_to(mod).as_posix()))
    _mod_index_cache[staging] = idx
    return idx


def file_owner(name: str, game: Path | str | None = None) -> str | None:
    """The mod a plugin or DLL came from, as its readable name; None if no mod in Vortex has it.

    When several mods ship a file of that name, Vortex deployed only one of
    them into the game, and that is the one the game loaded: the copy in
    Data that is the same file (Vortex's hard link) or has the same bytes
    wins. If that can't be told (no game folder, nothing deployed, identical
    copies), every candidate is named: "Mod A or Mod B".
    """
    candidates = file_owner_index().get(name.lower(), [])
    if len(candidates) > 1 and game:
        staging = vortex.staging_dir()
        deployed = [(mod, rel) for mod, rel in candidates
                    if _same_file(staging / mod / rel, Path(game) / "Data" / rel)]
        if len(deployed) == 1:
            candidates = deployed
    names = dict.fromkeys(vortex.nice_mod_name(mod) for mod, _ in candidates)   # two versions of one mod: once
    return " or ".join(names) or None


def _same_file(staged: Path, deployed: Path) -> bool:
    """True if `deployed` is `staged` (a hard link) or a byte-for-byte copy of it."""
    try:
        if os.path.samefile(staged, deployed):
            return True
        return staged.stat().st_size == deployed.stat().st_size and filecmp.cmp(staged, deployed, shallow=False)
    except OSError:
        return False


def analyze_log(path: str | Path, game: Path | str | None = None) -> Analysis:
    """Exception and suspects from a crash log. `game` lets file_owner tell apart mods sharing a file name."""
    text = Path(path).read_text(encoding="locale", errors="ignore")
    lines = text.splitlines()
    exception = None
    for l in lines[:40]:
        if "exception" in l.lower():
            m = re.search(r'"?(EXCEPTION_\w+)"?\s+at\s+\S+\s+(\S+)', l)
            native = re.search(r"native exception occurred at \S+ \(([^)]+)\)", l, re.I)   # .NET Script Framework
            exception = (f"Error: {m.group(1)} at {m.group(2)}" if m
                         else f"Error: native exception at {native.group(1)}" if native
                         else l.split("\t")[0].strip())
            break

    # call stack modules, top frames weigh most
    modules: dict[str, int] = {}
    in_stack = False
    rank = 0
    for line in lines:
        upper = line.strip().upper()
        if "CALL STACK" in upper:
            in_stack, rank = True, 0
            continue
        if in_stack:
            if not line.strip() or (upper.endswith(":") and "CALL STACK" not in upper):
                in_stack = False
                continue
            # "BadHooks.dll+0001234" (Crash Logger, Trainwreck) or "(BadHooks.dll+1234)" (.NET Script Framework)
            m = re.search(r"([^\s\[\]\\/()]+\.(?:dll|exe))\+", line, re.I)
            if m:
                name = m.group(1).strip()
                if name.lower() not in NOISE_MODULES:
                    modules[name] = modules.get(name, 0) + max(10 - rank, 1)
                rank += 1

    # plugins mentioned in registers / stack / relevant objects
    plugins: dict[str, int] = {}
    for m in re.finditer(r'"([^"\r\n]+?\.(?:esp|esm|esl))"', text, re.I):
        n = m.group(1)
        if n.lower() not in NOISE_PLUGINS:
            plugins[n] = plugins.get(n, 0) + 1
    for m in re.finditer(r"Modified by:\s*(.+)", text):
        for n in [x.strip() for x in m.group(1).split("->")]:
            if n.lower().endswith((".esp", ".esm", ".esl")) and n.lower() not in NOISE_PLUGINS:
                plugins[n] = plugins.get(n, 0) + 2      # last overriding plugins are strong hints

    suspects = []
    for name, score in sorted(modules.items(), key=lambda kv: -kv[1])[:4]:
        suspects.append(Suspect(name, "SKSE plugin", score, file_owner(name, game)))
    for name, score in sorted(plugins.items(), key=lambda kv: -kv[1])[:4]:
        suspects.append(Suspect(name, "plugin", score, file_owner(name, game)))
    suspects.sort(key=lambda s: -s.score)
    return Analysis(exception, tuple(suspects[:6]), str(path))


def analyze_logs(logs: Sequence[str | Path], game: Path | str | None = None) -> Analysis:
    """One analysis from every crash log written for a crash (several crash loggers installed).

    Each log is analyzed on its own, then suspects are merged by file: a file
    several loggers point at adds up its scores, so agreement ranks it higher.
    The main log is the first (newest) one that names a suspect; the exception
    line comes from the first log that has one.

    Inputs:
        logs: Crash log paths, newest first (new_crash_logs); at least one.
    """
    analyses = [analyze_log(p, game) for p in logs]
    if len(analyses) == 1:
        return analyses[0]
    merged: dict[tuple[str, str], Suspect] = {}
    for a in analyses:
        for sus in a.suspects:
            key = (sus.file.lower(), sus.kind)
            seen = merged.get(key)
            merged[key] = replace(seen, score=seen.score + sus.score) if seen else sus
    main = next((a for a in analyses if a.suspects), analyses[0])
    exception = next((a.exception for a in analyses if a.exception), None)
    suspects = tuple(sorted(merged.values(), key=lambda sus: -sus.score)[:6])
    return Analysis(exception, suspects, main.log, tuple(a.log for a in analyses if a is not main))


def summarize(event: CrashEvent, game: Path | str | None = None) -> str:
    """Plain-English summary for a crash event. `game` resolves the owner of Windows' faulting module."""
    if event.kind == "hang":
        return "Skyrim stopped responding (froze)."
    if event.kind == "exit":
        return "Skyrim closed normally."
    a = event.analysis
    parts = []
    sus = a.suspects if a else ()
    if sus:
        top = sus[0]
        who = top.mod or top.file
        parts.append(f"Most likely involved: {who} ({top.file})")
        others = [s.mod or s.file for s in sus[1:4]]
        if others:
            parts.append("Also mentioned: " + ", ".join(dict.fromkeys(others)))
        if a and a.other_logs:
            parts.append(f"Combined from {1 + len(a.other_logs)} crash logs (more than one crash logger "
                         "is installed).")
    elif event.module:
        parts.append(f"Windows says it crashed in: {event.module}")
        owner = file_owner(event.module, game)
        if owner:
            parts.append(f"That file comes from the mod: {owner}")
    else:
        parts.append("No crash log was written, so the cause is unknown. Installing a crash logger "
                     "(see Doctor) makes the next one explainable.")
    if a and a.exception:
        parts.append(a.exception)
    return "\n".join(parts)


def load_history() -> list[CrashEvent]:
    """Saved crashes and hangs, newest first. Entries that aren't objects are skipped."""
    raw = util.read_json(paths.CRASH_HISTORY, []) or []
    return [CrashEvent.from_json(e) for e in raw if isinstance(e, dict)]


def save_event(event: CrashEvent) -> None:
    """Add an event to the front of crash_history.json; earlier entries are kept exactly as written.

    Side effects: Rewrites crash_history.json, keeping the newest 50.
    """
    hist = util.read_json(paths.CRASH_HISTORY, []) or []
    hist.insert(0, event.to_json())
    util.write_json(paths.CRASH_HISTORY, hist[:50])


# ---- the watcher ---------------------------------------------------------------------
class CrashSquatcher:
    """Launches (optionally) and watches SkyrimSE.exe on a background thread.

    on_event(event) is called from the watcher thread with a Status while
    waiting and running, and a CrashEvent when the session ends (crashes and
    hangs are also saved to crash history).
    """

    def __init__(self, game: Path | str | None, on_event: Callable[[Status | CrashEvent], object],
                 launcher: Path | str | None = None):
        """game is None when attaching to a running Skyrim whose folder wasn't found; launching needs it.

        launcher: the program launch() starts, e.g. Skyrim Together's SkyrimTogether.exe. By
            default it's skse64_loader.exe, or SkyrimSE.exe without SKSE. Either way the
            watcher then follows SkyrimSE.exe.
        """
        self.launcher = launcher
        self.game, self.on_event = game, on_event
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()

    @property
    def active(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def launch(self) -> str:
        if self.launcher is not None:
            exe = Path(self.launcher)
        else:
            if self.game is None:
                raise ValueError("launching Skyrim needs its folder; play() checks for it first")
            game = Path(self.game)
            loader = game / "skse64_loader.exe"
            exe = loader if loader.exists() else game / GAME_EXE
        # From its own folder: the game's for SKSE, the mod's for Skyrim Together
        winapi.launch(exe, exe.parent)
        return exe.name

    def start(self, launch: bool = True) -> None:
        if self.active:
            return
        self.stop_flag.clear()
        launched = self.launch() if launch else None
        self.thread = threading.Thread(target=self._run, args=(time.time(), launched), daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def _find_proc(self) -> winapi.Proc | None:
        return winapi.find_process(GAME_EXE)

    @staticmethod
    def _game_start(proc: winapi.Proc, started: float) -> float:
        """When the game process started; when Windows won't say (access denied: psutil gives None,
        e.g. a game run as administrator), when watching started."""
        return proc.info.get("create_time") or started

    def _run(self, started: float, launched: str | None) -> None:
        self.on_event(Status("waiting"))
        proc = None
        deadline = time.time() + 90
        while not self.stop_flag.is_set() and time.time() < deadline:
            proc = self._find_proc()
            if proc:
                break
            time.sleep(1)
        if not proc:
            self.on_event(Status("stopped", note="Skyrim never started." if launched else "Skyrim isn't running."))
            return

        hung_since, hang_reported = None, False
        while not self.stop_flag.is_set():
            alive, ram = winapi.process_stats(proc)
            if not alive:
                break
            uptime = time.time() - self._game_start(proc, started)
            self.on_event(Status("running", uptime=uptime, ram=ram))

            if winapi.window_hung(proc.pid):
                hung_since = hung_since or time.time()
                if not hang_reported and time.time() - hung_since >= HANG_SECONDS:
                    hang_reported = True
                    ev = CrashEvent("hang", time.strftime("%Y-%m-%d %H:%M:%S"), uptime)
                    ev = replace(ev, summary=summarize(ev))
                    save_event(ev)
                    self.on_event(ev)
            else:
                hung_since, hang_reported = None, False
            time.sleep(2)

        if self.stop_flag.is_set():
            self.on_event(Status("stopped", note="Stopped watching."))
            return

        ended = time.time()
        game_start = self._game_start(proc, started)
        uptime = ended - game_start
        time.sleep(3)                                    # give crash loggers a moment to finish writing
        logs = new_crash_logs(self.game, game_start)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if logs:
            ev = CrashEvent("crash", now, uptime, analysis=analyze_logs(logs, self.game))
        else:
            win = windows_crash_event(game_start)
            if win:
                ev = CrashEvent("crash", now, uptime, module=win.get("module"), code=win.get("code"))
            else:
                ev = CrashEvent("exit", now, uptime)
        ev = replace(ev, summary=summarize(ev, self.game))
        if ev.kind == "crash":
            save_event(ev)
        self.on_event(ev)
        self.on_event(Status("stopped"))
