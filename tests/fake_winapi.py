"""
A stand-in for whiney.winapi in software tests: a registry held in a dict, a
list of running processes, canned command output, and a record of every side
effect (launches, opened paths and URLs, elevation requests). The sandbox
installs one per test (sandbox.winapi), so tests describe the OS state they
need and check what the app asked the OS to do.
"""
from pathlib import Path

from whiney.winapi import Proc


class FakeWinapi:
    """Same functions as whiney.winapi; state set by the test, side effects recorded."""

    def __init__(self, documents: Path):
        self.documents = documents
        self._registry: dict[tuple[str, str], tuple[str, dict]] = {}   # (hive, key lowercased) -> (key, values)
        self.versions: dict[str, str] = {}       # str(path) -> "1.6.1170.0"
        self.running: list[str] = []             # exe names
        self.stats: dict[str, tuple[bool, int]] = {}   # exe name -> (alive, ram) for process_stats
        self.create_times: dict[str, float | None] = {}   # exe name -> start time (epoch; None: access denied)
        self.hung: set[int] = set()              # pids whose window is "Not Responding"
        self.outputs: dict[str, str] = {}        # command name (cmd[0]) -> its stdout
        self.commands: list[list[str]] = []
        self.launched: list[tuple[str, str, bool]] = []
        self.opened: list[str] = []
        self.urls: list[str] = []
        self.elevated: list[tuple[str, str]] = []
        self.terminated: list[str] = []
        self.allow_elevation = True

    # ---- set-up helpers for tests ----
    def set_reg(self, hive: str, key: str, name: str, value) -> None:
        """Create the key if needed and set one value ("" is the default value)."""
        _, values = self._registry.setdefault((hive, key.lower()), (key, {}))
        values[name] = value

    # ---- winapi's functions ----
    def reg_value(self, hive, key, name=""):
        return self._registry.get((hive, key.lower()), ("", {}))[1].get(name)

    def reg_subkeys(self, hive, key):
        prefix = key.lower() + "\\"
        names = []
        for (h, low), (orig, _) in self._registry.items():
            if h == hive and low.startswith(prefix):
                child = orig[len(prefix):].split("\\")[0]
                if child not in names:
                    names.append(child)
        return names

    def file_version(self, path):
        return self.versions.get(str(path))

    def documents_folder(self):
        return self.documents

    def process_running(self, name):
        return name.lower() in (n.lower() for n in self.running)

    def find_process(self, name):
        for i, n in enumerate(self.running):
            if n.lower() == name.lower():
                return Proc(1000 + i, {"name": n, "pid": 1000 + i, "create_time": self.create_times.get(n, 0.0)}, None)
        return None

    def process_stats(self, proc):
        return self.stats.get(proc.info["name"], (False, 0))

    def terminate_all(self, name):
        self.terminated.append(name)
        self.running = [n for n in self.running if n.lower() != name.lower()]
        return True

    def launch(self, exe, cwd, new_console=False):
        self.launched.append((str(exe), str(cwd), new_console))

    def system_folder(self):
        return None

    def system_tool(self, name):
        return name

    def run(self, cmd, timeout=None):
        self.commands.append(list(cmd))
        return self.outputs.get(cmd[0])

    def window_hung(self, pid):
        return pid in self.hung

    def open_path(self, path):
        self.opened.append(str(path))

    def open_url(self, url):
        self.urls.append(url)

    def run_as_admin(self, exe, args):
        self.elevated.append((exe, args))
        return self.allow_elevation
