"""The Home tab: is the pack installed, which game, the sync code, the setup check, and the main actions.

Purpose:
    The first thing a player sees, so it answers "am I ready to play?" at a
    glance and offers the next step (Install, Play, Doctor), plus the
    players' installation guide (release/README.txt). The setup check
    (gathered at startup) says whether the game already matches the pack,
    so a player who set it up already isn't sent through an install.

Main package:
    HomePage.

Flow:
    build() lays out the title, status cards and actions; on_show() refreshes
    them from the App's last status.
"""
from pathlib import Path

import customtkinter as ctk

from whiney import config, crashsquatch, doctor, host, paths, skyrim, winapi
from whiney.ui.theme import FAIL_C, GOLD, MUTED, OK_C, TEXT, TITLE_FONT, WARN_C, F
from whiney.ui.widgets import Card, Page, TextWindow, Widget, btn, label, set_on


class HomePage(Page):
    title = ""

    def build(self, body: Widget) -> None:
        self.title_lbl = label(body, config.CONFIG["pack_name"], 30, GOLD, "bold", TITLE_FONT)
        self.title_lbl.pack(anchor="w")
        self.guide_btn = btn(body, "📖  Installation guide", self.open_guide, "ghost", width=180, height=32)
        self.guide_btn.place(relx=1, y=4, anchor="ne")
        self.guide_window: TextWindow | None = None
        req = config.load_requirements()
        built = f"  ·  built {req['built']}" if req.get("built") else ""
        label(body, f"by {config.CONFIG['author']}{built}", 13, MUTED).pack(anchor="w", pady=(0, 18))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")
        self.pack_card = self._stat(row, 0, "Mod pack")
        self.game_card = self._stat(row, 1, "Game")
        self.sync_card = self._stat(row, 2, "Sync code")
        btn(self.sync_card["frame"], "Copy", self.copy_sync, "ghost", width=60, height=26) \
            .place(relx=1, x=-12, y=12, anchor="ne")

        self.setup = Card(body)
        self.setup.pack(fill="x", pady=(16, 0))
        setup_row = ctk.CTkFrame(self.setup, fg_color="transparent")
        setup_row.pack(fill="x", padx=18, pady=14)
        btn(setup_row, "See details", lambda: self.app.show("doctor", run=True), "ghost", width=110, height=30) \
            .pack(side="right")
        label(setup_row, "SETUP CHECK", 11, MUTED, "bold").pack(anchor="w")
        self.setup_value = label(setup_row, "...", 16, TEXT, "bold")
        self.setup_value.pack(anchor="w", pady=(2, 0))
        self.setup_sub = label(setup_row, "", 12, MUTED, wrap=160)
        self.setup_sub.pack(fill="x")

        actions = Card(body)
        actions.pack(fill="x", pady=(16, 0))
        inner = ctk.CTkFrame(actions, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)
        self.play_btn = btn(inner, "▶   Play (SKSE)", lambda: self.app.play("skse"), "primary", height=48,
                            width=190, font=F(15, "bold"))
        self.play_btn.pack(side="left")
        self.together_btn = btn(inner, "⇄   Play Skyrim Together", lambda: self.app.play("together"), "primary",
                                height=48, width=230, font=F(15, "bold"))
        self.together_btn.pack(side="left", padx=(12, 0))
        self.install_btn = btn(inner, "Install", lambda: self.app.show("install"), height=48, width=120)
        self.install_btn.pack(side="left", padx=(12, 0))
        btn(inner, "Run Doctor", lambda: self.app.show("doctor", run=True), height=48, width=120) \
            .pack(side="left", padx=(12, 0))
        self.hint = label(actions, "", 12, MUTED)
        self.hint.pack(fill="x", padx=20, pady=(0, 16))

        self.notice = Card(body)
        self.notice_lbl = label(self.notice, "", 13, TEXT, wrap=44)
        self.notice_lbl.pack(fill="x", padx=20, pady=(14, 6))
        self.notice_btn = btn(self.notice, "", None, "normal", width=180)
        self.notice_btn.pack(anchor="w", padx=20, pady=(0, 14))

    def _stat(self, row: Widget, col: int, heading: str) -> dict[str, Widget]:
        card = Card(row)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        label(card, heading.upper(), 11, MUTED, "bold").pack(anchor="w", padx=18, pady=(14, 2))
        value = label(card, "...", 20, TEXT, "bold")
        value.pack(anchor="w", padx=18)
        sub = label(card, "", 12, MUTED, wraplength=230)
        sub.pack(anchor="w", padx=18, pady=(2, 14))
        return {"frame": card, "value": value, "sub": sub}

    def _show_setup(self, findings: list[doctor.Finding] | None, have_game: bool) -> bool:
        """Fill the setup check card; True if the game matches the pack."""
        if findings is None:
            self.setup_value.configure(text="Not checked", text_color=MUTED)
            self.setup_sub.configure(text="Skyrim wasn't found." if not have_game
                                     else "The check couldn't run; the Doctor shows why.")
            return False
        if doctor.matches_pack(findings):
            deployed = any(f.area == "Deployment" for f in findings)
            self.setup_value.configure(text="Matches the pack ✓", text_color=OK_C)
            self.setup_sub.configure(text="Same load order, and every file of the pack's mods is in the game."
                                     if deployed else "Same load order and plugins. (This build doesn't list "
                                                      "the pack's mod files, so only plugins were checked.)")
            return True
        problems = [f for f in findings if f.level != "OK"]
        if not problems:                    # nothing wrong, but no pack load order to compare with
            self.setup_value.configure(text="Not checked", text_color=MUTED)
            self.setup_sub.configure(text="This build has no load order to compare with.")
            return False
        worst = FAIL_C if any(f.level == "FAIL" for f in problems) else WARN_C
        self.setup_value.configure(text=f"{len(problems)} difference(s) from the pack", text_color=worst)
        self.setup_sub.configure(text="\n".join(f"• {f.title}" for f in problems[:3])
                                 + ("\n• ..." if len(problems) > 3 else ""))
        return False

    def open_guide(self) -> None:
        """Show the players' guide in a window; Open in Notepad hands the same file to Windows."""
        if self.guide_window is not None and self.guide_window.winfo_exists():
            self.guide_window.lift()
            return
        try:
            text = paths.GUIDE.read_text(encoding="utf-8")
        except OSError:
            self.app.tell("Guide not found", f"This build doesn't include the guide ({paths.GUIDE.name}). Ask "
                                             f"{config.CONFIG['author']} for it.")
            return
        self.guide_window = TextWindow(self.app, "Installation guide", text,
                                       [("Open in Notepad", lambda: winapi.open_path(paths.GUIDE))])

    def use_current_setup(self) -> None:
        config.mark_installed(self.app.status.get("req"))
        self.app.refresh_status()
        self.app.toast("Marked as installed")

    def copy_sync(self) -> None:
        code = skyrim.sync_code()
        if code:
            self.app.copy(code, "Sync code copied")

    def on_show(self) -> None:
        s = self.app.status
        state = s.get("state", "none")
        pc = self.pack_card
        if state == "installed":
            pc["value"].configure(text="Installed", text_color=OK_C)
            pc["sub"].configure(text="You're up to date.")
            self.install_btn.configure(text="Reinstall")
        elif state == "update":
            pc["value"].configure(text="Update ready", text_color=GOLD)
            pc["sub"].configure(text=f"{config.CONFIG['author']} added or changed mods.")
            self.install_btn.configure(text="Update")
        else:
            pc["value"].configure(text="Not installed", text_color=WARN_C)
            pc["sub"].configure(text="New here? Read the installation guide (top right), then click Install.")
            self.install_btn.configure(text="Install")

        gc = self.game_card
        game = s.get("game")
        if game:
            ver = winapi.file_version(Path(game) / "SkyrimSE.exe") or "found"
            gc["value"].configure(text=f"Skyrim SE {ver}" if ver != "found" else "Skyrim SE", text_color=TEXT)
            skse = "SKSE ready" if skyrim.skse_dlls(game) else "SKSE not installed"
            gc["sub"].configure(text=skse)
        else:
            gc["value"].configure(text="Not found", text_color=FAIL_C)
            gc["sub"].configure(text="Manage tab > Change game folder")

        code = s.get("sync")
        self.sync_card["value"].configure(text=code or "—", text_color=TEXT if code else MUTED,
                                          font=F(20, "bold", "Consolas" if winapi.IS_WINDOWS else "DejaVu Sans Mono"))
        self.sync_card["sub"].configure(text="Compare with friends before\njoining a multiplayer session.")

        client = host.find_client(game)
        set_on(self.play_btn, bool(game))
        set_on(self.together_btn, client is not None)
        if not game:
            hint = "Skyrim wasn't found, so both Play buttons are disabled."
        elif client is None:
            hint = ("Play (SKSE) starts single-player through SKSE. Skyrim Together isn't deployed, "
                    "so multiplayer is disabled.")
        else:
            hint = ("Play (SKSE) starts single-player through SKSE; Play Skyrim Together starts the multiplayer "
                    "client. Crash Squatch follows either one.")
        self.hint.configure(text=hint)

        matches = self._show_setup(s.get("setup"), bool(game))

        hist = crashsquatch.load_history()
        last = hist[0] if hist else None
        if state == "none" and matches:
            self.notice_lbl.configure(text="Your game already matches the pack: the same load order, with every "
                                           "mod deployed. Use it as is to skip installing (the pack's INI "
                                           "settings aren't applied; Install applies them).")
            self.notice_btn.configure(text="Use my current setup", command=self.use_current_setup)
            self.notice.pack(fill="x", pady=(16, 0))
        elif state == "update":
            self.notice_lbl.configure(text=f"An update from {config.CONFIG['author']} is ready. It only "
                                           "downloads what changed.")
            self.notice_btn.configure(text="Get the update", command=lambda: self.app.show("install"))
            self.notice.pack(fill="x", pady=(16, 0))
        elif last and last.kind in ("crash", "hang"):
            first = last.summary.splitlines()[0] if last.summary else ""
            what = "froze" if last.kind == "hang" else "crashed"
            self.notice_lbl.configure(text=f"Last time ({last.time}), Skyrim {what}. {first}")
            self.notice_btn.configure(text="See details", command=lambda: self.app.show("crash"))
            self.notice.pack(fill="x", pady=(16, 0))
        else:
            self.notice.pack_forget()
