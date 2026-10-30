"""Install and update logic, independent of the GUI that drives it.

Purpose:
    Takes a player from nothing to the pack's exact setup: download the pack
    from Drive, unpack it, zip each mod for Vortex, hand the one manual step
    (dragging zips into Vortex) to the player, then apply the pack's load
    order and INIs and verify the plugins arrived. Each step can be re-run;
    finished work is detected and skipped, which is also what makes a
    cancelled install safe to start again.

    The UI object passed in follows InstallerUI (step, log, progress, ask,
    tell, wait_for_user): the GUI's GuiBridge, or a test's FakeUI.

Main package:
    installed.json (paths.INSTALLED_MARKER): which full pack and update are
    installed; config.install_state() compares it with the requirements.
    Abort: an expected stop, with a message the player can act on.
    Cancelled: the player cancelled (an Abort); raised at the next safe point
    after the `cancel` event passed to Installer is set.

Flow:
    plan(mode) picks the steps; Installer.run does them in order:
    check -> download -> unpack -> prepare -> update -> vortex -> order -> verify,
    then writes installed.json. "update" mode skips straight to the update.
    When every pack mod is already in the game, the player can skip straight
    to the load order and settings (download through vortex show as skipped).
    An archive comes from, in order: the file the player picked, a copy in
    Downloads, or Drive; each is checked against its SHA-256 (obtain).
    "repair" mode reinstalls only the given mods (the Doctor's Repair button):
    gather their zips -> vortex -> verify just them; installed.json is left alone.
"""
import json
import os
import shutil
import tarfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol

from whiney import config, doctor, pack_mods, paths, skyrim, util, vortex, winapi

STEP_NAMES = {
    "check":    "Check your PC",
    "gather":   "Find the mods to repair",
    "download": "Download the mod pack",
    "unpack":   "Unpack it",
    "prepare":  "Prepare mods for Vortex",
    "update":   "Get the latest update",
    "vortex":   "Install in Vortex (your turn)",
    "order":    "Set load order & settings",
    "verify":   "Make sure everything's in place",
}


# The steps that get mods into the game; skipped together when they're all there already
MOD_STEPS = frozenset({"download", "unpack", "prepare", "update", "vortex"})

Mode = Literal["fresh", "update", "repair"]     # full pack (+ update), the update only, or some mods again
StepResult = Literal["skipped"] | None   # a step returns "skipped" when its work was already done


class InstallerUI(Protocol):
    """What the installer needs from whoever drives it: the GUI's GuiBridge, or a test's FakeUI."""

    def step(self, key: str, state: Literal["active", "done", "skipped", "error", "cancelled"]) -> None: ...
    def log(self, text: str) -> None: ...
    def progress(self, fraction: float | None, text: str) -> None: ...     # None: busy, no fraction
    def ask(self, question: str, default: bool) -> bool: ...              # blocks until answered
    def tell(self, message: str) -> None: ...                             # blocks until dismissed

    def wait_for_user(self, title: str, body: str, button: str,
                      extras: Sequence[tuple[str, Callable[[], object]]]) -> None: ...


class Abort(Exception):
    """Expected failure with a friendly message."""


class Cancelled(Abort):
    """The player cancelled the install. Nothing finished is lost; Start picks up where it stopped."""

    def __init__(self, message: str = "Cancelled. Nothing finished is lost: click Start to pick up where it stopped."
                 ) -> None:
        super().__init__(message)


def plan(mode: Mode) -> list[str]:
    has_update = bool(config.CONFIG.get("update_file_id"))
    if mode == "repair":
        return ["gather", "vortex", "verify"]
    if mode == "update":
        steps = ["check"] + (["update"] if has_update else []) + ["vortex", "order", "verify"]
    else:
        steps = ["check", "download", "unpack", "prepare"] + (["update"] if has_update else []) \
                + ["vortex", "order", "verify"]
    return steps


class Installer:
    def __init__(self, ui: InstallerUI, mode: Mode, game: Path | str | None = None, apply_inis: bool = True,
                 cancel: threading.Event | None = None, repair: Sequence[str] = (),
                 pack_file: Path | str | None = None) -> None:
        """mode: 'fresh' (full pack [+update]), 'update' (update only) or 'repair' (the `repair` mods only).

        cancel: a threading.Event the GUI sets to cancel; checked between steps,
            during downloads, unpacking, zipping and checksums, and after every wait.
        repair: pack mod folder names (files.json keys) to reinstall, in 'repair' mode.
        pack_file: a copy of the full pack or the update the player already has, used
            instead of downloading it when its SHA-256 matches; it is copied, never moved.
        """
        self.ui, self.mode = ui, mode
        self.repair_mods = list(repair)
        self.pack_file = Path(pack_file) if pack_file else None
        self._pack_file_sha: str | None = None
        self.game = Path(game) if game else None
        self.cancel = cancel or threading.Event()
        self.want_inis = apply_inis
        self.req = config.load_requirements()
        self.base = config.base_id(self.req)
        self.cfg = config.CONFIG
        self.update_info: dict[str, Any] | None = None     # the update's added/changed/removed, once applied

    # -- helpers -------------------------------------------------------------
    def _stop_if_cancelled(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def _step(self, key: str, fn: Callable[[], StepResult]) -> StepResult:
        self._stop_if_cancelled()
        self.ui.step(key, "active")
        try:
            result = fn()
        except Cancelled:
            self.ui.step(key, "cancelled")
            raise
        except BaseException:
            self.ui.step(key, "error")
            raise
        self.ui.step(key, "skipped" if result == "skipped" else "done")
        return result

    def _space_check(self, archive: Path) -> None:
        need = archive.stat().st_size * 3
        free = shutil.disk_usage(paths.WORK_DIR).free
        if free < need:
            if not self.ui.ask(f"Low disk space: about {util.human(need)} is needed but only "
                               f"{util.human(free)} is free on this drive.\n\nTry anyway?", False):
                raise Abort("Free up some disk space, then try again.")

    # -- steps -----------------------------------------------------------------
    def check(self) -> None:
        findings = doctor.preflight(self.req, self.game)
        for f in findings:
            self.ui.log(f"[{f.level}] {f.title}" + (f" - {f.fix}" if f.fix else ""))
        fails = [f for f in findings if f.level == "FAIL"]
        if fails:
            msg = "\n".join(f"- {f.title}" for f in fails)
            if not self.ui.ask(f"Some checks failed:\n\n{msg}\n\nThe Doctor tab explains how to fix "
                               "these. Continue anyway?", False):
                raise Abort("Stopped so you can fix the failed checks first.")

    def download(self, file_id: str, archive: Path, label: str) -> None:
        """gdown with a live size readout; browser fallback if Drive blocks it."""
        import gdown
        paths.WORK_DIR.mkdir(parents=True, exist_ok=True)
        url = f"https://drive.google.com/uc?id={file_id}"
        partial = archive.with_suffix(".part")
        self._remove_gdown_leftovers(partial)
        before = {p: p.stat().st_size for p in paths.WORK_DIR.iterdir() if p.is_file()}
        result: dict[str, Any] = {}     # "ok": gdown's return, or "error": what it raised

        def run() -> None:
            try:
                # gdown checks `cancel` between chunks and raises, closing its temporary file
                result["ok"] = gdown.download(url, str(partial), quiet=True, cancel=self.cancel)
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        start = time.time()
        while t.is_alive():
            time.sleep(0.5)
            got = 0
            try:
                for p in paths.WORK_DIR.iterdir():
                    if p.is_file():
                        got += max(0, p.stat().st_size - before.get(p, 0))
            except OSError:
                pass
            rate = got / max(time.time() - start, 0.001)
            self.ui.progress(None, f"Downloading {label}: {util.human(got)}  ({util.human(rate)}/s)")
            if self.cancel.is_set():
                t.join(timeout=10)      # let gdown notice and close its file so the leftover can be deleted
                break
        if self.cancel.is_set():
            self._remove_gdown_leftovers(partial)
            raise Cancelled()
        if result.get("ok") and partial.exists():
            os.replace(partial, archive)
            return
        if "error" in result:
            self.ui.log(f"Automatic download failed: {type(result['error']).__name__}: {result['error']}")
        self.manual_download(file_id, archive, label)

    @staticmethod
    def _remove_gdown_leftovers(partial: Path) -> None:
        """Delete the temporary files gdown leaves after a failed or cancelled download (<name><8 chars>.part)."""
        for leftover in partial.parent.glob(f"{partial.name}????????.part"):
            try:
                leftover.unlink()
            except OSError:
                pass            # still open (Windows): the next download tries again

    def manual_download(self, file_id: str, archive: Path, label: str) -> None:
        view = f"https://drive.google.com/file/d/{file_id}/view"
        downloads = paths.DOWNLOADS
        winapi.open_url(view)
        while True:
            self.ui.progress(None, "Waiting for you to download it in your browser...")
            self.ui.wait_for_user(
                "Download it in your browser",
                f"Google Drive blocked the automatic download of the {label}. That's normal for big files.\n\n"
                "1. A browser tab just opened on the file.\n"
                "2. Click Download. If Drive says it can't scan the file for viruses, click \"Download anyway\".\n"
                "3. Wait until the download FINISHES, then click the button below.",
                "It's downloaded",
                [("Open download page again", lambda: winapi.open_url(view)),
                 ("Open Downloads folder", lambda: winapi.open_path(downloads))])
            self._stop_if_cancelled()
            cands = sorted(downloads.glob("*.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
            if not cands:
                self.ui.tell(f"No .tar.gz file found in {downloads} yet. Is it still downloading?\n\n"
                             "Click OK when it's finished.")
                continue
            found = cands[0]
            if self.ui.ask(f"Use {found.name} ({util.human(found.stat().st_size)})?", True):
                shutil.move(str(found), str(archive))
                self.ui.log(f"Using {found.name}")
                return

    def _sha(self, path: Path, what: str) -> str:
        """SHA-256 of a file with a progress readout; cancellable."""
        last = 0.0

        def progress(fraction: float) -> None:
            nonlocal last
            self._stop_if_cancelled()
            if time.time() - last > 0.2:
                last = time.time()
                self.ui.progress(fraction, f"Checking {what}...")
        return util.sha256_file(path, progress)

    def find_in_downloads(self, expected: str | None, size: int | None, label: str) -> Path | None:
        """A file in Downloads that is this archive (same SHA-256), newest first; None without a checksum.

        Only .gz files of the recorded size are hashed, when the size is known
        (builds before it was recorded hash every .gz there).
        """
        if not expected or not paths.DOWNLOADS.is_dir():
            return None
        cands = [f for f in paths.DOWNLOADS.glob("*.gz") if f.is_file() and (size is None or f.stat().st_size == size)]
        for f in sorted(cands, key=lambda f: f.stat().st_mtime, reverse=True):
            if self._sha(f, f"{f.name} in Downloads") == expected.lower():
                return f
        return None

    def obtain(self, file_id: str, archive: Path, label: str, expected: str | None, size: int | None) -> None:
        """Put the full pack or the update at `archive`, checked: the player's file, a copy in Downloads, or Drive.

        Inputs:
            expected / size: the SHA-256 and size recorded when it was packed (None: unknown).

        The picked file is copied (it may be on a USB stick, and stays theirs);
        one found in Downloads is moved, as the browser fallback does. A file
        the player picked that is neither the pack nor the update stops the install.
        """
        paths.WORK_DIR.mkdir(parents=True, exist_ok=True)
        if self.pack_file:
            if expected:
                if self._pack_file_sha is None:
                    self._pack_file_sha = self._sha(self.pack_file, f"your file {self.pack_file.name}")
                use = self._pack_file_sha == expected.lower()
                if not use and self._pack_file_sha not in {(self.req.get(k) or "").lower()
                                                          for k in ("base_sha256", "update_sha256")}:
                    raise Abort(f"The file you picked ({self.pack_file.name}) isn't {self.cfg['author']}'s mod "
                                "pack or update for this app. It wasn't changed. Pick the right file, or clear "
                                "it to download from Drive.")
            else:
                use = label == "mod pack"           # nothing to check it against: taken as the full pack
                if use:
                    self.ui.log(f"No checksum recorded for the {label}; your file can't be checked.")
            if use:
                self.ui.progress(None, f"Copying {self.pack_file.name}...")
                shutil.copyfile(self.pack_file, archive)
                self.ui.log(f"Using your copy of the {label}: {self.pack_file.name} (no download needed).")
                return
        found = self.find_in_downloads(expected, size, label)
        if found:
            shutil.move(str(found), str(archive))
            self.ui.log(f"Found the {label} in Downloads ({found.name}): no download needed. It was moved "
                        f"into {paths.WORK_DIR.name}.")
            return
        self.download(file_id, archive, label)
        self.check_download(archive, expected, label)

    def check_download(self, archive: Path, expected: str | None, label: str) -> None:
        """Compare an archive with the SHA-256 recorded when it was packed (requirements.json).

        Inputs:
            expected: The recorded hex digest; None when there is none (a pack
                recorded with record_baseline.bat, or an exe built before
                checksums), which skips the check.

        Side effects: A mismatch deletes the archive, so the next run downloads
            it again, and stops the install.
        """
        if not expected:
            self.ui.log(f"No checksum recorded for the {label}; skipping the integrity check.")
            return
        if self._sha(archive, f"the {label}") == expected.lower():
            self.ui.log(f"The {label} matches the one {self.cfg['author']} packed.")
            return
        archive.unlink()
        raise Abort(f"The downloaded {label} doesn't match the one {self.cfg['author']} packed: it's "
                    "incomplete, damaged, or a different file. It was deleted; click Start to download it "
                    f"again. If this keeps happening, ask {self.cfg['author']} for the latest app: it and "
                    "the file on Drive may be out of step.")

    def extract(self, archive: Path, dest: Path, keep: Callable[[str], bool] | None = None) -> None:
        """Unpack a .tar.gz into a fresh dest. Plain files and folders only, all inside dest.

        keep: unpack only the entries whose name it accepts (repair: some mods); None unpacks all.

        Every entry is checked before it's written, on every Python: tarfile's
        "data" filter is missing before 3.10.12 / 3.11.4, so the check can't
        rely on it. A bad entry deletes the archive (so a retry downloads it
        again) and stops the install.
        """
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        total = archive.stat().st_size
        try:
            with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r:gz") as tar:
                self._extract_members(tar, raw, total, dest, keep)
        except util.UnsafeArchive as e:
            archive.unlink()
            raise Abort(f"{archive.name} contains something that can't be unpacked safely ({e}). It was "
                        f"deleted; don't use another copy of it. Tell {self.cfg['author']}.") from e
        self.ui.progress(1, "Unpacked.")

    def _extract_members(self, tar: tarfile.TarFile, raw: BinaryIO, total: int, dest: Path,
                         keep: Callable[[str], bool] | None = None) -> None:
        last = 0.0
        for member in tar:
            self._stop_if_cancelled()
            if keep is not None and not keep(member.name):
                continue
            if not (member.isfile() or member.isdir()):
                raise util.UnsafeArchive(f"{member.name!r} is a link or special file")
            util.safe_member_path(dest, member.name)
            if hasattr(tarfile, "data_filter"):
                tar.extract(member, dest, filter="data")
            else:
                tar.extract(member, dest)
            now = time.time()
            if now - last > 0.2:
                last = now
                self.ui.progress(raw.tell() / total, f"Unpacking: {member.name[-70:]}")

    @staticmethod
    def find_pack_root(extract_dir: Path) -> Path:
        root = extract_dir
        while True:
            entries = [e for e in root.iterdir() if not e.name.startswith(vortex.SKIP_PREFIXES)]
            if len(entries) == 1 and entries[0].is_dir():
                root = entries[0]
            else:
                return root

    @staticmethod
    def zip_folder(folder: Path, dest_zip: Path) -> None:
        """Accepts pre-1980 timestamps (some mods ship 1970 dates) and long Windows paths."""
        import zipfile
        base = str(folder)
        if winapi.IS_WINDOWS and not base.startswith("\\\\?\\"):
            base = "\\\\?\\" + os.path.abspath(base)
        part = dest_zip.with_name(dest_zip.name + ".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=1,
                             allowZip64=True, strict_timestamps=False) as zf:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames.sort()
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    zf.write(full, os.path.relpath(full, base))
        os.replace(part, dest_zip)

    @staticmethod
    def lone_archive(folder: Path) -> Path | None:
        entries = [e for e in folder.iterdir() if not e.name.startswith("__")]
        if len(entries) == 1 and entries[0].is_file() and entries[0].suffix.lower() in vortex.ARCHIVE_EXTS:
            return entries[0]
        return None

    def build_zips(self, root: Path, zip_dir: Path) -> int:
        zip_dir.mkdir(parents=True, exist_ok=True)
        mods = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(vortex.SKIP_PREFIXES))
        for i, mod in enumerate(mods, 1):
            self._stop_if_cancelled()
            self.ui.progress(i / max(len(mods), 1), f"Preparing {i}/{len(mods)}: {vortex.nice_mod_name(mod.name)}")
            inner = self.lone_archive(mod)
            for ext in vortex.ARCHIVE_EXTS:
                old = zip_dir / f"{mod.name}{ext}"
                if old.exists():
                    old.unlink()
            if inner:
                shutil.copy2(inner, zip_dir / f"{mod.name}{inner.suffix.lower()}")
                self.ui.log(f"{mod.name}: contains its own archive, passing it to Vortex directly")
            else:
                self.zip_folder(mod, zip_dir / f"{mod.name}.zip")
        return len(mods)

    def get_base(self) -> StepResult:
        if paths.BASE_READY.exists() and paths.BASE_READY.read_text(encoding="locale").strip() == self.base:
            self.ui.log("Found mods from a previous run, skipping the full download.")
            return "skipped"
        if paths.ZIP_DIR.exists():
            shutil.rmtree(paths.ZIP_DIR)
        if paths.ARCHIVE.exists() and (not paths.ARCHIVE_ID.exists()
                                      or paths.ARCHIVE_ID.read_text(encoding="locale").strip() != self.base):
            paths.ARCHIVE.unlink()
        if paths.ARCHIVE.exists():
            self.ui.log("Already downloaded, skipping.")
            return "skipped"
        self.obtain(self.cfg["drive_file_id"], paths.ARCHIVE, "mod pack", self.req.get("base_sha256"),
                    self.req.get("base_size"))
        paths.ARCHIVE_ID.write_text(self.base, encoding="locale")
        return None

    def unpack_base(self) -> StepResult:
        if paths.BASE_READY.exists() and paths.BASE_READY.read_text(encoding="locale").strip() == self.base:
            return "skipped"
        self._space_check(paths.ARCHIVE)
        self.extract(paths.ARCHIVE, paths.EXTRACT_DIR)
        return None

    def prepare_base(self) -> StepResult:
        if paths.BASE_READY.exists() and paths.BASE_READY.read_text(encoding="locale").strip() == self.base:
            return "skipped"
        count = self.build_zips(self.find_pack_root(paths.EXTRACT_DIR), paths.ZIP_DIR)
        shutil.rmtree(paths.EXTRACT_DIR, ignore_errors=True)
        if not count:
            raise Abort(f"The pack looks empty. Tell {self.cfg['author']}.")
        paths.BASE_READY.write_text(self.base, encoding="locale")
        self.ui.log(f"{count} mods ready.")
        return None

    @staticmethod
    def removed_mods(info: dict[str, Any]) -> list[str]:
        """The update's removed mods; raises UnsafeArchive unless each is a plain folder name.

        Each name becomes a file name in ZIP_DIR that is deleted, so a name with
        a folder, "..", or a drive in it would delete a file outside ZIP_DIR.
        """
        removed = info.get("removed", [])
        if not isinstance(removed, list):
            raise util.UnsafeArchive(f"'removed' is a {type(removed).__name__}, not a list")
        for name in removed:
            if not isinstance(name, str) or name in ("", ".", "..") or any(c in name for c in "/\\:"):
                raise util.UnsafeArchive(f"{name!r} isn't a mod folder name")
        return removed

    def _hand_off_update(self, mods: Sequence[str]) -> None:
        """Update only: copy the update's zips from ToVortex into UPDATE_ZIPS, the folder the player drags from."""
        shutil.rmtree(paths.UPDATE_ZIPS, ignore_errors=True)
        paths.UPDATE_ZIPS.mkdir(parents=True)
        for mod in mods:
            for ext in vortex.ARCHIVE_EXTS:
                if (paths.ZIP_DIR / f"{mod}{ext}").exists():
                    shutil.copy2(paths.ZIP_DIR / f"{mod}{ext}", paths.UPDATE_ZIPS / f"{mod}{ext}")

    def _update_ready(self) -> dict[str, Any] | None:
        """What UPDATE_READY recorded, if ToVortex already holds this exe's update."""
        ready = util.read_json(paths.UPDATE_READY, {}) or {}
        version = self.req.get("update_version")
        if not version or not isinstance(ready, dict) or ready.get("version") != version:
            return None
        info, mods = ready.get("info"), ready.get("mods")
        if not isinstance(info, dict) or not isinstance(mods, list):
            return None
        try:
            self.removed_mods(info)
        except util.UnsafeArchive:
            return None
        return ready

    def get_update(self) -> StepResult:
        """Apply the update to ToVortex (new and changed mods' zips in, removed ones out).

        ToVortex keeps everything, so a later Full install needn't download
        again; in "update" mode the player is handed just the update's zips
        (UPDATE_ZIPS). Already applied (UPDATE_READY names this update): skipped.
        """
        ready = self._update_ready()
        if ready:
            self.update_info = ready["info"]
            if self.mode == "update":
                self._hand_off_update(ready["mods"])
            self.ui.log("Found the update from a previous run, skipping the download.")
            return "skipped"
        reuse = False
        if paths.UPDATE_ARCHIVE.exists():
            reuse = self.ui.ask(f"Found an update you already downloaded "
                                f"({util.human(paths.UPDATE_ARCHIVE.stat().st_size)}). Use it?\n\n"
                                f"Say No only if {self.cfg['author']} released a newer update since then.", True)
            if not reuse:
                paths.UPDATE_ARCHIVE.unlink()
        if reuse:
            self.check_download(paths.UPDATE_ARCHIVE, self.req.get("update_sha256"), "update")
        else:
            self.obtain(self.cfg["update_file_id"], paths.UPDATE_ARCHIVE, "update", self.req.get("update_sha256"),
                        self.req.get("update_size"))
        self.extract(paths.UPDATE_ARCHIVE, paths.UPDATE_EXTRACT)
        root = self.find_pack_root(paths.UPDATE_EXTRACT)
        info: dict[str, Any] = {"added": [], "changed": [], "removed": []}
        info_file = root / paths.UPDATE_INFO
        if info_file.exists():
            info.update(json.loads(info_file.read_text(encoding="locale")))
        try:
            removed = self.removed_mods(info)
        except util.UnsafeArchive as e:
            paths.UPDATE_ARCHIVE.unlink()
            shutil.rmtree(paths.UPDATE_EXTRACT, ignore_errors=True)
            raise Abort(f"The update's list of removed mods can't be used safely ({e}). It was deleted; "
                        f"don't use another copy of it. Tell {self.cfg['author']}.") from e
        paths.ZIP_DIR.mkdir(parents=True, exist_ok=True)
        mods = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(vortex.SKIP_PREFIXES))
        count = self.build_zips(root, paths.ZIP_DIR)
        for name in removed:
            for ext in vortex.ARCHIVE_EXTS:
                stale = paths.ZIP_DIR / f"{name}{ext}"
                if stale.exists():
                    stale.unlink()
        shutil.rmtree(paths.UPDATE_EXTRACT, ignore_errors=True)
        paths.UPDATE_ARCHIVE.unlink()
        util.write_json(paths.UPDATE_READY, {"version": self.req.get("update_version"), "info": info, "mods": mods})
        if self.mode == "update":
            self._hand_off_update(mods)
        self.update_info = info
        self.ui.log(f"{count} new or updated mods ready.")
        return None

    def all_mods_in_place(self) -> bool:
        """Every plugin the pack enables is in Data, and every file its mods deployed (files.json) is in the game.

        False without a game, a pack load order or a files.json (an older build
        can't tell), so the install then runs in full.
        """
        inventory = config.load_inventory()
        plugins_txt = paths.PACKINFO / "plugins.txt"
        if not self.game or not inventory or not plugins_txt.exists():
            return False
        if any(not (self.game / "Data" / p).exists() for p in skyrim.enabled_plugins(plugins_txt)):
            return False
        return all(f.level == "OK" for f in doctor.check_deployment(self.game, inventory))

    # -- repair: some mods again -----------------------------------------------------
    @staticmethod
    def _mod_of(name: str) -> str | None:
        """The mod folder an archive entry belongs to ("mods/<mod>/a.esp" -> "<mod>"); None outside one."""
        parts = name.replace("\\", "/").strip("/").split("/")
        if parts[0] == pack_mods.ARC_ROOT:
            parts = parts[1:]
        return parts[0] if len(parts) > 1 else None

    def _zips_from(self, archive: Path, mods: list[str]) -> list[str]:
        """Unpack just `mods` from a pack archive and zip each into REPAIR_DIR. Returns the ones it doesn't hold."""
        wanted = set(mods)
        self.extract(archive, paths.REPAIR_EXTRACT, keep=lambda name: self._mod_of(name) in wanted)
        root = paths.REPAIR_EXTRACT / pack_mods.ARC_ROOT
        if not root.is_dir():
            root = paths.REPAIR_EXTRACT
        self.build_zips(root, paths.REPAIR_DIR)
        shutil.rmtree(paths.REPAIR_EXTRACT, ignore_errors=True)
        return [m for m in mods if not any((paths.REPAIR_DIR / f"{m}{ext}").exists() for ext in vortex.ARCHIVE_EXTS)]

    def gather(self) -> StepResult:
        """A zip of each mod being repaired, in REPAIR_DIR: from ToVortex, else from the pack's archives.

        ToVortex counts only while this pack is what's installed (its zips are
        then this pack's). Otherwise the update comes first, since a mod it
        changed is older in the full pack; each archive is downloaded again if
        it's gone (the player is asked first) and checked against its SHA-256.
        """
        if not self.repair_mods:
            raise Abort("Nothing to repair.")
        shutil.rmtree(paths.REPAIR_DIR, ignore_errors=True)
        paths.REPAIR_DIR.mkdir(parents=True)
        need = []
        current = config.install_state(self.req) == "installed"
        for mod in self.repair_mods:
            made = next((paths.ZIP_DIR / f"{mod}{ext}" for ext in vortex.ARCHIVE_EXTS
                         if (paths.ZIP_DIR / f"{mod}{ext}").exists()), None) if current else None
            if made:
                shutil.copy2(made, paths.REPAIR_DIR / made.name)
                self.ui.log(f"{vortex.nice_mod_name(mod)}: ready from the last install")
            else:
                need.append(mod)
        sources = [(paths.ARCHIVE, self.cfg["drive_file_id"], "mod pack", self.req.get("base_sha256"),
                    self.req.get("base_size"))]
        if self.cfg.get("update_file_id"):
            sources.insert(0, (paths.UPDATE_ARCHIVE, self.cfg["update_file_id"], "update",
                               self.req.get("update_sha256"), self.req.get("update_size")))
        for archive, file_id, label, sha, size in sources:
            if not need:
                break
            self._stop_if_cancelled()
            if archive == paths.ARCHIVE and archive.exists() and (not paths.ARCHIVE_ID.exists()
                                                                  or paths.ARCHIVE_ID.read_text(encoding="locale")
                                                                  .strip() != self.base):
                archive.unlink()                # an older full pack's
            if archive.exists():
                self.check_download(archive, sha, label)
            else:
                names = "\n".join(f"- {vortex.nice_mod_name(m)}" for m in need)
                if not self.pack_file and not self.ui.ask(
                        f"To repair these mods, the {label} is needed again:\n\n{names}\n\nGet it now? "
                        "(A copy in Downloads is used if there is one; otherwise it's downloaded.)", True):
                    raise Abort(f"Repair stopped: the {label} isn't on this PC any more, and it's needed "
                                "for these mods.")
                self.obtain(file_id, archive, label, sha, size)
            if archive == paths.ARCHIVE:
                paths.ARCHIVE_ID.write_text(self.base, encoding="locale")
            before = len(need)
            need = self._zips_from(archive, need)
            self.ui.log(f"{before - len(need)} mod(s) taken from the {label}")
        if need:
            raise Abort("These mods aren't in the mod pack, so they can't be repaired from it:\n"
                        + "\n".join(f"- {vortex.nice_mod_name(m)}" for m in need)
                        + f"\n\nTell {self.cfg['author']}: the app and the pack on Drive may be out of step.")
        return None

    def verify_repair(self) -> StepResult:
        """Every file the repaired mods deployed on the maintainer's PC is now in the game folder."""
        inventory = {m: files for m, files in config.load_inventory().items() if m in self.repair_mods}
        if not self.game or not inventory:
            self.ui.log("Skipped the final check (no Skyrim folder, or no file list in this build).")
            return "skipped"
        problems = [f for f in doctor.check_deployment(self.game, inventory) if f.level != "OK"]
        if problems:
            for f in problems:
                self.ui.log(f"[{f.level}] {f.title}")
                for line in f.detail.splitlines():
                    self.ui.log(f"    {line}")
            raise Abort("Some repaired mods still aren't fully in the game:\n\n"
                        + "\n".join(f.detail for f in problems) + "\n\n" + problems[0].fix)
        self.ui.log(f"All {len(inventory)} repaired mod(s) are in place.")
        return None

    def vortex(self) -> StepResult:
        folder = {"repair": paths.REPAIR_DIR, "update": paths.UPDATE_ZIPS}.get(self.mode, paths.ZIP_DIR)
        zips = [f for f in folder.iterdir() if f.suffix.lower() in vortex.ARCHIVE_EXTS] \
            if folder.is_dir() else []
        removed = (self.update_info or {}).get("removed", []) if self.mode == "update" else []
        if not zips and not removed:
            self.ui.log("Nothing to install in Vortex this time.")
            return "skipped"
        winapi.open_path(folder)
        if not vortex.vortex_running() and not vortex.launch_vortex():
            self.ui.log("Couldn't find Vortex automatically. Please open it yourself.")
        body = (f"A folder with {len(zips)} mod file(s) just opened, and Vortex should be starting.\n\n"
                "1. In Vortex, make sure Skyrim Special Edition is the active game.\n"
                "2. Go to the Mods page.\n"
                "3. In the folder press Ctrl+A, then drag everything onto Vortex's\n"
                "    \"Drop File(s)\" box. Lots of mods? Do batches of about 20.\n"
                "4. If Vortex says a mod is already installed, choose Replace.\n"
                "5. When they're all installed: select all > Enable, then Deploy.")
        if removed:
            body += "\n6. Remove these mods in Vortex (select > Remove), then Deploy:\n" + \
                    "\n".join(f"      - {vortex.nice_mod_name(n)}" for n in removed)
        if self.mode == "repair":
            body += ("\n\nIf the Doctor said a mod's files were found in another folder, reinstalling doesn't "
                     "move them: in Vortex, set that mod's Mod Type to match "
                     f"{self.cfg['author']}'s (show the Mod Type column), then Deploy.")
        body += "\n\nThen CLOSE Vortex completely (check the system tray too)."
        self.ui.progress(None, "Waiting for you to finish in Vortex...")
        while True:
            self.ui.wait_for_user("Your turn: install in Vortex", body, "Done, Vortex is closed",
                                  [("Open the mod folder again", lambda: winapi.open_path(folder)),
                                   ("Open Vortex", vortex.launch_vortex)])
            self._stop_if_cancelled()
            if not vortex.vortex_running():
                return None
            self.ui.tell("Vortex is still running. Close it completely (check the icons by your "
                         "clock too), then click OK.")

    def order(self) -> StepResult:
        if not (paths.PACKINFO / "plugins.txt").exists():
            self.ui.log("No load order included in this pack.")
            return "skipped"
        if not paths.SKYRIM_APPDATA.is_dir():
            raise Abort("Couldn't find Skyrim's settings folder. Launch Skyrim SE once from Steam, "
                        "quit at the main menu, then try again.")
        for name in ("plugins.txt", "loadorder.txt"):
            if (paths.PACKINFO / name).exists():
                util.backup_and_copy(paths.PACKINFO / name, paths.SKYRIM_APPDATA / name)
                self.ui.log(f"Load order: restored {name} (yours backed up as .bak)")
        inis = self.req.get("inis", [])
        if inis and self.want_inis:
            for name in inis:
                if not (paths.PACKINFO / name).exists():
                    self.ui.log(f"Settings: {name} isn't in this build, skipped")
                    continue
                util.backup_and_copy(paths.PACKINFO / name, skyrim.ini_dir() / name)
                self.ui.log(f"Settings: applied {name} (yours backed up as .bak)")
        return None

    def verify(self) -> StepResult:
        game = self.game
        plugins_txt = paths.PACKINFO / "plugins.txt"
        if not game or not plugins_txt.exists():
            self.ui.log("Skipped the final check (no Skyrim folder or load order).")
            return "skipped"
        wanted = skyrim.enabled_plugins(plugins_txt)
        missing = [p for p in wanted if not (Path(game) / "Data" / p).exists()]
        if missing:
            self.ui.log(f"{len(missing)} of {len(wanted)} plugins are missing from the Data folder:")
            for p in missing[:25]:
                self.ui.log(f"    - {p}")
            raise Abort(f"{len(missing)} plugin(s) didn't make it into the game. Usually that means some "
                        "mods weren't enabled or Vortex didn't Deploy. In Vortex: Mods > select all > "
                        "Enable > Deploy, close Vortex, then click Install again. It'll skip straight "
                        "to this check.")
        self.ui.log(f"All {len(wanted)} plugins are in place.")

        # Every file the pack's mods deploy (files.json); builds without it check plugins only
        problems = [f for f in doctor.check_deployment(Path(game), config.load_inventory()) if f.level != "OK"]
        for f in problems:
            self.ui.log(f"[{f.level}] {f.title}")
            for line in f.detail.splitlines():
                self.ui.log(f"    {line}")
        if problems and not self.ui.ask(
                "Some of the pack's mod files aren't in the game:\n\n"
                + "\n".join(f"- {f.title}" for f in problems)
                + "\n\nThe log lists them. Usually Vortex didn't Deploy everything. Finish anyway?", False):
            raise Abort("Some mod files didn't make it into the game. In Vortex: Mods > select all > Enable > "
                        "Deploy, close Vortex, then click Install again. It'll skip straight to this check.")
        if not problems and config.load_inventory():
            self.ui.log("Every file from the pack's mods is in place.")
        return None

    # -- run ---------------------------------------------------------------------
    def run(self) -> None:
        paths.WORK_DIR.mkdir(parents=True, exist_ok=True)
        actions = {
            "check": self.check,
            "download": self.get_base,
            "unpack": self.unpack_base,
            "prepare": self.prepare_base,
            "update": self.get_update,
            "vortex": self.vortex,
            "order": self.order,
            "verify": self.verify_repair if self.mode == "repair" else self.verify,
            "gather": self.gather,
        }
        if self.mode == "update":
            shutil.rmtree(paths.UPDATE_ZIPS, ignore_errors=True)    # a hand-off from an earlier run
        steps = plan(self.mode)
        skip: frozenset[str] = frozenset()
        if self.mode != "repair" and "check" in steps:
            self._step("check", self.check)
            steps.remove("check")
            if self.all_mods_in_place() and self.ui.ask(
                    "Every mod in the pack is already in your game. Skip straight to setting the load order "
                    "and settings?\n\nSay No to install the mods again anyway.", True):
                skip = MOD_STEPS
                self.ui.log("All the pack's mods are already in the game: skipping to the load order and settings.")
        for key in steps:
            if key in skip:
                self.ui.step(key, "skipped")
                continue
            self._step(key, actions[key])
        if self.mode == "repair":           # some mods again: what's installed hasn't changed
            self.ui.progress(1, "Repaired!")
            return
        config.mark_installed(self.req)
        self.ui.progress(1, "All done!")
