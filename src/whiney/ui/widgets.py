"""The building blocks every page uses: cards, buttons, labels, chips, dialogs, the Page base.

Purpose:
    Keeps the look consistent and the pages short: a page asks for btn(...)
    or label(...) instead of repeating colors, fonts and paddings.

Main package:
    Page: the base class every tab subclasses (title, subtitle, build(body),
    on_show()), which receives the window as an AppShell (the services pages
    use; AppStatus is its status). Dialog: the modal message box with custom buttons.
    TextWindow: a read-only document window (the installation guide).

Flow:
    Independent helpers; Page and Dialog build on btn and label.
"""
import functools
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, TypeVar

import customtkinter as ctk

from whiney import crashsquatch, doctor, winapi
from whiney.ui.theme import CARD, CARD_HI, GOLD, LINE, MUTED, PANEL, TEXT, TITLE_FONT, F, mix

# customtkinter publishes no types, so its widgets are Any to mypy; this names what a parameter holds
Widget = Any
T = TypeVar("T")


class AppStatus(TypedDict, total=False):
    """What App.status holds: gathered at startup and on every refresh (App._gather_status)."""
    req: dict[str, Any]                         # requirements.json the exe was built with
    game: Path | None                           # the game folder, None if not found
    state: Literal["none", "installed", "update"]   # config.install_state()
    sync: str | None                            # the active load order's sync code
    setup: list[doctor.Finding] | None          # doctor.setup_check(); None without a game


class AppShell(Protocol):
    """What pages use from the main window. ui.app.App implements it; pages depend on this, not on App."""
    content: Widget                             # the frame pages are packed into
    status: AppStatus
    watcher: crashsquatch.CrashSquatcher | None

    def post(self, fn: Callable[..., object], *args: Any, **kw: Any) -> None: ...
    def run_bg(self, fn: Callable[[], T], done: Callable[[T], object] | None = None) -> None: ...
    def show(self, key: str, run: bool = False) -> None: ...
    def repair(self, mods: Sequence[str]) -> None: ...
    def refresh_status(self) -> None: ...
    def play(self, mode: Literal["skse", "together"] = "skse") -> None: ...
    def start_watch(self, launch: bool = True, launcher: Path | None = None) -> None: ...
    def bring_to_front(self) -> None: ...
    def dialog(self, title: str, message: str, buttons: Sequence[tuple[str, Any, str]],
               on_close: Callable[[Any], object]) -> None: ...
    def tell(self, title: str, message: str) -> None: ...
    def copy(self, text: str, note: str = "Copied") -> None: ...
    def toast(self, text: str) -> None: ...


class Card(ctk.CTkFrame):
    def __init__(self, master: Widget, **kw: Any) -> None:
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", LINE)
        super().__init__(master, **kw)


def btn(master: Widget, text: str, command: Callable[[], object] | None,
        kind: Literal["primary", "normal", "danger", "ghost"] = "normal", **kw: Any) -> Widget:
    styles: dict[str, dict[str, Any]] = {
        "primary": dict(fg_color=GOLD, hover_color="#e6c454", text_color="#1a1406"),
        "normal": dict(fg_color=CARD_HI, hover_color="#313744", text_color=TEXT,
                       border_width=1, border_color=LINE),
        "danger": dict(fg_color="#3a1f1d", hover_color="#53302c", text_color="#ffb3ab",
                       border_width=1, border_color="#5c2c27"),
        "ghost": dict(fg_color="transparent", hover_color=CARD_HI, text_color=MUTED),
    }
    kw.setdefault("height", 36)
    kw.setdefault("corner_radius", 8)
    kw.setdefault("font", F(13, "bold" if kind == "primary" else "normal"))
    b = ctk.CTkButton(master, text=text, command=command, **styles[kind], **kw)
    b._kind = kind
    return b


def label(master: Widget, text: str = "", size: int = 13, color: str = TEXT, weight: str = "normal",
          family: str | None = None, wrap: int | None = None, **kw: Any) -> Widget:
    """wrap=N: keep text wrapped to the parent's width minus N pixels as the window resizes."""
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    lbl = ctk.CTkLabel(master, text=text, font=F(size, weight, family), text_color=color, **kw)
    if wrap is not None:
        def fit(e: tk.Event, l: Widget = lbl, pad: int = wrap) -> None:
            if e.width > pad + 50 and l.winfo_exists():
                l.configure(wraplength=e.width - pad)
        master.bind("<Configure>", fit, add="+")
    return lbl


def box(master: Widget, **kw: Any) -> Widget:
    """Invisible container. height=1 so it collapses when empty (CTk default is 200)."""
    kw.setdefault("fg_color", "transparent")
    kw.setdefault("height", 1)
    return ctk.CTkFrame(master, **kw)


def set_on(button: Widget, on: bool) -> None:
    """Enable/disable a button; primary buttons also dim so they don't look clickable."""
    button.configure(state="normal" if on else "disabled")
    if getattr(button, "_kind", None) == "primary":
        button.configure(fg_color=GOLD if on else "#4a4024", text_color_disabled="#8c7d55")


def chip(master: Widget, text: str, color: str) -> Widget:
    return ctk.CTkLabel(master, text=f"  {text}  ", font=F(11, "bold"), text_color=color,
                        fg_color=mix(CARD, color, 0.16), corner_radius=10, height=22)


class Dialog(ctk.CTkToplevel):
    """Modal message box. buttons = [(label, value, kind)]."""

    def __init__(self, master: Widget, title: str, message: str, buttons: Sequence[tuple[str, Any, str]],
                 on_close: Callable[[Any], object]) -> None:
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=PANEL)
        self.resizable(False, False)
        self.on_close = on_close
        self.result = None
        label(self, title, 16, GOLD, "bold").pack(fill="x", padx=24, pady=(20, 6))
        label(self, message, 13, TEXT, wraplength=440).pack(fill="x", padx=24, pady=(0, 18))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 20))
        for text, value, kind in reversed(buttons):
            btn(row, text, functools.partial(self.close, value), kind, width=110).pack(side="right", padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(buttons[-1][1]))
        self.after(50, self._center)

    def _center(self) -> None:
        self.update_idletasks()
        m = self.master
        x = m.winfo_rootx() + (m.winfo_width() - self.winfo_width()) // 2
        y = m.winfo_rooty() + (m.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def close(self, value: Any) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_close(value)


class Page(ctk.CTkFrame):
    title = ""
    subtitle = ""

    def __init__(self, app: AppShell) -> None:
        super().__init__(app.content, fg_color="transparent")
        self.app = app
        if self.title:
            head = box(self)
            head.pack(fill="x", padx=32, pady=(26, 14))
            label(head, self.title, 24, TEXT, "bold", TITLE_FONT).pack(anchor="w")
            if self.subtitle:
                label(head, self.subtitle, 13, MUTED).pack(anchor="w", pady=(2, 0))
        else:
            box(self, height=26).pack(fill="x")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=32, pady=(0, 24))
        self.build(self.body)

    def build(self, body: Widget) -> None:
        pass

    def on_show(self) -> None:
        pass


class TextWindow(ctk.CTkToplevel):
    """A read-only window showing a plain-text document in a monospaced font (column layouts stay aligned).

    extras: [(label, callable)] buttons beside Close.
    """

    def __init__(self, master: Widget, title: str, text: str,
                 extras: Sequence[tuple[str, Callable[[], object]]] = ()) -> None:
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=PANEL)
        self.geometry("760x680")
        mono = "Consolas" if winapi.IS_WINDOWS else "DejaVu Sans Mono"
        self.textbox = ctk.CTkTextbox(self, fg_color=CARD, text_color=TEXT, border_color=LINE, border_width=1,
                                      font=ctk.CTkFont(family=mono, size=13), corner_radius=10, wrap="word")
        self.textbox.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        self.textbox.insert("1.0", text)
        self.textbox.configure(state="disabled")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))
        btn(row, "Close", self.destroy, "primary", width=110).pack(side="right")
        for text_, fn in extras:
            btn(row, text_, fn, width=150).pack(side="left", padx=(0, 8))
        self.after(50, self.lift)
