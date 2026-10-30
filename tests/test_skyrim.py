"""
test_skyrim.py  --  src/whiney/skyrim.py

skyrim reads the player's install: where the game is, what SKSE runtime
and Creation Club content it has, and the active load order with its sync
code. These pin each reader on hand-built folders and files.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
import re
from pathlib import Path

import pytest

from builders import make_game, write_plugins_txt
from whiney import config, skyrim

pytestmark = pytest.mark.software


def test_read_plugins_txt_keeps_file_order_and_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "plugins.txt"
    p.write_text("# header\n\n*A.esp\nB.esp\n  *C.esm  \n", encoding="utf-8")
    assert skyrim.read_plugins_txt(p) == [("A.esp", True), ("B.esp", False), ("C.esm", True)]
    assert skyrim.enabled_plugins(p) == ["A.esp", "C.esm"]


def test_read_plugins_txt_of_a_missing_file_is_empty(tmp_path):
    assert skyrim.read_plugins_txt(tmp_path / "nope.txt") == []


def test_sync_code_is_two_groups_of_four_hex(tmp_path):
    p = write_plugins_txt(tmp_path / "plugins.txt", enabled=["A.esp", "B.esp"])
    assert re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}", skyrim.sync_code(p))


def test_sync_code_ignores_case_and_disabled_plugins_but_not_order(tmp_path):
    # Players compare codes before multiplayer: same enabled list in the same
    # order must match, and any reorder must not, or desyncs go unnoticed
    a = write_plugins_txt(tmp_path / "a.txt", enabled=["A.esp", "B.esp"])
    b = write_plugins_txt(tmp_path / "b.txt", enabled=["a.ESP", "b.esp"], disabled=["Off.esp"])
    c = write_plugins_txt(tmp_path / "c.txt", enabled=["B.esp", "A.esp"])
    assert skyrim.sync_code(a) == skyrim.sync_code(b)
    assert skyrim.sync_code(a) != skyrim.sync_code(c)


def test_sync_code_is_none_with_nothing_enabled(tmp_path):
    assert skyrim.sync_code(write_plugins_txt(tmp_path / "p.txt", disabled=["A.esp"])) is None


def test_is_game_dir_needs_skyrimse_exe(tmp_path):
    assert not skyrim.is_game_dir(tmp_path)
    assert not skyrim.is_game_dir(None)
    assert skyrim.is_game_dir(make_game(tmp_path / "game"))


def test_find_game_dir_prefers_the_saved_choice(sandbox):
    game = make_game(sandbox.root / "game")
    config.save_setting("game_dir", str(game))
    assert skyrim.find_game_dir() == game


def test_find_game_dir_searches_steam_libraries(sandbox, monkeypatch):
    lib = sandbox.root / "SteamLibrary"
    game = make_game(lib / "steamapps" / "common" / "Skyrim Special Edition")
    monkeypatch.setattr(skyrim, "steam_libraries", lambda: [sandbox.root / "empty", lib])
    assert skyrim.find_game_dir() == game


def test_skse_dlls_lists_only_runtime_dlls_sorted(tmp_path):
    # Lowercase names only: glob is case-sensitive on Linux but not on Windows
    game = make_game(tmp_path / "game")
    for name in ("skse64_1_6_1170.dll", "skse64_1_5_97.dll", "skse64_loader.exe", "skse64_steam_loader.dll"):
        (game / name).write_bytes(b"")
    assert skyrim.skse_dlls(game) == ["skse64_1_5_97.dll", "skse64_1_6_1170.dll"]
    assert skyrim.skse_runtime_label("skse64_1_6_1170.dll") == "1.6.1170"


def test_cc_plugins_lists_only_installed_creation_club_files(tmp_path):
    game = make_game(tmp_path / "game")
    (game / "Skyrim.ccc").write_text("ccBGSSSE001-Fish.esm\nccQDRSSE001-SurvivalMode.esl\n\n", encoding="utf-8")
    (game / "Data" / "ccBGSSSE001-Fish.esm").write_bytes(b"")
    assert skyrim.cc_plugins(game) == ["ccBGSSSE001-Fish.esm"]


def test_uses_enb_needs_the_dll_and_an_enb_ini(tmp_path):
    game = make_game(tmp_path / "game")
    (game / "d3d11.dll").write_bytes(b"")
    assert not skyrim.uses_enb(game)          # d3d11.dll alone is also ReShade
    (game / "enblocal.ini").write_text("", encoding="utf-8")
    assert skyrim.uses_enb(game)


def test_game_files_by_name_lists_every_copy_with_its_case_on_disk(tmp_path):
    game = make_game(tmp_path / "game")
    for rel in ("Data/SKSE/Plugins/Hook.dll", "Hook.DLL"):
        (game / rel).parent.mkdir(parents=True, exist_ok=True)
        (game / rel).write_bytes(b"")
    by_name = skyrim.game_files_by_name(game)
    assert sorted(by_name["hook.dll"]) == ["Data/SKSE/Plugins/Hook.dll", "Hook.DLL"]
    assert by_name["skyrimse.exe"] == ["SkyrimSE.exe"]


# ---- Steam (fake registry) -----------------------------------------------------------
STEAM_KEY = r"Software\Valve\Steam"


def test_library_folders_are_read_in_file_order_with_backslashes_unescaped():
    vdf = ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n'
           '\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t\t"label"\t\t""\n\t}\n}\n')
    assert skyrim.parse_library_folders(vdf) == [Path("C:\\Program Files (x86)\\Steam"), Path("D:\\SteamLibrary")]


def test_no_steam_path_in_the_registry_means_no_libraries(sandbox):
    assert skyrim.steam_libraries() == []


def test_steam_libraries_are_steam_itself_then_each_listed_library(sandbox):
    steam, second = sandbox.root / "Steam", sandbox.root / "Lib"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(f'"path"\t\t"{second}"\n', encoding="utf-8")
    sandbox.winapi.set_reg("HKCU", STEAM_KEY, "SteamPath", str(steam))
    assert skyrim.steam_libraries() == [steam, second]


def test_find_game_dir_finds_the_game_through_steams_registry_entry(sandbox):
    steam = sandbox.root / "Steam"
    game = make_game(steam / "steamapps" / "common" / "Skyrim Special Edition")
    sandbox.winapi.set_reg("HKCU", STEAM_KEY, "SteamPath", str(steam))
    assert skyrim.find_game_dir() == game


@pytest.mark.parametrize("rel, runtime", [
    ("SkyrimTogetherReborn/cache/x/manifest.json", True),
    ("Data/SkyrimTogetherReborn/cache/a.bin", True),
    ("data\\skyrimtogetherreborn\\Cache\\a.bin", True),
    ("Data/SkyrimTogetherReborn/SkyrimTogether.exe", False),
    ("Data/OtherMod/cache/a.bin", False),                  # only Skyrim Together's cache
])
def test_only_skyrim_togethers_cache_counts_as_written_at_run_time(rel, runtime):
    assert skyrim.is_runtime_file(rel) is runtime
