"""
test_paths.py  --  src/whiney/paths.py

paths.py is the one place real-world locations are built. The kit folder
anchoring is what build.bat and pack_mods rely on to find pack_config.json,
_packinfo/ and the manifests; the sandbox's own guard (conftest.py) covers
the rest, failing any test run where a path constant escapes it.

--software  Fixture files in the sandbox. No Skyrim, no registry.
"""
import pytest

from whiney import paths

pytestmark = pytest.mark.software

# Taken at import, before the sandbox redirects it
REAL_KIT_DIR = paths.KIT_DIR


def test_kit_dir_is_the_repo_root_beside_build_bat():
    # build.bat runs `-m whiney --snapshot` and expects pack_config.json and _packinfo next to it
    assert (REAL_KIT_DIR / "build.bat").is_file()
    assert (REAL_KIT_DIR / "src" / "whiney" / "paths.py").is_file()
