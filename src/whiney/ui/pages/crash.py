"""The Crash Squatch tab: play, watch the game, and explain crashes and freezes.

Purpose:
    The face of crashsquatch.CrashSquatcher: live status while the game runs, and
    a history of crashes with the likely culprit and a report to copy.

Main package:
    CrashPage. fmt_duration() formats uptimes ("1h 05m").

Flow:
    Play / Watch starts the watcher -> its events update the status ->
    a crash or freeze is added to the history and shown in detail.
"""
import functools
from pathlib import Path

import customtkinter as ctk

from whiney import config, crashsquatch, host, skyrim, util, winapi
from whiney.ui.theme import CARD, CARD_HI, FAIL_C, MUTED, OK_C, PANEL, TEXT, WARN_C, F, mix
from whiney.ui.widgets import Card, Page, Widget, box, btn, label, set_on


def fmt_duration(s: float) -> str:
    s = int(s)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


IDLE_HINT = "Start Skyrim with Play (SKSE) or Play Skyrim Together, or watch a game already running."

class CrashPage(Page):
    title = "Crash Squatch"
    subtitle = "Launch Skyrim from here and the app watches in the background for crashes and freezes."

    def build(self, body: Widget) -> None:
        top = Card(body)
        top.pack(fill="x")
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=16)
        self.dot = ctk.CTkLabel(row, text="●", font=F(26), text_color=MUTED, width=30)
        self.dot.pack(side="left")
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", padx=(8, 0))
        self.state_lbl = label(col, "Not watching", 18, TEXT, "bold")
        self.state_lbl.pack(anchor="w")
        self.stats_lbl = label(col, IDLE_HINT, 12, MUTED)
        self.stats_lbl.pack(anchor="w")
        self.stop_btn = btn(row, "Stop watching", self.stop, "ghost", width=130)
        self.stop_btn.pack(side="right")
        self.attach_btn = btn(row, "Watch running game", self.attach, width=170)
        self.attach_btn.pack(side="right", padx=(8, 8))
        play = ctk.CTkFrame(top, fg_color="transparent")
        play.pack(fill="x", padx=20, pady=(0, 16))
        self.play_btn = btn(play, "▶  Play (SKSE)", lambda: self.app.play("skse"), "primary", width=150)
        self.play_btn.pack(side="left")
        self.together_btn = btn(play, "⇄  Play Skyrim Together", lambda: self.app.play("together"), "primary",
                                width=200)
        self.together_btn.pack(side="left", padx=(8, 0))

        mid = ctk.CTkFrame(body, fg_color="transparent")
        mid.pack(fill="both", expand=True, pady=(14, 0))
        mid.grid_columnconfigure(1, weight=1)
        mid.grid_rowconfigure(1, weight=1)
        label(mid, "HISTORY", 11, MUTED, "bold").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.history = ctk.CTkScrollableFrame(mid, fg_color=PANEL, width=270, corner_radius=12)
        self.history.grid(row=1, column=0, sticky="nsw")
        self.detail = Card(mid)
        self.detail.grid(row=1, column=1, sticky="nsew", padx=(14, 0))
        self.detail_title = label(self.detail, "No crashes recorded", 16, TEXT, "bold")
        self.detail_title.pack(fill="x", padx=20, pady=(16, 4))
        self.detail_body = label(self.detail, "Crashes and freezes caught by Crash Squatch show up here with "
                                              "the most likely cause.", 13, MUTED, wrap=44)
        self.detail_body.pack(fill="x", padx=20)
        self.suspects = box(self.detail)
        self.suspects.pack(fill="x", padx=20, pady=(12, 0))
        self.detail_btns = box(self.detail)
        self.detail_btns.pack(fill="x", padx=20, pady=16, side="bottom")
        self.selected: crashsquatch.CrashEvent | None = None
        self.set_idle()

    def on_show(self) -> None:
        self.load_history()

    def set_idle(self, note: str | None = None) -> None:
        self.dot.configure(text_color=MUTED)
        self.state_lbl.configure(text="Not watching")
        self.stats_lbl.configure(text=note or IDLE_HINT)
        self.stop_btn.configure(state="disabled")
        game = self.app.status.get("game")
        set_on(self.play_btn, bool(game))
        set_on(self.together_btn, host.find_client(game) is not None)
        self.attach_btn.configure(state="normal" if self.app.status.get("game") else "disabled")

    def attach(self) -> None:
        self.app.start_watch(launch=False)

    def stop(self) -> None:
        if self.app.watcher:
            self.app.watcher.stop()

    def on_event(self, ev: crashsquatch.Status | crashsquatch.CrashEvent) -> None:
        if isinstance(ev, crashsquatch.Status):
            st = ev.state
            if st == "waiting":
                self.dot.configure(text_color=WARN_C)
                self.state_lbl.configure(text="Starting Skyrim...")
                self.stats_lbl.configure(text="Waiting for the game window.")
                self.stop_btn.configure(state="normal")
                set_on(self.play_btn, False)
                set_on(self.together_btn, False)
                self.attach_btn.configure(state="disabled")
            elif st == "running":
                self.dot.configure(text_color=OK_C)
                self.state_lbl.configure(text="Skyrim is running, watching")
                self.stats_lbl.configure(text=f"Playing for {fmt_duration(ev.uptime)}   ·   "
                                              f"RAM {util.human(ev.ram)}")
            elif st == "stopped":
                self.set_idle(ev.note)
            return
        if ev.kind == "exit":
            self.set_idle(f"Skyrim closed normally after {fmt_duration(ev.uptime)}.")
            return
        self.load_history()
        self.select(ev)
        if ev.kind == "hang":
            self.dot.configure(text_color=FAIL_C)
            self.state_lbl.configure(text="Skyrim froze")

    def load_history(self) -> None:
        for w in self.history.winfo_children():
            w.destroy()
        hist = crashsquatch.load_history()
        if not hist:
            label(self.history, "Nothing yet. Good sign.", 12, MUTED).pack(fill="x", padx=10, pady=10)
            return
        for ev in hist:
            color = WARN_C if ev.kind == "hang" else FAIL_C
            first = ev.summary.splitlines()[0] if ev.summary else ""
            item = ctk.CTkFrame(self.history, fg_color=CARD, corner_radius=8, border_width=1,
                                border_color=mix(CARD, color, 0.5))
            item.pack(fill="x", padx=6, pady=3)
            kind = "Froze" if ev.kind == "hang" else "Crashed"
            t = label(item, f"{kind}  ·  {ev.time}", 12, color, "bold")
            t.pack(fill="x", padx=12, pady=(8, 0))
            d = label(item, first, 12, MUTED, wrap=26)
            d.pack(fill="x", padx=12, pady=(0, 8))
            for w in (item, t, d):
                w.bind("<Button-1>", lambda e, ev=ev: self.select(ev))
        if not self.selected:
            self.select(hist[0])

    def select(self, ev: crashsquatch.CrashEvent) -> None:
        self.selected = ev
        kind = ev.kind
        what = "Skyrim froze" if kind == "hang" else "Skyrim crashed"
        played = f" after {fmt_duration(ev.uptime)}" if ev.uptime else ""
        self.detail_title.configure(text=f"{what}{played}", text_color=WARN_C if kind == "hang" else FAIL_C)
        self.detail_body.configure(text=f"{ev.time}\n\n{ev.summary}", text_color=TEXT)
        for w in self.suspects.winfo_children():
            w.destroy()
        sus = ev.analysis.suspects if ev.analysis else ()
        if sus:
            label(self.suspects, "SUSPECTS (most likely first)", 11, MUTED, "bold").pack(anchor="w", pady=(0, 4))
            for s in sus:
                r = ctk.CTkFrame(self.suspects, fg_color=CARD_HI, corner_radius=8)
                r.pack(fill="x", pady=2)
                label(r, s.mod or "(unknown mod)", 13, TEXT, "bold").pack(side="left", padx=12, pady=6)
                label(r, f"{s.file}  ·  {s.kind}", 12, MUTED).pack(side="right", padx=12)
        for w in self.detail_btns.winfo_children():
            w.destroy()
        logs = [ev.analysis.log, *ev.analysis.other_logs] if ev.analysis else []
        for i, log in enumerate(p for p in logs if p and Path(p).exists()):
            text = "Open crash log" if i == 0 else f"Log {i + 1}"
            btn(self.detail_btns, text, functools.partial(winapi.open_path, log), width=110 if i else 140) \
                .pack(side="left", padx=(8 if i else 0, 0))
        btn(self.detail_btns, f"Copy for {config.CONFIG['author']}", lambda: self.copy(ev)) \
            .pack(side="left", padx=(8, 0))
        btn(self.detail_btns, "Run Doctor", lambda: self.app.show("doctor", run=True), "ghost") \
            .pack(side="left", padx=(8, 0))

    def copy(self, ev: crashsquatch.CrashEvent) -> None:
        lines = [f"{config.CONFIG['pack_name']}: Skyrim {'froze' if ev.kind == 'hang' else 'crashed'} "
                 f"at {ev.time}", f"Sync code: {skyrim.sync_code() or 'n/a'}", ev.summary]
        for s in ev.analysis.suspects if ev.analysis else ():
            lines.append(f"- {s.mod or '?'}: {s.file} ({s.kind})")
        if ev.analysis:
            names = [Path(p).name for p in (ev.analysis.log, *ev.analysis.other_logs) if p]
            lines.append(f"Crash log{'s' if len(names) > 1 else ''}: {', '.join(names)}")
        self.app.copy("\n".join(lines), "Copied. Paste it in your chat.")
