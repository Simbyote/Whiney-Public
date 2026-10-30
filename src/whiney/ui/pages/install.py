"""The Install & Update tab: runs the installer and shows its steps, log and progress.

Purpose:
    The installer is GUI-independent and runs on a worker thread; this page
    is its face. GuiBridge implements the installer's UI protocol and hops
    every call onto the GUI thread.

Main package:
    InstallPage; GuiBridge (installer.Installer's `ui`).

Flow:
    1. build(): mode choice, step list, log, progress, action area.
    2. start(): run installer.Installer(GuiBridge(...)) in the background.
    3. The bridge updates steps, log and progress; finished() reports the result.
    repair(mods), from the Doctor's Repair button, runs the installer's
    "repair" mode on just those mods and starts straight away.
    Cancel (shown while it runs) sets the installer's cancel event; it stops
    at the next safe point and a later Start resumes. "I already have the
    file" picks a copy of the pack (or update) to use instead of downloading.
"""
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog
from typing import Any, Literal

import customtkinter as ctk

from whiney import config, installer, paths, vortex, winapi
from whiney.ui.theme import CARD_HI, FAIL_C, GOLD, GOLD_DIM, LINE, MUTED, OK_C, PANEL, TEXT, F
from whiney.ui.widgets import AppShell, Card, Page, Widget, box, btn, label, set_on

StepState = Literal["active", "done", "skipped", "error", "cancelled"]


class InstallPage(Page):
    title = "Install & Update"
    subtitle = "Gets your Skyrim set up exactly like the pack. You'll do one drag-and-drop in Vortex."

    def build(self, body: Widget) -> None:
        top = Card(body)
        top.pack(fill="x")
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=14)
        label(row, "Mode", 13, MUTED).pack(side="left")
        self.mode = ctk.CTkSegmentedButton(row, values=["Full install", "Update only"], font=F(13),
                                           selected_color=GOLD_DIM, selected_hover_color=GOLD_DIM,
                                           unselected_color=CARD_HI, unselected_hover_color="#313744",
                                           command=lambda v: self.draw_steps())
        self.mode.pack(side="left", padx=(12, 0))
        self.inis = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text=f"Use {config.CONFIG['author']}'s game settings (INIs)", variable=self.inis,
                        font=F(13), text_color=TEXT, fg_color=GOLD_DIM, hover_color=GOLD,
                        border_color=LINE).pack(side="left", padx=(20, 0))
        self.start_btn = btn(row, "Start", self.start, "primary", width=130)
        self.start_btn.pack(side="right")
        self.cancel_btn = btn(row, "Cancel", self.ask_cancel, width=110)      # shown while running
        self.cancel_event = threading.Event()
        file_row = ctk.CTkFrame(top, fg_color="transparent")
        file_row.pack(fill="x", padx=18, pady=(0, 12))
        self.file_btn = btn(file_row, "I already have the file...", self.pick_file, "ghost", width=190, height=28)
        self.file_btn.pack(side="left")
        self.file_lbl = label(file_row, "Otherwise it's downloaded from Google Drive (a copy in Downloads is "
                                        "found automatically).", 12, MUTED)
        self.file_lbl.pack(side="left", padx=(10, 0))
        self.clear_file_btn = btn(file_row, "Don't use it", self.clear_file, "ghost", width=100, height=28)
        self.pack_file: Path | None = None

        mid = ctk.CTkFrame(body, fg_color="transparent")
        mid.pack(fill="both", expand=True, pady=(14, 0))
        mid.grid_columnconfigure(1, weight=1)
        mid.grid_rowconfigure(0, weight=1)

        self.steps_card = Card(mid, width=270)
        self.steps_card.grid(row=0, column=0, sticky="nsw")
        self.steps_card.grid_propagate(False)
        label(self.steps_card, "STEPS", 11, MUTED, "bold").pack(anchor="w", padx=18, pady=(14, 6))
        self.steps_box = ctk.CTkFrame(self.steps_card, fg_color="transparent")
        self.steps_box.pack(fill="both", expand=True, padx=12)
        self.step_rows: dict[str, tuple[Widget, Widget]] = {}      # step key -> (status dot, name)

        right = ctk.CTkFrame(mid, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        self.status_lbl = label(right, "Ready when you are.", 14, TEXT)
        self.status_lbl.pack(fill="x")
        self.bar = ctk.CTkProgressBar(right, progress_color=GOLD, fg_color=CARD_HI, height=8)
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(8, 12))

        self.action = Card(right, border_color=GOLD_DIM, border_width=2)
        self.action_title = label(self.action, "", 16, GOLD, "bold")
        self.action_title.pack(fill="x", padx=18, pady=(14, 4))
        self.action_body = label(self.action, "", 13, TEXT, wrap=40)
        self.action_body.pack(fill="x", padx=18)
        self.action_row = box(self.action)
        self.action_row.pack(fill="x", padx=18, pady=14)

        self.log = ctk.CTkTextbox(right, fg_color=PANEL, text_color=MUTED, border_color=LINE, border_width=1,
                                  font=ctk.CTkFont(family="Consolas" if winapi.IS_WINDOWS else "DejaVu Sans Mono",
                                                   size=12),
                                  corner_radius=10)
        self.log.pack(fill="both", expand=True)
        self.log.insert("end", "Details show up here while it works.\n")
        self.log.configure(state="disabled")
        self.running = False
        self.repair_mods: list[str] = []         # set by repair(): the next run is a repair of these

    def on_show(self) -> None:
        if not self.running:
            self.repair_mods = []
            self.mode.set("Update only" if self.app.status.get("state") == "update" else "Full install")
            self.draw_steps()

    def pick_file(self) -> None:
        """Choose a copy of the mod pack or update the player already has; it's checked when the install runs."""
        chosen = filedialog.askopenfilename(title=f"Pick {config.CONFIG['author']}'s mod pack or update file",
                                            filetypes=[("Mod pack", "*.tar.gz *.gz"), ("All files", "*.*")])
        if chosen:
            self.pack_file = Path(chosen)
            self.file_lbl.configure(text=f"Using {self.pack_file.name} if it matches (checked when you click "
                                         "Start). It's copied; yours stays where it is.", text_color=TEXT)
            self.clear_file_btn.pack(side="left", padx=(10, 0))

    def clear_file(self) -> None:
        self.pack_file = None
        self.file_lbl.configure(text="Otherwise it's downloaded from Google Drive (a copy in Downloads is found "
                                     "automatically).", text_color=MUTED)
        self.clear_file_btn.pack_forget()

    def mode_key(self) -> installer.Mode:
        if self.repair_mods:
            return "repair"
        return "update" if self.mode.get() == "Update only" else "fresh"

    def repair(self, mods: Sequence[str]) -> None:
        """Reinstall just these pack mods: gather their zips, the Vortex hand-off, then check them."""
        if self.running:
            self.app.tell("Busy", "An install is already running. Repair once it's finished.")
            return
        self.repair_mods = list(mods)
        self.start()
        if self.running:
            self.add_log("Repairing: " + ", ".join(vortex.nice_mod_name(m) for m in self.repair_mods))

    def draw_steps(self) -> None:
        for w in self.steps_box.winfo_children():
            w.destroy()
        self.step_rows = {}
        for key in installer.plan(self.mode_key()):
            r = ctk.CTkFrame(self.steps_box, fg_color="transparent")
            r.pack(fill="x", pady=3)
            dot = ctk.CTkLabel(r, text="○", width=22, font=F(15), text_color=MUTED)
            dot.pack(side="left")
            name = label(r, installer.STEP_NAMES[key], 13, MUTED)
            name.pack(side="left", padx=(4, 0))
            self.step_rows[key] = (dot, name)

    def set_step(self, key: str, state: StepState) -> None:
        if key not in self.step_rows:
            return
        dot, name = self.step_rows[key]
        look = {"active": ("◉", GOLD, TEXT), "done": ("✓", OK_C, TEXT), "skipped": ("✓", MUTED, MUTED),
                "error": ("✕", FAIL_C, FAIL_C), "cancelled": ("■", MUTED, MUTED)}[state]
        dot.configure(text=look[0], text_color=look[1])
        name.configure(text_color=look[2])
        if state == "active":
            self.status_lbl.configure(text=installer.STEP_NAMES[key] + "...")

    def add_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        try:
            with open(paths.WORK_DIR / "install_log.txt", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass

    def set_progress(self, frac: float | None, text: str | None) -> None:
        if frac is None:
            if self.bar.cget("mode") != "indeterminate":
                self.bar.configure(mode="indeterminate")
                self.bar.start()
        else:
            if self.bar.cget("mode") != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate")
            self.bar.set(frac)
        if text:
            self.status_lbl.configure(text=text)

    def show_action(self, title: str, body: str, button: str,
                    extras: Sequence[tuple[str, Callable[[], object]]], done: Callable[[], object]) -> None:
        self.action_title.configure(text=title)
        self.action_body.configure(text=body)
        for w in self.action_row.winfo_children():
            w.destroy()

        def finish() -> None:
            self.action.pack_forget()
            done()
        btn(self.action_row, button, finish, "primary").pack(side="left")
        for text, fn in extras:
            btn(self.action_row, text, fn).pack(side="left", padx=(8, 0))
        self.action.pack(fill="x", pady=(0, 12), before=self.log)
        self.app.bring_to_front()

    def start(self) -> None:
        if self.running:
            return
        game = self.app.status.get("game")
        if not config.CONFIG.get("drive_file_id") or config.CONFIG["drive_file_id"] == "PASTE_FILE_ID_HERE":
            self.app.tell("Not set up", "This copy of the app has no download link built in. "
                                        f"Ask {config.CONFIG['author']} for a proper build.")
            return
        mode = self.mode_key()
        self.running = True
        set_on(self.start_btn, False)
        self.start_btn.configure(text="Working...")
        self.cancel_event = threading.Event()
        set_on(self.cancel_btn, True)
        self.cancel_btn.configure(text="Cancel")
        self.cancel_btn.pack(side="right", padx=(0, 8))
        self.mode.configure(state="disabled")
        set_on(self.file_btn, False)
        set_on(self.clear_file_btn, False)
        self.draw_steps()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        try:
            paths.WORK_DIR.mkdir(parents=True, exist_ok=True)
            (paths.WORK_DIR / "install_log.txt").write_text(
                f"{config.CONFIG['pack_name']} install log {time.strftime('%Y-%m-%d %H:%M')} ({mode})\n",
                encoding="utf-8")
        except OSError:
            pass
        bridge = GuiBridge(self.app, self, self.cancel_event)
        job = installer.Installer(bridge, mode, game=game, apply_inis=self.inis.get(), cancel=self.cancel_event,
                                  repair=self.repair_mods, pack_file=self.pack_file)

        def work() -> None:
            try:
                job.run()
                self.app.post(self.finished, True, None)
            except installer.Cancelled as e:
                self.app.post(self.finished, False, str(e), True)
            except installer.Abort as e:
                self.app.post(self.finished, False, str(e))
            except Exception as e:
                tb = traceback.format_exc()
                self.app.post(self.add_log, tb)
                self.app.post(self.finished, False, f"Something went wrong: {type(e).__name__}: {e}")
        threading.Thread(target=work, daemon=True).start()

    def ask_cancel(self) -> None:
        """Confirm, then cancel: the installer stops at its next safe point (see installer.Cancelled)."""
        def go(yes: bool) -> None:
            if yes and self.running:
                self.cancel_event.set()
                set_on(self.cancel_btn, False)
                self.cancel_btn.configure(text="Cancelling...")
                self.status_lbl.configure(text="Cancelling at the next safe point...")
        self.app.dialog("Cancel the install?", "It stops at the next safe point. Finished steps are kept, so "
                                               "Start picks up where it stopped.",
                        [("Cancel install", True, "primary"), ("Keep going", False, "normal")], go)

    def finished(self, ok: bool, message: str | None, cancelled: bool = False) -> None:
        self.running = False
        repaired, self.repair_mods = self.repair_mods, []
        self.cancel_btn.pack_forget()
        set_on(self.start_btn, True)
        self.start_btn.configure(text="Start")
        self.mode.configure(state="normal")
        set_on(self.file_btn, True)
        set_on(self.clear_file_btn, True)
        self.action.pack_forget()
        self.set_progress(1 if ok else 0, None)
        if cancelled:
            self.status_lbl.configure(text="Cancelled.")
            self.add_log(f"\n{message}")
            self.app.toast("Install cancelled")
        elif ok and repaired:
            self.status_lbl.configure(text="Repaired!")
            self.add_log(f"\nRepaired {len(repaired)} mod(s).")
            self.app.refresh_status()
            self.app.tell("Repaired", f"{len(repaired)} mod(s) are back in the game. Run the Doctor again to "
                                      "check everything else.")
        elif ok:
            self.status_lbl.configure(text="All done!")
            self.add_log("\nAll done! In Vortex > Plugins, keep Autosort OFF so it keeps this order.")
            self.app.refresh_status()
            self.app.tell("All done!", "Your Skyrim is set up.\n\nOne last thing: open Vortex > Plugins and turn "
                                       "Autosort OFF so it keeps this load order. Then hit Play.")
        else:
            self.status_lbl.configure(text="Stopped.")
            self.add_log(f"\nStopped: {message}")
            self.app.tell("Repair stopped" if repaired else "Install stopped",
                          f"{message}\n\nThe log on this page (also saved to "
                          f"Downloads\\Whiney\\install_log.txt) shows what happened.")


class GuiBridge:
    """Installer UI protocol, safe to call from the worker thread."""

    def __init__(self, app: AppShell, page: InstallPage, cancel: threading.Event | None = None) -> None:
        self.app, self.page = app, page
        self.cancel = cancel or threading.Event()

    def step(self, key: str, state: StepState) -> None:
        self.app.post(self.page.set_step, key, state)
        if state == "active":
            self.app.post(self.page.add_log, f"\n» {installer.STEP_NAMES.get(key, key)}")

    def log(self, text: str) -> None:
        self.app.post(self.page.add_log, text)

    def progress(self, frac: float | None, text: str) -> None:
        self.app.post(self.page.set_progress, frac, text)

    def _blocking(self, show: Callable[[Callable[..., None]], object], cancellable: bool = False) -> Any:
        """Show something on the GUI thread and wait for the player's answer.

        cancellable: also stop waiting when the install is cancelled (raises
            installer.Cancelled). Only for the in-page action card: a dialog is
            modal, so the player answers it before they can reach Cancel.
        """
        ev, box = threading.Event(), {}      # box: the answer, handed from the GUI thread

        def done(value: Any = None) -> None:
            box["v"] = value
            ev.set()
        self.app.post(show, done)
        while not ev.wait(0.2):
            if cancellable and self.cancel.is_set():
                self.app.post(self.page.action.pack_forget)
                raise installer.Cancelled()
        return box.get("v")

    def ask(self, question: str, default: bool = True) -> bool:
        btns = [("Yes", True, "primary" if default else "normal"), ("No", False, "normal" if default else "primary")]
        return bool(self._blocking(lambda done: self.app.dialog("Quick question", question, btns, done)))

    def tell(self, message: str) -> None:
        self._blocking(lambda done: self.app.dialog("Heads up", message, [("OK", True, "primary")], done))

    def wait_for_user(self, title: str, body: str, button: str,
                      extras: Sequence[tuple[str, Callable[[], object]]]) -> None:
        self._blocking(lambda done: self.page.show_action(title, body, button, extras, lambda: done(True)),
                       cancellable=True)
