"""
test_host.py  --  src/whiney/host.py

The Host tab tells the host which port to forward and whether forwarding can
work at all. These pin the port read from the server config and the CGNAT
check, starting and stopping the server, the firewall rule check and add,
and finding the client launcher, on a fake winapi. IP lookups use the network and are not covered.

--software  Config files in tmp_path. No server, no network.
"""
import pytest

from builders import make_game, make_mod
from whiney import host, winapi

pytestmark = pytest.mark.software


def test_server_port_is_read_from_the_config_folder(tmp_path):
    exe = tmp_path / host.SERVER_EXE
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "STServer.ini").write_text("[GameServer]\nuPort = 12345\n", encoding="utf-8")
    assert host.server_port(exe) == 12345


def test_server_port_defaults_without_a_config(tmp_path):
    assert host.server_port(tmp_path / host.SERVER_EXE) == host.DEFAULT_PORT
    assert host.server_port(None) == host.DEFAULT_PORT


@pytest.mark.parametrize("ip, cgnat", [
    ("100.64.0.1", True),          # 100.64.0.0/10 (RFC 6598): carrier-grade NAT
    ("100.127.255.254", True),
    ("100.128.0.1", False),
    ("100.63.255.255", False),
    ("203.0.113.7", False),
    ("not an ip", False),
])
def test_cgnat_is_exactly_100_64_0_0_slash_10(ip, cgnat):
    assert host.is_cgnat(ip) is cgnat


# ---- the server process and the firewall (fake winapi) ------------------------------------
def test_the_server_starts_in_its_own_console_from_its_folder(sandbox, tmp_path):
    exe = tmp_path / "SkyrimTogetherReborn" / host.SERVER_EXE
    host.start_server(exe)
    assert sandbox.winapi.launched == [(str(exe), str(exe.parent), True)]


def test_stopping_the_server_terminates_it_by_name(sandbox):
    sandbox.winapi.running = [host.SERVER_EXE]
    assert host.server_running()
    assert host.stop_server() and not host.server_running()


@pytest.mark.parametrize("netsh_output, exists", [
    # `netsh advfirewall firewall show rule` lists LocalPort for a rule that exists
    ("Rule Name:   Skyrim Together Server\nProtocol:    UDP\nLocalPort:   10578\nAction:      Allow\n", True),
    ("Rule Name:   Skyrim Together Server\nProtocol:    UDP\nLocalPort:   10600\n", False),       # other port
    ("No rules match the specified criteria.\n", False),
])
def test_the_firewall_rule_is_found_by_its_port(sandbox, monkeypatch, netsh_output, exists):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    sandbox.winapi.outputs["netsh"] = netsh_output
    assert host.firewall_rule_exists(10578) is exists


def test_the_firewall_rule_is_unknown_when_netsh_cannot_run(sandbox, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    assert host.firewall_rule_exists(10578) is None


def test_adding_the_rule_asks_for_admin_with_a_udp_rule_for_the_port(sandbox, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", True)
    assert host.add_firewall_rule(10578)
    [(exe, args)] = sandbox.winapi.elevated
    assert exe == "netsh" and "protocol=UDP localport=10578" in args and 'name="Skyrim Together Server"' in args


def test_firewall_calls_are_skipped_off_windows(sandbox, monkeypatch):
    monkeypatch.setattr(winapi, "IS_WINDOWS", False)
    assert host.firewall_rule_exists(10578) is None and host.add_firewall_rule(10578) is False
    assert sandbox.winapi.commands == [] and sandbox.winapi.elevated == []


def test_software_tests_cannot_reach_the_network(sandbox):
    # public_ip asks three web services; in a software test each attempt is blocked
    with pytest.raises(AssertionError, match="network"):
        import socket
        socket.create_connection(("example.com", 80), timeout=1)


# ---- the Skyrim Together client (Play Skyrim Together) ----------------------------------------
def test_the_client_is_found_in_the_deployed_data_folder(sandbox):
    game = make_game(sandbox.root / "game")
    exe = game / "Data" / host.TOGETHER_DIR / host.CLIENT_EXE
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert host.find_client(game) == exe


def test_a_client_only_in_vortex_staging_is_not_used(sandbox):
    # Not deployed means not active in the game: multiplayer stays off until it's deployed
    game = make_game(sandbox.root / "game")
    make_mod(sandbox.staging, "Skyrim Together Reborn-69993-1-6-1700000000",
             {f"{host.TOGETHER_DIR}/{host.CLIENT_EXE}": b"MZ"})
    assert host.find_client(game) is None
    assert host.find_client(None) is None
