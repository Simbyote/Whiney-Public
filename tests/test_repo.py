"""
test_repo.py  --  build.bat, the other .bat files, requirements*.txt, Makefile, the module structure

These files have no tests of their own and fail only on someone else's PC:
a .bat with LF line endings that cmd misparses, a build.bat naming a file that
moved, a dependency that floats to a new version, a make target pointing at
a command that changed. Each is checked here so the drift shows up in
`make check` instead of on the maintainer's machine. So are the architecture
rules (layers, the OS and paths boundaries) and the window's contract with
its pages (ui.widgets.AppShell), which mypy can't check through customtkinter.

--software  Reads the files; runs `make -n` (prints, runs nothing). No Windows needed.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.software

ROOT = Path(__file__).resolve().parents[1]
BATS = sorted(ROOT.glob("*.bat"))
# Written by build.bat itself before PyInstaller runs, so absent in a clean checkout
GENERATED = {"_packinfo", "pack_config.json"}


def _bat_text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_maintainer_bat_files_are_all_present():
    assert {p.name for p in BATS} == {"build.bat", "pack_mods.bat", "pack_update.bat",
                                      "record_baseline.bat", "test_app.bat"}


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_bat_files_use_crlf_line_endings(bat):
    # cmd.exe mis-parses `goto :label` / `call :label` in LF-only files
    raw = bat.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n"), "convert to CRLF (.gitattributes does it on checkout)"


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_bat_files_put_src_on_the_path_before_running_the_package(bat):
    text = bat.read_text(encoding="utf-8")
    if "-m whiney" not in text:
        pytest.skip("doesn't run the package")
    assert text.index('set "PYTHONPATH=%~dp0src"') < text.index("-m whiney")


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_modules_the_bat_files_run_exist(bat):
    for module in re.findall(r"-m (whiney[\w.]*)", bat.read_text(encoding="utf-8")):
        path = ROOT / "src" / Path(*module.split("."))
        assert path.with_suffix(".py").is_file() or (path / "__main__.py").is_file(), module


def test_build_bat_names_only_files_that_exist():
    text = _bat_text("build.bat").replace("^\n", " ")
    sources = [s.split(";")[0] for s in re.findall(r'--add-data "([^"]+)"', text)]
    sources += re.findall(r"--icon (\S+)", text)
    sources += re.findall(r"-r (\S+)", text)
    entry = re.search(r"(src\\\S+\.py)", text).group(1)
    assert len(sources) >= 4
    for s in sources + [entry]:
        if s in GENERATED:
            continue
        assert (ROOT / s.replace("\\", "/")).exists(), s


def test_build_bat_bundles_assets_where_the_app_looks_for_them():
    # paths.ASSET_DIR is BUNDLE_DIR / "assets"; the exe must carry the icon there
    assert '--add-data "assets\\icon.ico;assets"' in _bat_text("build.bat")


@pytest.mark.parametrize("req", sorted(ROOT.glob("requirements*.txt")), ids=lambda p: p.name)
def test_requirements_are_pinned_exactly(req):
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-r "):
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[\w.]+", line), f"pin with ==: {line}"


# ---- Makefile ----------------------------------------------------------------------
needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


def _documented_targets() -> list[str]:
    return re.findall(r"^([a-z0-9-]+):.*## ", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)


def test_every_documented_target_is_phony():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    phony = set(re.search(r"^\.PHONY:(.*)$", text, re.M).group(1).split())
    assert set(_documented_targets()) <= phony


@needs_make
@pytest.mark.parametrize("target", _documented_targets())
def test_every_target_expands(target):
    out = subprocess.run(["make", "-s", "-n", "-C", str(ROOT), target],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("runner", ["Makefile", ".github/workflows/ci.yml"])
def test_pytest_runs_with_default_encoding_warnings(runner):
    # pyproject turns EncodingWarning into an error, but Python only emits it with
    # this flag; without it a Windows-only cp1252 bug slips through on Linux
    lines = [line for line in (ROOT / runner).read_text(encoding="utf-8").splitlines() if "-m pytest" in line]
    assert lines and all("-X warn_default_encoding" in line for line in lines), lines


@pytest.mark.parametrize("runner", ["Makefile", ".github/workflows/ci.yml"])
def test_the_type_checker_runs_in_make_lint_and_ci(runner):
    # Types only protect anything while something checks them on every change
    assert "-m mypy" in (ROOT / runner).read_text(encoding="utf-8")


# ---- module layers (docs/architecture.md) --------------------------------------------
# A module may import only from lower layers. Keeps the graph acyclic and the
# logic headless: nothing below ui may reach tkinter through an import
LAYERS = [
    {"paths", "util", "winapi"},
    {"config"},
    {"skyrim", "vortex"},
    {"doctor", "crashsquatch", "host", "manage", "snapshot", "pack_mods"},
    {"installer"},
    {"ui.theme"},
    {"ui.widgets", "ui.splash"},
    {"ui.pages.home", "ui.pages.install", "ui.pages.doctor", "ui.pages.crash", "ui.pages.host", "ui.pages.manage"},
    {"ui.app"},
    {"__main__"},
]
LAYER_OF = {m: i for i, layer in enumerate(LAYERS) for m in layer}
PKG = ROOT / "src" / "whiney"


def _module_id(path: Path) -> str:
    """src/whiney/ui/pages/home.py -> "ui.pages.home"."""
    return ".".join(path.relative_to(PKG).with_suffix("").parts)


SOURCES = sorted(p for p in PKG.rglob("*.py") if p.stem != "__init__")
MODULES = {_module_id(p) for p in SOURCES}


def _whiney_imports(path: Path) -> set[str]:
    """The whiney modules a file imports, as module ids ("from whiney.ui.theme import BG" -> "ui.theme")."""
    import ast
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("whiney"):
            continue
        base = node.module[len("whiney."):] if node.module != "whiney" else ""
        for alias in node.names:
            sub = f"{base}.{alias.name}".lstrip(".")
            found.add(sub if sub in MODULES else base)
    return found


def test_every_module_has_a_layer():
    assert MODULES == set(LAYER_OF), "add the new module to LAYERS"


@pytest.mark.parametrize("src", SOURCES, ids=_module_id)
def test_modules_import_only_from_lower_layers(src):
    me = _module_id(src)
    upward = sorted(m for m in _whiney_imports(src) if LAYER_OF[m] >= LAYER_OF[me] and m != me)
    assert upward == [], f"{me} (layer {LAYER_OF[me]}) imports from its own layer or above: {upward}"


@pytest.mark.parametrize("src", SOURCES, ids=_module_id)
def test_only_the_ui_package_imports_tkinter(src):
    # Everything outside ui/ must run headless: the packer, --snapshot, the tests
    import ast
    tk = set()
    for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            tk |= {a.name for a in node.names if a.name.split(".")[0] in ("tkinter", "customtkinter")}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("tkinter", "customtkinter"):
            tk.add(node.module)
    if _module_id(src).startswith("ui."):
        return
    assert tk == set(), f"{_module_id(src)} imports {sorted(tk)}; GUI code belongs in whiney/ui/"



# ---- real-world locations (docs/architecture.md, "Where files live") ----------------------
@pytest.mark.parametrize("src", [p for p in SOURCES if p.stem not in ("paths", "__main__")], ids=_module_id)
def test_only_paths_builds_real_world_locations(src):
    # The sandbox redirects paths.py; a folder built anywhere else is the real one, even in tests
    # (__main__ spells out its log folder because nothing is imported yet when it runs)
    import ast
    found = set()
    for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in ("home", "expanduser", "environ", "getenv"):
            found.add(node.attr)
    assert found == set(), f"{_module_id(src)} uses {sorted(found)}: add the location to paths.py instead"


# ---- the OS boundary (docs/architecture.md) -----------------------------------------
# Only winapi talks to the OS, so the sandbox can replace one module and every
# Windows call stays testable; anything else importing these would bypass it
OS_MODULES = {"winreg", "ctypes", "subprocess", "psutil", "webbrowser"}


def _os_reach(path: Path) -> set[str]:
    import ast
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names} & OS_MODULES
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in OS_MODULES:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute) and node.attr == "startfile":
            found.add("os.startfile")
    return found


@pytest.mark.parametrize("src", [p for p in SOURCES if p.stem != "winapi"], ids=_module_id)
def test_only_winapi_talks_to_the_os(src):
    assert _os_reach(src) == set(), f"move these calls into winapi.py: {sorted(_os_reach(src))}"


# ---- the window's contract with its pages (ui.widgets.AppShell) ---------------------------
# Pages get the window as an AppShell. App subclasses customtkinter's CTk, which ships no
# types, so mypy accepts App as matching any protocol; this checks the match from the source
def _class_def(path: Path, name: str):
    import ast
    return next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.ClassDef) and n.name == name)


def _signature(fn) -> str:
    """A method's parameters, annotations, defaults and return annotation, as source text."""
    import ast
    return f"({ast.unparse(fn.args)}) -> {ast.unparse(fn.returns) if fn.returns else None}"


def test_app_implements_every_appshell_method_with_the_same_signature():
    import ast
    shell = _class_def(PKG / "ui" / "widgets.py", "AppShell")
    app = _class_def(PKG / "ui" / "app.py", "App")
    app_methods = {n.name: n for n in app.body if isinstance(n, ast.FunctionDef)}
    for want in (n for n in shell.body if isinstance(n, ast.FunctionDef)):
        assert want.name in app_methods, f"App has no {want.name}(), which AppShell promises pages"
        assert _signature(app_methods[want.name]) == _signature(want), f"App.{want.name} differs from AppShell"


def test_app_sets_every_appshell_attribute_with_the_same_type():
    import ast
    shell = _class_def(PKG / "ui" / "widgets.py", "AppShell")
    app = _class_def(PKG / "ui" / "app.py", "App")
    assigned = {}                                 # self.<name> -> its annotation ("" if none)
    for node in ast.walk(app):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            assigned[node.target.attr] = ast.unparse(node.annotation)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    assigned.setdefault(t.attr, "")
    for want in (n for n in shell.body if isinstance(n, ast.AnnAssign)):
        name, kind = want.target.id, ast.unparse(want.annotation)
        assert name in assigned, f"App never sets self.{name}, which AppShell promises pages"
        if kind != "Widget":                      # widgets are untyped (customtkinter); only presence counts
            assert assigned[name] == kind, f"App.{name} is {assigned[name] or 'unannotated'}, AppShell says {kind}"
