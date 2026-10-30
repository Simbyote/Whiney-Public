"""Skyrim Together Reborn server helpers for whoever hosts multiplayer.

Purpose:
    Hosting fails for reasons players can't see: the server isn't deployed,
    the firewall blocks it, or the ISP's carrier-grade NAT makes port
    forwarding impossible. This finds and runs the server and gathers what
    the Host tab needs to explain those cases.

Main package:
    None; plain values: the server exe path, its UDP port, local and public
    IPs, and whether the firewall rule and CGNAT apply.

Flow:
    1. Find the server: deployed Data folder first, then Vortex staging.
    2. Read its port from STServer.ini.
    3. Start / stop it; look up the addresses to share.
    4. Check and add the Windows firewall rule (UAC prompt).
"""
import re
import socket
from pathlib import Path

from whiney import vortex, winapi

SERVER_EXE = "SkyrimTogetherServer.exe"
CLIENT_EXE = "SkyrimTogether.exe"          # the multiplayer launcher players start the game with
TOGETHER_DIR = "SkyrimTogetherReborn"     # the mod's folder inside Data
DEFAULT_PORT = 10578
RULE_NAME = "Skyrim Together Server"


def find_client(game: Path | str | None) -> Path | None:
    """The Skyrim Together launcher in the deployed Data folder, or None.

    Only the deployed copy counts: the client is a mod, and a copy that's only
    in Vortex's staging folder isn't active in the game.
    """
    if not game:
        return None
    exe = Path(game) / "Data" / TOGETHER_DIR / CLIENT_EXE
    return exe if exe.exists() else None


def find_server(game: str | Path | None) -> Path | None:
    """Look in the deployed Data folder first, then Vortex's staging folder."""
    places = []
    if game:
        places.append(Path(game) / "Data" / TOGETHER_DIR)
    staging = vortex.staging_dir()
    if staging.is_dir():
        places += [m / TOGETHER_DIR for m in staging.iterdir()
                   if m.is_dir() and "together" in m.name.lower()]
    for p in places:
        exe = p / SERVER_EXE
        if exe.exists():
            return exe
    return None


def server_port(server_exe: Path | None) -> int:
    """uPort from the server config, else the default."""
    if server_exe:
        for cfg in (server_exe.parent / "config" / "STServer.ini", server_exe.parent / "STServer.ini"):
            try:
                m = re.search(r"^\s*uPort\s*=\s*(\d+)", cfg.read_text(encoding="locale", errors="ignore"), re.M)
                if m:
                    return int(m.group(1))
            except OSError:
                pass
    return DEFAULT_PORT


def server_running() -> bool:
    return winapi.process_running(SERVER_EXE)


def start_server(server_exe: Path) -> None:
    # Its own console window, so the host sees the server running and can close it
    winapi.launch(server_exe, server_exe.parent, new_console=True)


def stop_server() -> bool:
    return winapi.terminate_all(SERVER_EXE)


def local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))                       # no packets sent, just picks the route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def public_ip() -> str | None:
    import requests
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            ip = requests.get(url, timeout=5).text.strip()
            if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
                return ip
        except Exception:
            continue
    return None


def is_cgnat(ip: str) -> bool:
    """100.64.0.0/10 on your router's WAN side means port forwarding can't work."""
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
        return a == 100 and 64 <= b <= 127
    except Exception:
        return False


def firewall_rule_exists(port: int) -> bool | None:
    if not winapi.IS_WINDOWS:
        return None
    out = winapi.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"])
    if out is None:
        return None
    return str(port) in out


def add_firewall_rule(port: int) -> bool:
    """Opens a UAC prompt; Windows needs admin rights to add the rule."""
    if not winapi.IS_WINDOWS:
        return False
    args = (f'advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow '
            f'protocol=UDP localport={port}')
    return winapi.run_as_admin("netsh", args)
