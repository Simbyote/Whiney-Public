"""
test_doctor_report.py  --  src/whiney/doctor.py (the whole report, word for word)

Players paste the Doctor report to the maintainer, so its exact text is a
contract: which checks ran, in what order, at which level, with which fix.
One setup with a problem in every check group runs through run_all, and the
report must match the golden text below character for character.

--software  A fake game, load order, SKSE folder and Vortex staging in the sandbox.
"""
import pytest

from builders import make_game, make_mod, write_plugin, write_plugins_txt
from whiney import doctor, paths

pytestmark = pytest.mark.software

GOLDEN = r"""
Test Pack - Doctor report (2026-10-30 12:00)
Sync code: SYNC-CODE

[WARN] Vortex: Couldn't find Vortex
    Fix: Install it from nexusmods.com/app, or ignore this if it's in an unusual folder.
[OK] Game: Found Skyrim SE
    <game>
[FAIL] SKSE: SKSE for game version 1.6.1170 is missing
    Fix: Get it from skse.silverlock.org. Copy skse64_loader.exe and the .dll files into the Skyrim folder, next to SkyrimSE.exe.
[FAIL] Game: Missing Creation Club files
    ccBGSSSE001-Fish.esm
    Fix: Launch the game once from Steam so it downloads its Creation Club content.
[WARN] Graphics: Tester uses an ENB and you don't
    The game runs fine without it, it just won't look the same.
    Fix: Optional: get the ENB binaries from enbdev.com and copy d3d11.dll + d3dcompiler_46e.dll into the Skyrim folder.
[FAIL] Plugins: 1 enabled plugin(s) are missing from Data
    Gone.esp
    Fix: In Vortex: Mods > select all > Enable > Deploy. Or run Install again.
[FAIL] Plugins: 1 plugin(s) are missing a master (crashes at startup)
    Patch.esp needs: Base.esp
    Fix: Install/enable the mod that provides the missing file, or disable the plugin that needs it (Vortex > Plugins).
[FAIL] Plugins: Load order has plugins before their masters
    Late.esp loads before its master Base2.esp
    Fix: Run Install again to restore the pack's load order (keep Autosort OFF).
[WARN] Sync: Your load order differs from the pack
    Not enabled for you: base.esp
    Extra on your side: base2.esp, gone.esp, late.esp
    Fix: In multiplayer this causes desyncs. Install tab > Install again restores it.
[FAIL] SKSE: 1 SKSE plugins installed but SKSE itself isn't
    Fix: Get SKSE from skse.silverlock.org and copy skse64_loader.exe + the .dll files next to SkyrimSE.exe.
[WARN] Crash reports: No crash logger installed
    Without one, Crash Squatch can only tell that the game crashed, not why.
    Fix: Install 'Crash Logger SSE AE VR' from Nexus, through Vortex.
[WARN] Mods: 1 of 2 pack mods aren't in your Vortex
    Missing
    Fix: Run Install again, or drag those zips from Downloads\Whiney\ToVortex into Vortex.
"""


@pytest.fixture
def broken(sandbox, monkeypatch):
    """A game where every check group finds something: missing SKSE, a missing master, bad order, sync drift."""
    monkeypatch.setattr(doctor.time, "strftime", lambda fmt: "2026-10-30 12:00")
    monkeypatch.setattr(doctor.skyrim, "sync_code", lambda *a: "SYNC-CODE")
    game = make_game(sandbox.root / "game")
    data = game / "Data"
    write_plugin(data, "Patch.esp", ["Skyrim.esm", "Base.esp"])
    write_plugin(data, "Base.esp")
    write_plugin(data, "Late.esp", ["Base2.esp"])
    write_plugin(data, "Base2.esp")
    write_plugins_txt(paths.SKYRIM_APPDATA / "plugins.txt",
                      enabled=["Patch.esp", "Late.esp", "Base2.esp", "Gone.esp"], disabled=["Base.esp"])
    write_plugins_txt(sandbox.packinfo / "plugins.txt", enabled=["Patch.esp", "Base.esp"])
    (data / "SKSE" / "Plugins").mkdir(parents=True)
    (data / "SKSE" / "Plugins" / "Hooks.dll").write_bytes(b"")
    make_mod(sandbox.staging, "Alpha-11111-1-0-1700000000", {"Alpha.esp": b""})
    req = {"game_version": "1.6.1170.0", "skse_dlls": ["skse64_1_6_1170.dll"],
           "cc_plugins": ["ccBGSSSE001-Fish.esm"], "uses_enb": True,
           "mods": ["Alpha-11111-1-0-1700000000", "Missing-22222-1-0-1700000000"]}
    return game, req


def test_the_report_of_a_broken_setup_matches_the_golden_text(broken):
    game, req = broken
    expected = GOLDEN.strip("\n").replace("<game>", str(game))
    assert doctor.report_text(doctor.run_all(game=game, req=req)) == expected
