"""The Doctor tab: runs the health checks and shows one card per finding.

Purpose:
    Turns doctor.run_all's findings into something a player can act on:
    red first, each with its fix, plus a report to copy for the maintainer.

Main package:
    DoctorPage.

Flow:
    run() checks in the background -> show() draws counts and finding cards ->
    copy or save the report.
"""
import threading
import time

import customtkinter as ctk

from whiney import config, doctor, paths, winapi
from whiney.ui.theme import FAIL_C, LEVEL_COLORS, MUTED, OK_C, TEXT, WARN_C
from whiney.ui.widgets import Card, Page, Widget, box, btn, chip, label, set_on


class DoctorPage(Page):
    title = "Doctor"
    subtitle = "Checks your game, plugins and mods for anything that would cause problems."

    def build(self, body: Widget) -> None:
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")
        self.run_btn = btn(top, "Run checks", self.run, "primary", width=140)
        self.run_btn.pack(side="left")
        btn(top, "Copy report", self.copy, width=120).pack(side="left", padx=(10, 0))
        btn(top, "Save report", self.save, width=120).pack(side="left", padx=(10, 0))
        self.counts = box(top)
        self.counts.pack(side="right")
        self.status_lbl = label(body, "Not run yet.", 13, MUTED)
        self.status_lbl.pack(fill="x", pady=(12, 8))
        self.list = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self.list.pack(fill="both", expand=True)
        self.results: list[doctor.Finding] = []
        self.in_place = False       # every pack mod is in the game: the Sync card offers the pack's load order
        self.busy = False

    def run(self) -> None:
        if self.busy:
            return
        self.busy = True
        set_on(self.run_btn, False)
        self.run_btn.configure(text="Checking...")
        game = self.app.status.get("game")

        def work() -> None:
            res = doctor.run_all(game, progress=lambda f, t: self.app.post(self.status_lbl.configure, text=t))
            try:
                in_place = doctor.all_mods_in_place(game)
            except Exception:
                in_place = False
            self.app.post(self.show, res, in_place)
        threading.Thread(target=work, daemon=True).start()

    def show(self, results: list[doctor.Finding], in_place: bool = False) -> None:
        """Draw the findings. in_place: every pack mod is in the game (doctor.all_mods_in_place)."""
        self.busy = False
        self.in_place = in_place
        set_on(self.run_btn, True)
        self.run_btn.configure(text="Run again")
        order = {"FAIL": 0, "WARN": 1, "OK": 2}
        self.results = sorted(results, key=lambda r: order[r.level])
        for w in self.list.winfo_children():
            w.destroy()
        for w in self.counts.winfo_children():
            w.destroy()
        n = {k: sum(1 for r in results if r.level == k) for k in order}
        for k, txt in (("FAIL", "problems"), ("WARN", "warnings"), ("OK", "fine")):
            chip(self.counts, f"{n[k]} {txt}", LEVEL_COLORS[k]).pack(side="left", padx=(6, 0))
        if n["FAIL"]:
            self.status_lbl.configure(text="Found problems. Fix the red ones first; each card says how.",
                                      text_color=FAIL_C)
        elif n["WARN"]:
            self.status_lbl.configure(text="Nothing serious. A few things worth a look.", text_color=WARN_C)
        else:
            self.status_lbl.configure(text="Everything looks healthy.", text_color=OK_C)
        for r in self.results:
            self._card(r)
        self.app.refresh_status()

    def _card(self, r: doctor.Finding) -> None:
        color = LEVEL_COLORS[r.level]
        card = Card(self.list)
        card.pack(fill="x", pady=4, padx=(0, 6))
        bar = ctk.CTkFrame(card, width=4, height=1, fg_color=color, corner_radius=2)
        bar.pack(side="left", fill="y", padx=(10, 0), pady=10)
        inner = box(card)
        inner.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        head = box(inner)
        head.pack(fill="x")
        label(head, r.area, 11, MUTED).pack(side="right")
        label(head, r.title, 14, TEXT, "bold", wrap=110).pack(side="left", fill="x", expand=True)
        if r.detail:
            label(inner, r.detail, 12, MUTED, wrap=10).pack(fill="x", pady=(2, 0))
        if r.fix and r.level != "OK":
            label(inner, "→ " + r.fix, 12, color, wrap=10).pack(fill="x", pady=(4, 0))
        if r.area == "Sync" and r.level != "OK" and self.in_place:
            btn(inner, "Apply the pack's load order", self.app.apply_load_order, "primary", width=200,
                height=30).pack(anchor="w", pady=(8, 0))
        if r.mods and r.level != "OK":
            mods = list(r.mods)
            btn(inner, f"Repair {len(mods)} mod{'s' if len(mods) > 1 else ''}", lambda: self.app.repair(mods),
                "primary" if r.level == "FAIL" else "normal", width=130, height=30).pack(anchor="w", pady=(8, 0))

    def copy(self) -> None:
        if self.results:
            self.app.copy(doctor.report_text(self.results), "Report copied. Paste it to "
                          f"{config.CONFIG['author']}.")

    def save(self) -> None:
        if not self.results:
            return
        path = paths.WORK_DIR / f"doctor_report_{time.strftime('%Y%m%d-%H%M')}.txt"
        paths.WORK_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(doctor.report_text(self.results), encoding="utf-8")
        winapi.open_path(paths.WORK_DIR)
        self.app.toast(f"Saved {path.name}")
