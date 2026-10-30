"""The GUI: the window, its splash screen, and one page per tab.

Purpose:
    Everything the player sees, kept apart from the logic it drives
    (installer, doctor, crashsquatch, host, manage). Only this package imports
    tkinter, so the rest of the app, the packer and the tests run headless.

Main package:
    ui.app.App: the main window. ui.app.main() starts it.

Flow:
    theme (colors, fonts) -> widgets (shared building blocks) -> splash and
    pages (one per tab) -> app (the window that holds them).
"""
