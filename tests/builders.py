"""
Builders for the files the app reads: plugin headers, plugins.txt, a game
folder, Vortex mod folders. Tests describe the situation in a line or two and
these write the bytes, so the format details live in one place.
"""
import struct
from pathlib import Path

# TES4 record header flags (UESP: Skyrim Mod File Format/TES4)
ESM_FLAG = 0x1
ESL_FLAG = 0x200


def _field(typ: bytes, data: bytes) -> bytes:
    return typ + struct.pack("<H", len(data)) + data


def plugin_bytes(masters=(), esm=False, esl=False, big_field=False) -> bytes:
    """A minimal TES4 header with MAST/DATA pairs per master.

    big_field adds an XXXX-prefixed field over 64 KB before the masters, the
    way plugins with huge descriptions are written.
    """
    body = _field(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))
    if big_field:
        payload = b"x" * 70_000
        body += b"XXXX" + struct.pack("<H", 4) + struct.pack("<I", len(payload))
        body += b"SNAM" + struct.pack("<H", 0) + payload
    for m in masters:
        body += _field(b"MAST", m.encode("cp1252") + b"\0")
        body += _field(b"DATA", struct.pack("<Q", 0))
    flags = (ESM_FLAG if esm else 0) | (ESL_FLAG if esl else 0)
    # TES4 header: type, data size, flags, form id, version control, form version, unknown
    return b"TES4" + struct.pack("<IIIIHH", len(body), flags, 0, 0, 44, 0) + body


def write_plugin(data_dir: Path, name: str, masters=(), esm=False, esl=False) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / name
    path.write_bytes(plugin_bytes(masters, esm=esm, esl=esl))
    return path


def write_plugins_txt(path: Path, enabled=(), disabled=(), header=True) -> Path:
    """plugins.txt the way the game writes it: '*' marks enabled, '#' lines are comments."""
    lines = ["# This file is used by Skyrim to keep track of your downloaded content."] if header else []
    lines += [f"*{n}" for n in enabled] + list(disabled)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_game(root: Path, official=("Skyrim.esm", "Update.esm")) -> Path:
    """A game folder with SkyrimSE.exe and the given official masters in Data."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SkyrimSE.exe").write_bytes(b"MZ")
    for name in official:
        write_plugin(root / "Data", name, esm=True)
    return root


def make_mod(staging: Path, folder: str, files: dict) -> Path:
    """A Vortex mod folder: {relative path: bytes or str}."""
    mod = staging / folder
    for rel, content in files.items():
        p = mod / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode() if isinstance(content, str) else content)
    return mod
