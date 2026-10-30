"""The animated splash shown while the app gathers its first status.

Purpose:
    Covers the startup check (game, install state) with something to look
    at, and stays up at least MIN_TIME so it never just flickers.

Main package:
    Splash: a borderless window drawing a rune ring and the pack's name;
    App closes it when startup finishes.

Flow:
    Draw the frame -> animate the ring and runes -> fade out on close().
"""
import math
import time
import tkinter as tk
from collections.abc import Callable

from whiney.ui.theme import BG, GOLD, GOLD_DIM, LINE, MUTED, TEXT, TITLE_FONT, UI_FONT, mix

RUNES: list[list[list[tuple[float, float]]]] = [  # original glyphs, unit box -1..1
    [[(0, -1), (0, 1)], [(0, -0.45), (0.6, -1)], [(0, 0.05), (0.6, -0.5)]],
    [[(-0.45, -1), (-0.45, 1)], [(-0.45, -1), (0.45, -0.45), (-0.45, 0.1)], [(-0.45, 0.1), (0.45, 1)]],
    [[(0, -1), (0.55, 0), (0, 1), (-0.55, 0), (0, -1)]],
    [[(-0.6, -1), (0, -0.1), (0.6, -1)], [(0, -0.1), (0, 1)]],
    [[(0, -1), (0, 1)], [(-0.55, -0.55), (0.55, 0.55)]],
    [[(-0.5, 1), (-0.5, -1), (0.5, 1), (0.5, -1)]],
    [[(-0.5, -1), (0.5, 0), (-0.5, 1)]],
    [[(0, -1), (0, 1)], [(-0.55, -0.35), (0, -1), (0.55, -0.35)]],
]


class Splash(tk.Toplevel):
    W, H = 580, 360
    MIN_TIME = 2.8

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}")
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.c = tk.Canvas(self, width=self.W, height=self.H, bg=BG, highlightthickness=0)
        self.c.pack(fill="both", expand=True)
        self.c.create_rectangle(1, 1, self.W - 2, self.H - 2, outline=LINE)
        self.cx, self.cy = self.W // 2, 150
        self.t0 = time.time()
        self.ready = False
        self.done_cb: Callable[[], object] | None = None      # called once the fade-out ends
        self.closing_at: float | None = None
        self.status = "Waking up..."

        self.glows = [self.c.create_oval(0, 0, 0, 0, outline="", fill=BG) for _ in range(3)]
        for g in self.glows:                # smallest glow on top, all of them behind everything else
            self.c.tag_lower(g)
        self.ring1 = self.c.create_oval(self.cx - 92, self.cy - 92, self.cx + 92, self.cy + 92, outline=BG, width=2)
        self.ring2 = self.c.create_oval(self.cx - 128, self.cy - 128, self.cx + 128, self.cy + 128, outline=BG, width=1)
        self.ticks = [self.c.create_line(0, 0, 0, 0, fill=BG, width=2) for _ in range(48)]
        # one entry per rune: each stroke's points, with the canvas line drawing it
        self.rune_items: list[list[tuple[list[tuple[float, float]], int]]] = []
        for i in range(12):
            glyph = RUNES[i % len(RUNES)]
            self.rune_items.append([(stroke, self.c.create_line(0, 0, 0, 0, fill=BG, width=2,
                                                                capstyle="round", joinstyle="round"))
                                    for stroke in glyph])
        self.star = self.c.create_polygon(0, 0, 0, 0, outline=BG, fill="", width=2)
        self.title_item = self.c.create_text(self.cx, 300, text=title, fill=BG,
                                             font=(TITLE_FONT, 22, "bold"))
        self.sub_item = self.c.create_text(self.cx, 330, text="", fill=BG, font=(UI_FONT, 10))
        self.bar = self.c.create_line(0, self.H - 3, 0, self.H - 3, fill=GOLD, width=2)
        self.bind("<Button-1>", lambda e: self.finish(force=True))
        self.c.bind("<Button-1>", lambda e: self.finish(force=True))
        self.tick()

    def set_status(self, text: str) -> None:
        self.status = text

    def finish(self, force: bool = False) -> None:
        """Called when startup work is done (or on click, force=True, to skip the wait)."""
        if force:
            if not self.ready:
                return                      # can't skip before the app is built
            self.t0 -= self.MIN_TIME
        self.ready = True

    def tick(self) -> None:
        t = time.time() - self.t0
        cx, cy = self.cx, self.cy
        fade_in = min(t / 0.6, 1)
        if self.closing_at is None and self.ready and t >= self.MIN_TIME:
            self.closing_at = time.time()
        fade_out = 1 - min((time.time() - self.closing_at) / 0.35, 1) if self.closing_at else 1
        alpha = fade_in * fade_out
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            pass

        pulse = (math.sin(t * 2.4) + 1) / 2
        for i, g in enumerate(self.glows):
            r = 30 + i * 16 + pulse * 6
            self.c.coords(g, cx - r, cy - r, cx + r, cy + r)
            self.c.itemconfigure(g, fill=mix(BG, "#2a2412", (0.8 - i * 0.25) * min(t / 1.0, 1) * (0.6 + 0.4 * pulse)))
        self.c.itemconfigure(self.ring1, outline=mix(BG, GOLD, min(t / 0.8, 1)))
        self.c.itemconfigure(self.ring2, outline=mix(BG, GOLD_DIM, min(t / 1.2, 1)))

        spin = t * 0.5
        for i, item in enumerate(self.ticks):
            a = spin + i * (2 * math.pi / 48)
            long_tick = i % 4 == 0
            r1, r2 = (80, 92) if long_tick else (86, 92)
            self.c.coords(item, cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                          cx + r2 * math.cos(a), cy + r2 * math.sin(a))
            appear = min(max((t - i * 0.015) / 0.4, 0), 1)
            self.c.itemconfigure(item, fill=mix(BG, GOLD if long_tick else GOLD_DIM, appear))

        rspin = -t * 0.32
        for i, strokes in enumerate(self.rune_items):
            a = rspin + i * (2 * math.pi / 12)
            px, py = cx + 110 * math.cos(a), cy + 110 * math.sin(a)
            rot = a + math.pi / 2
            ca, sa = math.cos(rot), math.sin(rot)
            appear = min(max((t - 0.5 - i * 0.07) / 0.5, 0), 1)
            for stroke, item in strokes:
                pts = []
                for x, y in stroke:
                    x, y = x * 7, y * 9
                    pts += [px + x * ca - y * sa, py + x * sa + y * ca]
                if len(pts) >= 4:
                    self.c.coords(item, *pts)
                self.c.itemconfigure(item, fill=mix(BG, GOLD, appear * (0.75 + 0.25 * pulse)))

        star = []
        for k in range(16):
            a = -t * 0.8 + k * math.pi / 8
            r = 38 if k % 2 == 0 else (13 if k % 4 == 1 else 19)
            star += [cx + r * math.cos(a), cy + r * math.sin(a)]
        self.c.coords(self.star, *star)
        self.c.itemconfigure(self.star, outline=mix(BG, GOLD, min(max((t - 0.2) / 0.6, 0), 1)))

        self.c.itemconfigure(self.title_item, fill=mix(BG, TEXT, min(max((t - 0.7) / 0.8, 0), 1)))
        shown = self.status[:int(max(t - 1.1, 0) * 45)] if t > 1.1 else ""
        self.c.itemconfigure(self.sub_item, text=shown, fill=MUTED)

        w = self.W
        head = (t * 260) % (w + 160) - 80
        self.c.coords(self.bar, max(head - 80, 0), self.H - 3, min(head + 80, w), self.H - 3)

        if self.closing_at and fade_out <= 0:
            cb = self.done_cb
            self.destroy()
            if cb:
                cb()
            return
        self.after(16, self.tick)
