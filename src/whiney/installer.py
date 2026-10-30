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

from whiney import config, doctor, paths, skyrim, util, vortex, winapi

STEP_NAMES = {
    "check":    "Check your PC",
    "download": "Download the mod pack",
    "unpack":   "Unpack it",
    "prepare":  "Prepare mods for Vortex",
    "update":   "Get the latest update",
    "vortex":   "Install in Vortex (your turn)",
    "order":    "Set load order & settings",
    "verify":   "Make sure everything's in place",
}


Mode = Literal["fresh", "update"]     # full pack (+ update), or the update only
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
    if mode == "update":
        steps = ["check"] + (["update"] if has_update else []) + ["vortex", "order", "verify"]
    else:
        steps = ["check", "download", "unpack", "prepare"] + (["update"] if has_update else []) \
                + ["vortex", "order", "verify"]
    return steps


class Installer:
    def __init__(self, ui: InstallerUI, mode: Mode, game: Path | str | None = None, apply_inis: bool = True,
                 cancel: threading.Event | None = None) -> None:
        """mode: 'fresh' (full pack [+update]) or 'update' (update only).

        cancel: a threading.Event the GUI sets to cancel; checked between steps,
            during downloads, unpacking, zipping and checksums, and after every wait.
        """
        self.ui, self.mode = ui, mode
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
        last = 0.0

        def progress(fraction: float) -> None:
            nonlocal last
            self._stop_if_cancelled()
            if time.time() - last > 0.2:
                last = time.time()
                self.ui.progress(fraction, f"Checking the {label}...")

        if util.sha256_file(archive, progress) == expected.lower():
            self.ui.log(f"The {label} matches the one {self.cfg['author']} packed.")
            return
        archive.unlink()
        raise Abort(f"The downloaded {label} doesn't match the one {self.cfg['author']} packed: it's "
                    "incomplete, damaged, or a different file. It was deleted; click Start to download it "
                    f"again. If this keeps happening, ask {self.cfg['author']} for the latest app: it and "
                    "the file on Drive may be out of step.")

    def extract(self, archive: Path, dest: Path) -> None:
        """Unpack a .tar.gz into a fresh dest. Plain files and folders only, all inside dest.

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
                self._extract_members(tar, raw, total, dest)
        except util.UnsafeArchive as e:
            archive.unlink()
            raise Abort(f"{archive.name} contains something that can't be unpacked safely ({e}). It was "
                        f"deleted; don't use another copy of it. Tell {self.cfg['author']}.") from e
        self.ui.progress(1, "Unpacked.")

    def _extract_members(self, tar: tarfile.TarFile, raw: BinaryIO, total: int, dest: Path) -> None:
        last = 0.0
        for member in tar:
            self._stop_if_cancelled()
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
        self.download(self.cfg["drive_file_id"], paths.ARCHIVE, "mod pack")
        self.check_download(paths.ARCHIVE, self.req.get("base_sha256"), "mod pack")
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

    def get_update(self) -> StepResult:
        reuse = False
        if paths.UPDATE_ARCHIVE.exists():
            reuse = self.ui.ask(f"Found an update you already downloaded "
                                f"({util.human(paths.UPDATE_ARCHIVE.stat().st_size)}). Use it?\n\n"
                                f"Say No only if {self.cfg['author']} released a newer update since then.", True)
            if not reuse:
                paths.UPDATE_ARCHIVE.unlink()
        if not reuse:
            self.download(self.cfg["update_file_id"], paths.UPDATE_ARCHIVE, "update")
        self.check_download(paths.UPDATE_ARCHIVE, self.req.get("update_sha256"), "update")
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
        count = self.build_zips(root, paths.ZIP_DIR)
        for name in removed:
            for ext in vortex.ARCHIVE_EXTS:
                stale = paths.ZIP_DIR / f"{name}{ext}"
                if stale.exists():
                    stale.unlink()
        shutil.rmtree(paths.UPDATE_EXTRACT, ignore_errors=True)
        paths.UPDATE_ARCHIVE.unlink()
        self.update_info = info
        self.ui.log(f"{count} new or updated mods ready.")
        return None

    def vortex(self) -> StepResult:
        zips = [f for f in paths.ZIP_DIR.iterdir() if f.suffix.lower() in vortex.ARCHIVE_EXTS] \
            if paths.ZIP_DIR.is_dir() else []
        removed = (self.update_info or {}).get("removed", []) if self.mode == "update" else []
        if not zips and not removed:
            self.ui.log("Nothing to install in Vortex this time.")
            return "skipped"
        winapi.open_path(paths.ZIP_DIR)
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
        body += "\n\nThen CLOSE Vortex completely (check the system tray too)."
        self.ui.progress(None, "Waiting for you to finish in Vortex...")
        while True:
            self.ui.wait_for_user("Your turn: install in Vortex", body, "Done, Vortex is closed",
                                  [("Open the mod folder again", lambda: winapi.open_path(paths.ZIP_DIR)),
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
            "verify": self.verify,
        }
        if self.mode == "update":
            if paths.ZIP_DIR.exists():
                shutil.rmtree(paths.ZIP_DIR)
            paths.ZIP_DIR.mkdir(parents=True)
        for key in plan(self.mode):
            self._step(key, actions[key])
        config.mark_installed(self.req)
        self.ui.progress(1, "All done!")
