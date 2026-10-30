"""
test_docs.py  --  docs/_DOCUMENTATION.md, applied to src/, tests/ and docs/

The documentation standard only holds if something checks it. These enforce
the parts a machine can: every source module opens with Purpose, Main package
and Flow; every test file names its target and its mode; every guide is
listed in docs/README.md, and every path that index names exists.

--software  Reads files only.
"""
import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.software

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "src" / "whiney").rglob("*.py"))
TESTS = sorted((ROOT / "tests").glob("test_*.py"))
DOCS = ROOT / "docs"


def _docstring(path: Path) -> str:

    return ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: str(p.relative_to(ROOT / "src" / "whiney")))
def test_source_modules_open_with_purpose_main_package_and_flow(src):
    doc = _docstring(src)
    for section in ("Purpose:", "Main package:", "Flow:"):
        assert f"\n{section}" in doc, f"{src.name}: module docstring needs a '{section}' section"


@pytest.mark.parametrize("test", TESTS, ids=lambda p: p.name)
def test_test_modules_name_their_target_and_mode(test):
    doc = _docstring(test)
    assert doc.splitlines()[0].startswith(f"{test.name}  --  "), "first line: '<file>  --  <target>'"
    assert re.search(r"^--(software|live)\s", doc, re.M), "say what each mode covers: '--software  ...'"


@pytest.mark.parametrize("test", TESTS, ids=lambda p: p.name)
def test_test_modules_target_a_module_that_exists(test):
    # A test file left behind after its module was split or renamed tests code that's gone
    target = _docstring(test).splitlines()[0].split("  --  ", 1)[1]
    m = re.match(r"(src/whiney/\w+\.py)", target)
    if m:
        assert (ROOT / m.group(1)).is_file(), f"{test.name} targets {m.group(1)}, which no longer exists: delete it"


def test_every_guide_is_listed_in_the_docs_index():
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for guide in sorted((DOCS / "guides").glob("*.md")):
        assert f"guides/{guide.name}" in index, f"add {guide.name} to docs/README.md"


def test_every_path_the_docs_index_names_exists():
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for rel in set(re.findall(r"`((?:guides/)?[\w./-]+\.md)`", index)):
        assert (DOCS / rel).is_file(), f"docs/README.md names {rel}, which doesn't exist"
