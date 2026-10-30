"""Colors, fonts and the customtkinter appearance every screen shares.

Purpose:
    One palette and one set of font helpers, so pages don't each pick their
    own. Importing it also sets customtkinter's dark appearance and color
    theme, which has to happen before the first widget is created.

Main package:
    The color constants (BG ... INFO_C, LEVEL_COLORS for Doctor levels),
    UI_FONT / TITLE_FONT, F() for a font, mix() for blending two colors.

Flow:
    1. Colors and fonts.
    2. Set customtkinter's appearance mode and color theme.
    3. Font and color helpers.
"""
import customtkinter as ctk

from whiney import winapi

BG = "#0f1115"
PANEL = "#171a20"
CARD = "#1e222a"
CARD_HI = "#252a34"
LINE = "#2c313c"
GOLD = "#d4af37"
GOLD_DIM = "#8a7330"
TEXT = "#e8e6e1"
MUTED = "#9aa0aa"
OK_C = "#4fbf7f"
WARN_C = "#e0a63a"
FAIL_C = "#e25b4f"
INFO_C = "#5b9be0"
LEVEL_COLORS = {"OK": OK_C, "WARN": WARN_C, "FAIL": FAIL_C}
UI_FONT = "Segoe UI" if winapi.IS_WINDOWS else "Inter"
TITLE_FONT = "Georgia"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


# Short on purpose: every label and button builds its font with F(...)
def F(size: int = 13, weight: str = "normal", family: str | None = None) -> ctk.CTkFont:  # noqa: N802
    return ctk.CTkFont(family=family or UI_FONT, size=size, weight=weight)


def mix(c1: str, c2: str, t: float) -> str:
    """Blend two #rrggbb colors, t=0 -> c1, t=1 -> c2."""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=True))
