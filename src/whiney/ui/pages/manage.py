"""The Manage tab: save backups, restoring settings, freeing space, folders, uninstall.

Purpose:
    The housekeeping a player rarely needs, in one scrollable place, each
    action a thin call into manage.

Main package:
    ManagePage.

Flow:
    One section per job; refresh() redraws backups, settings and disk space after each action.
"""
import functools
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from whiney import config, manage, paths, skyrim, util, vortex, winapi
from whiney.ui.theme import CARD_HI, MUTED, TEXT
from whiney.ui.widgets import Card, Page, Widget, box, btn, label


class ManagePage(Page):
    title = "Manage"
    subtitle = "Backups, cleanup, folders, and removing the pack."

    def build(self, body: Widget) -> None:
        scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.saves = self._section(scroll, "Saves", "Back up your saves before updates or big changes.")
        r = ctk.CTkFrame(self.saves, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=(0, 6))
        btn(r, "Back up saves now", self.backup, "primary", width=170).pack(side="left")
        btn(r, "Open backups folder", lambda: self.open_dir(paths.SAVE_BACKUPS), width=170) \
            .pack(side="left", padx=(8, 0))
        self.backups_box = box(self.saves)
        self.backups_box.pack(fill="x", padx=20, pady=(0, 16))

        st = self._section(scroll, "Your original settings",
                           "Installing backs up your own load order and INI files. Put them back here.")
        r = ctk.CTkFrame(st, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=(0, 16))
        self.restore_btn = btn(r, "Restore my settings", self.restore_settings, width=170)
        self.restore_btn.pack(side="left")
        self.restore_lbl = label(r, "", 12, MUTED)
        self.restore_lbl.pack(side="left", padx=12)

        sp = self._section(scroll, "Disk space",
                           "Delete the downloaded pack files. Vortex keeps its own copy of the mods.")
        r = ctk.CTkFrame(sp, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=(0, 16))
        self.space_btn = btn(r, "Free up space", self.free_space, width=170)
        self.space_btn.pack(side="left")

        fo = self._section(scroll, "Folders", "")
        r = ctk.CTkFrame(fo, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=(0, 8))
        for text, fn in (("Game folder", lambda: self.open_dir(self.app.status.get("game"))),
                         ("Skyrim settings", lambda: self.open_dir(skyrim.ini_dir())),
                         ("Saves", lambda: self.open_dir(skyrim.saves_dir())),
                         ("Crash logs", lambda: self.open_dir(skyrim.my_games_dir() / "SKSE")),
                         ("App files", lambda: self.open_dir(paths.WORK_DIR))):
            btn(r, text, fn, width=130).pack(side="left", padx=(0, 8))
        r = ctk.CTkFrame(fo, fg_color="transparent")
        r.pack(fill="x", padx=20, pady=(0, 16))
        btn(r, "Change game folder", self.pick_game, "ghost", width=170).pack(side="left")
        btn(r, "Change Vortex mods folder", self.pick_staging, "ghost", width=200).pack(side="left", padx=(8, 0))
        self.paths_lbl = label(fo, "", 12, MUTED, wrap=44)
        self.paths_lbl.pack(fill="x", padx=20, pady=(0, 16))

        un = self._section(scroll, "Remove the pack",
                           "Restores your original settings, deletes the downloaded files, and tells you "
                           "how to remove the mods in Vortex.")
        btn(un, "Uninstall pack...", self.uninstall, "danger", width=170).pack(anchor="w", padx=20, pady=(0, 16))

    def _section(self, parent: Widget, title: str, sub: str | None) -> Widget:
        card = Card(parent)
        card.pack(fill="x", pady=(0, 12), padx=(0, 6))
        label(card, title, 15, TEXT, "bold").pack(anchor="w", padx=20, pady=(14, 0))
        if sub:
            label(card, sub, 12, MUTED, wrap=44).pack(fill="x", padx=20, pady=(2, 10))
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=8).pack()
        return card

    def on_show(self) -> None:
        for w in self.backups_box.winfo_children():
            w.destroy()
        backups = manage.list_save_backups()[:5]
        if backups:
            label(self.backups_box, "Recent backups:", 12, MUTED).pack(anchor="w", pady=(6, 2))
        for b in backups:
            r = ctk.CTkFrame(self.backups_box, fg_color=CARD_HI, corner_radius=8)
            r.pack(fill="x", pady=2)
            label(r, f"{b.stem.replace('Saves-', '')}   ·   {util.human(b.stat().st_size)}", 12, TEXT) \
                .pack(side="left", padx=12, pady=6)
            btn(r, "Restore", functools.partial(self.restore_saves, b), "ghost", width=80, height=28) \
                .pack(side="right", padx=6)
        baks = manage.settings_backups()
        self.restore_btn.configure(state="normal" if baks else "disabled")
        self.restore_lbl.configure(
            text=f"Backups found: {', '.join(p.name for p in baks)}" if baks else "No backups yet.")
        size = manage.download_space()
        self.space_btn.configure(text=f"Free up {util.human(size)}" if size else "Nothing to clean",
                                 state="normal" if size else "disabled")
        self.paths_lbl.configure(text=f"Game: {self.app.status.get('game') or 'not found'}\n"
                                      f"Vortex mods: {vortex.staging_dir()}")

    def open_dir(self, p: str | Path | None) -> None:
        if p and Path(p).exists():
            winapi.open_path(p)
        else:
            self.app.tell("Not found", f"That folder doesn't exist yet:\n{p}")

    def backup(self) -> None:
        def done(dest: Path | None) -> None:
            if dest:
                self.app.toast(f"Saves backed up: {dest.name}")
            else:
                self.app.tell("Nothing to back up", "No saves found yet.")
            self.on_show()
        self.app.run_bg(manage.backup_saves, done)

    def restore_saves(self, path: Path) -> None:
        def go(mode: str | None) -> None:
            if mode in ("merge", "replace"):
                done = ("Saves restored: the folder now matches the backup" if mode == "replace"
                        else "Saves restored: the backup's saves were added back")
                def restored(_: Path | None) -> None:
                    self.app.toast(f"{done} (your current saves were backed up first)")
                    self.on_show()
                self.app.run_bg(lambda: manage.restore_saves(path, replace=mode == "replace"), restored)
        self.app.dialog("Restore saves?",
                        f"Restore the backup from {path.stem.replace('Saves-', '')}? Your current saves get backed "
                        "up first either way, so nothing is lost.\n\n"
                        "Merge: adds the backup's saves back. Saves made since then stay.\n"
                        "Replace: the saves folder becomes exactly the backup. Saves made since then are "
                        "removed (they stay in the new backup).",
                        [("Merge", "merge", "primary"), ("Replace", "replace", "normal"),
                         ("Cancel", None, "normal")], go)

    def restore_settings(self) -> None:
        done = manage.restore_settings()
        self.app.refresh_status()
        self.app.toast(f"Restored: {', '.join(done)}" if done else "Nothing to restore")

    def free_space(self) -> None:
        freed = manage.free_space()
        self.app.toast(f"Freed {util.human(freed)}")
        self.on_show()

    def pick_game(self) -> None:
        p = filedialog.askdirectory(title="Pick the folder that contains SkyrimSE.exe")
        if not p:
            return
        if not skyrim.is_game_dir(p):
            self.app.tell("Wrong folder", "SkyrimSE.exe isn't in that folder.")
            return
        config.save_setting("game_dir", p)
        self.app.refresh_status()
        self.on_show()

    def pick_staging(self) -> None:
        p = filedialog.askdirectory(title="Pick Vortex's mods (staging) folder")
        if p:
            config.save_setting("staging_dir", p)
            self.on_show()

    def uninstall(self) -> None:
        def go(yes: bool) -> None:
            if not yes:
                return
            restored, freed = manage.uninstall()
            self.app.refresh_status()
            self.on_show()
            self.app.tell("Pack removed",
                          f"Restored: {', '.join(restored) or 'nothing to restore'}. Freed {util.human(freed)}.\n\n"
                          "Last step, in Vortex: Mods page > select the pack's mods > Remove > Deploy. "
                          "(Ctrl+A selects everything if you only have the pack installed.)")
        self.app.dialog("Uninstall the pack?", "This restores your own load order and settings and deletes the "
                                               "downloaded files. Your saves are not touched.",
                        [("Uninstall", True, "danger"), ("Cancel", False, "normal")], go)
