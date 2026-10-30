"""The main window: sidebar, page switching, background work, status, and Crash Squatch wiring.

Purpose:
    Holds the pages and everything they share: running work off the GUI
    thread and posting results back (run_bg, post), the player's status
    (game found, install state), dialogs and toasts, and starting the game
    with Crash Squatch attached.

Main package:
    App. main() creates it and runs the Tk main loop.

Flow:
    1. Show the splash and gather the first status in the background: the game,
       the install state, the sync code, and whether the game matches the pack.
    2. Build the sidebar and every page; reveal the window.
    3. Drain the work queue on the GUI thread; refresh status on demand.
"""
import math
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TypeVar

import customtkinter as ctk

from whiney import config, crashsquatch, doctor, host, installer, paths, skyrim, vortex, winapi
from whiney.ui.pages.crash import CrashPage
from whiney.ui.pages.doctor import DoctorPage
from whiney.ui.pages.home import HomePage
from whiney.ui.pages.host import HostPage
from whiney.ui.pages.install import InstallPage
from whiney.ui.pages.manage import ManagePage
from whiney.ui.splash import Splash
from whiney.ui.theme import BG, CARD_HI, GOLD, GOLD_DIM, MUTED, PANEL, TITLE_FONT, F
from whiney.ui.widgets import AppStatus, Dialog, Page, Widget, label

T = TypeVar("T")


class App(ctk.CTk):
    NAV: list[tuple[str, str, type[Page]]] = [
           ("home", "⌂   Home", HomePage), ("install", "⇩   Install & Update", InstallPage),
           ("doctor", "✚   Doctor", DoctorPage), ("crash", "◉   Crash Squatch", CrashPage),
           ("host", "⇄   Host Server", HostPage), ("manage", "⚙   Manage", ManagePage)]

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(config.CONFIG["pack_name"])
        self.configure(fg_color=BG)
        self.geometry(self._centered(1100, 720))
        self.minsize(980, 640)
        ico = paths.ASSET_DIR / "icon.ico"
        if winapi.IS_WINDOWS and ico.exists():
            try:
                self.iconbitmap(str(ico))
            except tk.TclError:
                pass
        self.q: queue.Queue[Callable[[], object]] = queue.Queue()   # work to run on the GUI thread
        self.status: AppStatus = {}
        self.watcher: crashsquatch.CrashSquatcher | None = None
        self.pages: dict[str, Page] = {}
        self.current: str | None = None
        self._toast: Widget | None = None
        self.after(30, self._pump)

        self.splash = Splash(self, config.CONFIG["pack_name"])
        threading.Thread(target=self._startup, daemon=True).start()

    def _centered(self, w: int, h: int) -> str:
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        return f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 2 - 20, 0)}"

    # thread plumbing
    def post(self, fn: Callable[..., object], *args: Any, **kw: Any) -> None:
        self.q.put(lambda: fn(*args, **kw))

    def _pump(self) -> None:
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            self.report_callback_exception(*sys.exc_info())
        self.after(30, self._pump)

    def run_bg(self, fn: Callable[[], T], done: Callable[[T], object] | None = None) -> None:
        def work() -> None:
            try:
                res = fn()
            except Exception as e:
                traceback.print_exc()
                self.post(self.tell, "Something went wrong", f"{type(e).__name__}: {e}")
                return
            if done:
                self.post(done, res)
        threading.Thread(target=work, daemon=True).start()

    def report_callback_exception(self, exc: type[BaseException], val: BaseException,
                                  tb: TracebackType | None) -> None:
        traceback.print_exception(exc, val, tb)
        try:
            self.tell("Something went wrong", f"{exc.__name__}: {val}\n\nDetails were saved to "
                                              "Downloads\\Whiney\\app_log.txt.")
        except Exception:
            pass

    # startup
    def _startup(self) -> None:
        def say(text: str) -> None:
            self.post(self.splash.set_status, text)
        say("Looking for Skyrim and checking your mods...")
        status = self._gather_status()
        say("Reading your load order...")
        time.sleep(0.3)
        say("Ready.")
        self.post(self._startup_done, status)

    def _gather_status(self) -> AppStatus:
        req = config.load_requirements()
        game = skyrim.find_game_dir()
        return {"req": req, "game": game, "state": config.install_state(req),
                "sync": skyrim.sync_code(), "setup": self._setup_check(game, req),
                "mods_in_place": self._mods_in_place(game)}

    @staticmethod
    def _mods_in_place(game: Path | None) -> bool:
        """doctor.all_mods_in_place; False if it can't run."""
        try:
            return doctor.all_mods_in_place(game)
        except Exception:
            traceback.print_exc()
            return False

    @staticmethod
    def _setup_check(game: Path | None, req: dict[str, Any]) -> list[doctor.Finding] | None:
        """Does the game already match the pack (doctor.setup_check)? None without a game, or if it can't run."""
        if not game:
            return None
        try:
            return doctor.setup_check(game, req)
        except Exception:
            traceback.print_exc()
            return None

    def _startup_done(self, status: AppStatus) -> None:
        self.status = status
        self._build()
        self.splash.done_cb = self._reveal
        self.splash.finish()

    def _reveal(self) -> None:
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.deiconify()
        self.show("home")
        self._fade_in(0.0)
        if winapi.process_running(crashsquatch.GAME_EXE):
            def answered(watch: bool) -> None:
                if watch:
                    self.start_watch(launch=False)
            self.dialog("Skyrim is already running", "Want Crash Squatch to keep an eye on it?",
                        [("Watch it", True, "primary"), ("No thanks", False, "normal")], answered)

    def _fade_in(self, a: float) -> None:
        a = min(a + 0.08, 1.0)
        try:
            self.attributes("-alpha", a)
        except tk.TclError:
            return
        if a < 1:
            self.after(16, lambda: self._fade_in(a))

    def _build(self) -> None:
        side = ctk.CTkFrame(self, fg_color=PANEL, width=230, corner_radius=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        logo = tk.Canvas(side, width=56, height=56, bg=PANEL, highlightthickness=0)
        logo.pack(pady=(26, 6))
        self._draw_logo(logo, 28, 28)
        label(side, config.CONFIG["pack_name"], 15, GOLD, "bold", TITLE_FONT, anchor="center",
              justify="center", wraplength=200).pack(fill="x", padx=14)
        label(side, f"by {config.CONFIG['author']}", 11, MUTED, anchor="center").pack(fill="x", pady=(0, 18))
        self.nav_btns = {}
        for key, text, _ in self.NAV:
            b = ctk.CTkButton(side, text=text, anchor="w", font=F(14), height=42, corner_radius=8,
                              fg_color="transparent", hover_color=CARD_HI, text_color=MUTED,
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_btns[key] = b
        self.side_status = label(side, "", 11, MUTED, anchor="w", wraplength=200)
        self.side_status.pack(side="bottom", fill="x", padx=18, pady=16)

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)
        for key, _, cls in self.NAV:
            self.pages[key] = cls(self)
        self._update_side()

    def _draw_logo(self, c: tk.Canvas, cx: float, cy: float) -> None:
        c.create_oval(cx - 25, cy - 25, cx + 25, cy + 25, outline=GOLD_DIM, width=2)
        pts = []
        for k in range(16):
            a = k * math.pi / 8 - math.pi / 2
            r = 19 if k % 2 == 0 else (7 if k % 4 == 1 else 11)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        c.create_polygon(*pts, outline=GOLD, fill="", width=2)

    def _update_side(self) -> None:
        s = self.status
        game = "Skyrim found ✓" if s.get("game") else "Skyrim not found"
        pack = {"installed": "Pack installed ✓", "update": "Update available",
                "none": "Pack not installed"}[s.get("state", "none")]
        watch = "\nCrash Squatch: on" if self.watcher and self.watcher.active else ""
        self.side_status.configure(text=f"{game}\n{pack}{watch}")

    def show(self, key: str, run: bool = False) -> None:
        if self.current:
            self.pages[self.current].pack_forget()
            self.nav_btns[self.current].configure(fg_color="transparent", text_color=MUTED)
        self.current = key
        self.nav_btns[key].configure(fg_color=CARD_HI, text_color=GOLD)
        page = self.pages[key]
        page.pack(fill="both", expand=True)
        page.on_show()
        if run and hasattr(page, "run"):
            page.run()

    def repair(self, mods: Sequence[str]) -> None:
        """Open Install & Update and reinstall just these pack mods (the Doctor's Repair button)."""
        self.show("install")
        page = self.pages["install"]
        assert isinstance(page, InstallPage)
        page.repair(mods)

    def apply_load_order(self) -> None:
        """Set the pack's load order, and the INIs if the player wants them, without installing anything.

        Offered by Home and the Doctor only when every pack mod is already in
        the game. Vortex must be closed: it rewrites plugins.txt while open.
        """
        if vortex.vortex_running():
            self.tell("Close Vortex first", "Vortex rewrites the load order while it's open. Close it "
                                            "completely (check the icons by your clock too), then try again.")
            return
        req = self.status.get("req") or config.load_requirements()
        author = config.CONFIG["author"]
        message = ("Every mod in the pack is already in your game, so only the load order needs setting. "
                   "Yours is kept as plugins.txt.bak (Manage > restore settings puts it back).")
        if req.get("inis"):
            buttons: list[tuple[str, Any, str]] = [("Load order + settings", "inis", "primary"),
                                                   ("Load order only", "order", "normal"), ("Cancel", None, "normal")]
            message += f"\n\nAlso use {author}'s game settings (INIs)? Yours are kept as .bak too."
        else:
            buttons = [("Set load order", "order", "primary"), ("Cancel", None, "normal")]

        def work(choice: str) -> tuple[list[str], str | None]:
            """(what was applied, or the reason it couldn't be)."""
            lines: list[str] = []
            try:
                installer.apply_load_order(req, choice == "inis", lines.append)
            except installer.Abort as e:
                return lines, str(e)
            return lines, None

        def done(result: tuple[list[str], str | None]) -> None:
            lines, error = result
            if error:
                self.tell("Couldn't set the load order", error)
                return
            self.refresh_status()
            page = self.pages["doctor"]
            if self.current == "doctor" and isinstance(page, DoctorPage):
                page.run()
            self.tell("Load order set", "\n".join(lines) + "\n\nIn Vortex > Plugins, keep Autosort OFF so "
                                        "it keeps this order.")

        def go(choice: str | None) -> None:
            if choice:
                self.run_bg(lambda: work(choice), done)
        self.dialog("Use the pack's load order?", message, buttons, go)

    def refresh_status(self) -> None:
        def done(status: AppStatus) -> None:
            self.status = status
            self._update_side()
            if self.current in ("home", "manage"):
                self.pages[self.current].on_show()
        self.run_bg(self._gather_status, done)

    # game + Crash Squatch
    def play(self, mode: Literal["skse", "together"] = "skse") -> None:
        """Start a session: "skse" is single-player through SKSE, "together" the Skyrim Together client."""
        game = self.status.get("game")
        if not game:
            self.tell("Skyrim not found", "Set the game folder in Manage first.")
            return
        launcher = None
        if mode == "together":
            launcher = host.find_client(game)
            if launcher is None:
                self.tell("Skyrim Together not found",
                          "Install the Skyrim Together Reborn mod (it's in the pack) and Deploy in Vortex.")
                return
        if self.status.get("state") == "none":
            self.dialog("Pack not installed", "The mod pack isn't installed yet. Play anyway?",
                        [("Play anyway", True, "normal"), ("Install first", False, "primary")],
                        lambda yes: self.start_watch(True, launcher) if yes else self.show("install"))
            return
        self.start_watch(True, launcher)

    def start_watch(self, launch: bool = True, launcher: Path | None = None) -> None:
        if self.watcher and self.watcher.active:
            self.show("crash")
            return
        if launch and vortex.vortex_running():
            self.toast("Tip: close Vortex while playing")
        self.watcher = crashsquatch.CrashSquatcher(self.status.get("game"), lambda ev: self.post(self._watch_event, ev),
                                               launcher=launcher)
        try:
            self.watcher.start(launch=launch)
        except OSError as e:
            self.tell("Couldn't start Skyrim", str(e))
            return
        self.show("crash")
        self._update_side()

    def _watch_event(self, ev: crashsquatch.Status | crashsquatch.CrashEvent) -> None:
        self.pages["crash"].on_event(ev)
        if isinstance(ev, crashsquatch.Status) and ev.state == "stopped":
            self._update_side()
        if isinstance(ev, crashsquatch.CrashEvent) and ev.kind in ("crash", "hang"):
            self.bring_to_front()
            self.show("crash")
            self.pages["crash"].select(ev)
            self.bell()

    # small UI helpers
    def bring_to_front(self) -> None:
        self.deiconify()
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(1500, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def dialog(self, title: str, message: str, buttons: Sequence[tuple[str, Any, str]],
               on_close: Callable[[Any], object]) -> None:
        Dialog(self, title, message, buttons, on_close)

    def tell(self, title: str, message: str) -> None:
        Dialog(self, title, message, [("OK", True, "primary")], lambda v: None)

    def copy(self, text: str, note: str = "Copied") -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toast(note)

    def toast(self, text: str) -> None:
        if self._toast:
            self._toast.destroy()
        t = ctk.CTkLabel(self.content, text=f"   {text}   ", font=F(13), text_color="#1a1406",
                         fg_color=GOLD, corner_radius=8, height=34)
        t.place(relx=0.5, rely=1.0, y=-24, anchor="s")
        self._toast = t
        self.after(2600, lambda: t.destroy() if t.winfo_exists() else None)


def main() -> None:
    app = App()
    app.mainloop()
