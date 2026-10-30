"""The one module that talks to Windows: registry, Win32 calls, processes, the shell.

Purpose:
    Everything else in the app decides; this module only asks Windows. Keeping
    the OS behind small functions with plain inputs and outputs means the
    decisions around them (which registry key wins, how a crash event is
    parsed) are ordinary code the software tests can run against a fake, and
    the test sandbox can replace this whole module so no software test reaches
    the real OS. tests/test_repo.py fails if any other module imports winreg,
    ctypes, subprocess, psutil or webbrowser. Network I/O is not here: host
    and installer use requests, socket and gdown directly.

Main package:
    None; plain values. Registry reads return the value or None (missing key
    or value, or not Windows); a process is a Proc handle from find_process.

Flow:
    Independent primitives, grouped: platform flags, registry, files and
    folders, processes, windows, the shell.
"""
import os
import subprocess
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psutil

IS_WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0     # CREATE_NO_WINDOW: hide helper consoles
CREATE_NEW_CONSOLE = 0x00000010                  # give a launched program its own visible console

# Short hive names callers use, mapped to winreg's constants
HIVES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE", "HKCR": "HKEY_CLASSES_ROOT"}


# ---- registry ------------------------------------------------------------------------
# Any: values can be str, int, bytes or list; every one this app reads is a REG_SZ string
def reg_value(hive: str, key: str, name: str = "") -> Any:
    """A registry value as stored (usually a str), or None if the key or value is missing.

    Inputs:
        hive: "HKCU", "HKLM" or "HKCR".
        name: The value's name; "" is the key's default value.
    """
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, HIVES[hive]), key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except (OSError, ImportError):
        return None


def reg_subkeys(hive: str, key: str) -> list[str]:
    """Names of a registry key's direct subkeys; [] if the key is missing. Unreadable entries are skipped."""
    try:
        import winreg
        root = winreg.OpenKey(getattr(winreg, HIVES[hive]), key)
    except (OSError, ImportError):
        return []
    names = []
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                names.append(winreg.EnumKey(root, i))
            except OSError:
                continue
    return names


# ---- files and folders -------------------------------------------------------------------
def file_version(path: str | Path) -> str | None:
    """Read a Windows exe/dll version resource, e.g. '1.6.1170.0'."""
    if not IS_WINDOWS or not Path(path).exists():
        return None
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
        ms, ls = info[2], info[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None


def documents_folder() -> Path | None:
    """The shell's real Documents folder (follows OneDrive redirection); None if not on Windows or unknown."""
    if IS_WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL (5): the user's Documents
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
                return Path(buf.value)
        except Exception:
            pass
    return None


def system_folder() -> Path | None:
    """Windows' System32 folder, as Windows reports it; None if not on Windows or unknown."""
    if IS_WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260):
                return Path(buf.value)
        except Exception:
            pass
    return None


# ---- processes --------------------------------------------------------------------------
@dataclass
class Proc:
    """A running process found by name. info holds name, pid and create_time (None if access was denied)."""
    pid: int
    info: dict
    handle: "psutil.Process" = field(repr=False)   # only this module touches it


def process_running(name: str) -> bool:
    name = name.lower()
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == name:
                return True
        return False
    except ImportError:
        pass
    if not IS_WINDOWS:
        return False
    try:
        out = subprocess.run([system_tool("tasklist"), "/FI", f"IMAGENAME eq {name}"],
                             capture_output=True, text=True, creationflags=NO_WINDOW, encoding="locale").stdout
        return name in out.lower()
    except FileNotFoundError:
        return False


def find_process(name: str) -> Proc | None:
    """The first running process with this exe name (case-insensitive), or None."""
    import psutil
    for p in psutil.process_iter(["name", "pid", "create_time"]):
        if (p.info.get("name") or "").lower() == name.lower():
            return Proc(p.pid, p.info, p)
    return None


def process_stats(proc: Proc) -> tuple[bool, int]:
    """(still running, resident memory in bytes). A zombie or vanished process is (False, 0)."""
    import psutil
    try:
        alive = proc.handle.is_running() and proc.handle.status() != psutil.STATUS_ZOMBIE
        ram = proc.handle.memory_info().rss if alive else 0
    except psutil.Error:
        alive, ram = False, 0
    return alive, ram


def terminate_all(name: str) -> bool:
    """Ask every process with this exe name to exit. False if the process list couldn't be read.

    Side effects: Sends terminate to matching processes.
    """
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == name.lower():
                p.terminate()
        return True
    except Exception:
        return False


def launch(exe: str | Path, cwd: str | Path, new_console: bool = False) -> None:
    """Start a program and return immediately.

    Inputs:
        new_console: Give it its own visible console window (Windows only); a
            console program such as the Skyrim Together server needs one to be seen.

    Side effects: Starts a process.
    """
    flags = CREATE_NEW_CONSOLE if new_console and IS_WINDOWS else 0
    subprocess.Popen([str(exe)], cwd=str(cwd), creationflags=flags)


def system_tool(name: str) -> str:
    """A Windows tool's full path in System32 ("netsh" -> C:\\Windows\\System32\\netsh.exe).

    Windows looks for a bare name in the app's own folder and the current
    folder before System32. Players run the exe from Downloads, where a
    planted netsh.exe would run instead of the real one (elevated, through
    run_as_admin). A name with a folder, and any name off Windows, is returned as is.
    """
    folder = system_folder() if IS_WINDOWS and not os.path.dirname(name) else None
    if folder is None:
        return name
    return str(folder / (name if name.lower().endswith(".exe") else name + ".exe"))


def run(cmd: list[str], timeout: float | None = None) -> str | None:
    """Run a console command with no visible window and return its output, or None if it couldn't run.

    Inputs:
        cmd: A bare program name is a Windows tool, run from System32 (system_tool).
        timeout: Seconds before giving up (None = wait as long as it takes).

    Outputs:
        stdout decoded in the Windows locale encoding, as the tools write it.
    """
    try:
        return subprocess.run([system_tool(cmd[0]), *cmd[1:]], capture_output=True, text=True, timeout=timeout,
                              creationflags=NO_WINDOW, encoding="locale").stdout
    except Exception:
        return None


# ---- windows ------------------------------------------------------------------------------
def window_hung(pid: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hung = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd: int, _: int) -> bool:
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid and user32.IsWindowVisible(hwnd):
                hung.append(bool(user32.IsHungAppWindow(hwnd)))
            return True
        user32.EnumWindows(cb, 0)
        return any(hung)
    except Exception:
        return False


# ---- the shell ----------------------------------------------------------------------------
def open_path(path: str | Path) -> None:
    path = str(path)
    if IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def open_url(url: str) -> None:
    """Open a web page in the default browser. Side effects: starts or focuses the browser."""
    webbrowser.open(url)


def run_as_admin(exe: str, args: str) -> bool:
    """Start a program elevated, through the UAC prompt. True if it started (the user said yes).

    Inputs:
        exe: A bare name is a Windows tool, run from System32 (system_tool).

    Side effects: Shows the UAC prompt and starts the program with admin rights.
    """
    if not IS_WINDOWS:
        return False
    import ctypes
    # ShellExecuteW returns a value > 32 on success
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", system_tool(exe), args, None, 0) > 32
