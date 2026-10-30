"""Small helpers: JSON files, sizes, replacing a file with a backup, archive checksums and entry paths.

Purpose:
    The few helpers every module needs that belong to no part of the app.
    Kept small on purpose: anything that knows about Skyrim, Vortex or the
    pack goes in skyrim, vortex or config, and anything that asks the OS
    (processes, the registry, opening a folder) goes in winapi.

Main package:
    None; plain helpers.

Flow:
    Independent helpers; no order.
"""
import filecmp
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"              # the last unit: never rolls over to PB


def backup_and_copy(src: str | Path, dst: str | Path) -> None:
    """Replace dst with src, keeping the replaced file as <dst>.bak.

    A dst that is already the same as src isn't backed up: it's the pack's
    copy from an earlier apply, and backing it up would overwrite the player's
    own file in the .bak with it.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not filecmp.cmp(src, dst, shallow=False):
        shutil.copy2(dst, dst.with_name(dst.name + ".bak"))
    shutil.copy2(src, dst)


def sha256_file(path: str | Path, progress: Callable[[float], object] | None = None) -> str:
    """Hex SHA-256 of a file, read in 1 MB blocks (packs are several GB).

    Inputs:
        progress: Called with the fraction read so far after each block, if given.
    """
    h = hashlib.sha256()
    total = Path(path).stat().st_size or 1
    done = 0
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
            done += len(block)
            if progress:
                progress(done / total)
    return h.hexdigest()


class UnsafeArchive(ValueError):
    """An archive entry that would land outside the folder it's unpacked into, or isn't a plain file or folder."""


def safe_member_path(dest: str | Path, name: str) -> Path:
    """Where an archive entry named `name` lands under dest; raises UnsafeArchive if that's outside dest.

    Inputs:
        name: The entry's name as stored: relative, absolute, or with ".."
            components (a crafted or corrupt archive).

    Outputs:
        The resolved path inside dest. Checked before anything is written, so
        one bad entry stops the whole archive.
    """
    root = Path(dest).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise UnsafeArchive(f"{name!r} would be written outside {root}")
    return target


