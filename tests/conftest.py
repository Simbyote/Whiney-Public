"""
Test-mode selection and shared fixtures.

    pytest                      -> --software (default)
    pytest --software           contract tests on fixtures: any OS, deterministic, pass/fail
    pytest --live               read-only checks against the real Windows install;
                                results go to artifacts/<timestamp>/ for review
    pytest --software --live    both

Every test carries exactly one of @pytest.mark.software / @pytest.mark.live.
Tests outside the selected mode are deselected rather than skipped, so the
output only lists what actually ran.

Software tests run inside `sandbox`: every path in paths.py and pack_mods would
touch (Downloads, AppData, Documents, Vortex staging, the kit folder) is
redirected into tmp_path, CONFIG is a fixed test config, the OS is FakeWinapi,
Google Drive is FakeGdown, and opening a network connection fails the test. A
software test can't read or change a real install, or reach the internet, even
by mistake.
"""
import inspect
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from fake_gdown import FakeGdown
from fake_winapi import FakeWinapi
from whiney import config as pack_config  # pytest hooks take a `config` argument
from whiney import crashsquatch, pack_mods, paths, winapi

# What a fresh kit holds: placeholders, no update configured
TEST_CONFIG = {"pack_name": "Test Pack", "author": "Tester", "drive_file_id": "PASTE_FILE_ID_HERE",
               "update_file_id": ""}


def pytest_addoption(parser):
    g = parser.getgroup("whiney")
    g.addoption("--software", action="store_true",
                help="run contract tests on fixtures (default when no mode is given)")
    g.addoption("--live", action="store_true",
                help="run read-only checks against the real Windows install")
    g.addoption("--artifact-dir", default="artifacts",
                help="root for live-run output (default: ./artifacts)")


def _selected_modes(config) -> set[str]:
    """Modes chosen on the command line; software when none is given."""
    modes = {m for m in ("software", "live") if config.getoption(f"--{m}")}
    return modes or {"software"}


def pytest_collection_modifyitems(config, items):
    modes = _selected_modes(config)
    kept, dropped = [], []
    for item in items:
        item_modes = {m for m in ("software", "live") if item.get_closest_marker(m)}
        if len(item_modes) != 1:
            raise pytest.UsageError(f"{item.nodeid}: mark it exactly one of software / live")
        (kept if item_modes & modes else dropped).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept



def pytest_runtest_logreport(report):
    """On GitHub Actions, turn each failure into an ::error annotation on the PR and the run summary."""
    if not report.failed or os.environ.get("GITHUB_ACTIONS") != "true":
        return
    path, line, _ = report.location
    # The tail of the failure holds the assertion and its values; annotations cap around 4 KB
    text = "\n".join(report.longreprtext.splitlines()[-25:])[-3000:]
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    title = f"{report.nodeid} ({report.when})".replace(",", "%2C").replace("::", " / ")
    # pytest captures sys.stdout during tests; workflow commands must reach the real one
    sys.__stdout__.write(f"\n::error file={path},line={(line or 0) + 1},title={title}::{text}\n")
    sys.__stdout__.flush()

# Every function whiney.winapi defines: the sandbox replaces each one
WINAPI_FUNCTIONS = sorted(n for n, f in vars(winapi).items()
                          if inspect.isfunction(f) and f.__module__ == winapi.__name__)


def _no_network(*args, **kwargs):
    """Stands in for socket connections in software tests."""
    raise AssertionError("a software test tried to use the network; fake it (sandbox.gdown, sandbox.winapi)")


def _not_faked(name: str):
    """Stands in for a winapi function FakeWinapi lacks: fails the test instead of reaching the OS."""
    def call(*args, **kwargs):
        raise AssertionError(f"winapi.{name} has no fake in tests/fake_winapi.py; "
                             "a software test must not reach the real OS")
    return call


@dataclass
class Sandbox:
    """The redirected locations a software test sees, all under tmp_path."""
    root: Path
    kit: Path          # KIT_DIR / BUNDLE_DIR: pack_config.json, manifests, _packinfo
    work: Path         # Downloads\Whiney
    appdata: Path      # %LOCALAPPDATA%\Skyrim Special Edition (plugins.txt)
    documents: Path    # Documents (My Games\Skyrim Special Edition under it)
    staging: Path      # Vortex's mods folder
    winapi: FakeWinapi = None    # the OS: registry, processes, launches (tests/fake_winapi.py)
    gdown: FakeGdown = None      # Google Drive downloads (tests/fake_gdown.py)

    @property
    def packinfo(self) -> Path:
        return self.kit / paths.PACKINFO_NAME


@pytest.fixture(autouse=True)
def sandbox(request, tmp_path, monkeypatch):
    """Redirect every real-world path into tmp_path for software tests; live tests are left alone."""
    if request.node.get_closest_marker("software") is None:
        return None
    box = Sandbox(root=tmp_path, kit=tmp_path / "kit", work=tmp_path / "work",
                  appdata=tmp_path / "appdata", documents=tmp_path / "Documents",
                  staging=tmp_path / "staging")
    for d in (box.kit, box.appdata, box.documents, box.staging):
        d.mkdir()

    for name, value in {
        "KIT_DIR": box.kit, "BUNDLE_DIR": box.kit, "ASSET_DIR": box.kit / "assets",
        "PACKINFO": box.packinfo,
        "GUIDE": box.kit / "README.txt",
        "DOWNLOADS": box.root / "Downloads",
        "HOME_DOCUMENTS": box.documents,
        "WORK_DIR": box.work,
        "ARCHIVE": box.work / "modpack.tar.gz",
        "ARCHIVE_ID": box.work / "modpack.id",
        "EXTRACT_DIR": box.work / "extracted",
        "ZIP_DIR": box.work / "ToVortex",
        "BASE_READY": box.work / "ToVortex" / ".base_ready",
        "UPDATE_ARCHIVE": box.work / "modpack_update.tar.gz",
        "UPDATE_EXTRACT": box.work / "update_extracted",
        "REPAIR_DIR": box.work / "Repair",
        "REPAIR_EXTRACT": box.work / "repair_extracted",
        "INSTALLED_MARKER": box.work / "installed.json",
        "SETTINGS_FILE": box.work / "settings.json",
        "CRASH_HISTORY": box.work / "crash_history.json",
        "SAVE_BACKUPS": box.work / "save_backups",
        "LOG_FILE": box.work / "app_log.txt",
        "SKYRIM_APPDATA": box.appdata,
        "VORTEX_STAGING": box.staging,
        "VORTEX_CANDIDATES": [],
    }.items():
        monkeypatch.setattr(paths, name, value)

    # A fixed config, so tests never depend on what DEFAULT_CONFIG happens to hold
    monkeypatch.setattr(pack_config, "DEFAULT_CONFIG", dict(TEST_CONFIG))
    monkeypatch.setattr(pack_config, "CONFIG", dict(TEST_CONFIG))

    monkeypatch.setattr(pack_mods, "HERE", box.kit)
    monkeypatch.setattr(pack_mods, "MANIFEST", box.kit / "pack_manifest.json")
    monkeypatch.setattr(pack_mods, "LAST_UPDATE", box.kit / "last_update.json")
    monkeypatch.setattr(crashsquatch, "_mod_index_cache", {})
    # The OS: every winapi function is the fake's, or raises if the fake lacks it
    box.winapi = FakeWinapi(box.documents)
    for name in WINAPI_FUNCTIONS:
        monkeypatch.setattr(winapi, name, getattr(box.winapi, name, None) or _not_faked(name))

    # Google Drive: the installer imports gdown when it downloads; this is what it gets
    box.gdown = FakeGdown()
    monkeypatch.setitem(sys.modules, "gdown", box.gdown)
    # No network at all: a software test that opens a connection fails instead
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    _assert_nothing_escapes(tmp_path)
    return box


def _assert_nothing_escapes(tmp_path: Path) -> None:
    """Fail the test if any loaded whiney module still holds a real-world path.

    Covers a path constant added without a sandbox line above, and a stale
    module left behind by a refactor (e.g. an old core.py beside its replacements).
    """
    leaked = []
    for name, module in list(sys.modules.items()):
        if name != "whiney" and not name.startswith("whiney."):
            continue
        for attr, value in vars(module).items():
            values = value if isinstance(value, (list, tuple)) else [value]
            if any(isinstance(v, Path) and not v.is_relative_to(tmp_path) for v in values):
                leaked.append(f"{name}.{attr}")
    assert not leaked, ("real paths outside the sandbox: " + ", ".join(sorted(leaked))
                        + ". Sandbox them in conftest.py, or delete the module if it is stale.")


@pytest.fixture
def artifacts(request) -> Path:
    """A fresh folder under --artifact-dir for one live test's output."""
    root = Path(request.config.getoption("--artifact-dir"))
    out = root / time.strftime("%Y%m%d-%H%M%S") / request.node.name
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture
def windows():
    """Live tests need Windows Python: from WSL, `make test-live` runs them on py.exe."""
    if not winapi.IS_WINDOWS:
        pytest.skip("live tests need Windows Python (make test-live from WSL)")
