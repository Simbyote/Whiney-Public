"""
Started by test_gui.py in its own process: opens the real App, visits every
tab, renders a Doctor run's cards, a crash's details, each state of Home's
setup check and the installation guide, cancels an install's wait for the
player, and prints JSON with each page's widget counts, what Home and Install
showed, and any exception raised in a Tk callback or a background thread.
Exits once every tab has been shown.
"""
import collections
import json
import sys
import tempfile
import threading
import traceback
from pathlib import Path

from whiney import crashsquatch
from whiney.ui import app as app_module

errors = []
home_seen: dict = {}
install_seen: dict = {}
crash_seen: dict = {}
doctor_seen: dict = {}
threading.excepthook = lambda a: errors.append(
    "thread: " + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
app = app_module.App()
app.report_callback_exception = lambda e, v, tb: errors.append("tk: " + "".join(traceback.format_exception(e, v, tb)))


def widget_counts(widget) -> dict:
    """Widgets under `widget`, by class name."""
    counts, stack = collections.Counter(), [widget]
    while stack:
        w = stack.pop()
        counts[type(w).__name__] += 1
        stack.extend(w.winfo_children())
    return dict(counts)


def play_buttons() -> dict:
    """Each page's Play buttons: "normal" when clickable, "disabled" otherwise."""
    return {page: {"skse": str(app.pages[page].play_btn.cget("state")),
                   "together": str(app.pages[page].together_btn.cget("state"))}
            for page in ("home", "crash")}


def finish(extra=None):
    print(json.dumps({"pages": {k: widget_counts(p) for k, p in app.pages.items()},
                      "play_buttons": play_buttons(),
                      "home": home_seen,
                      "install": install_seen,
                      "crash": crash_seen,
                      "doctor": doctor_seen,
                      "errors": errors + ([extra] if extra else [])}))
    app.destroy()


def exercise():
    """Render what the tabs only show after a click or a crash: Doctor cards, a crash's details, live status."""
    from whiney import doctor
    try:
        app.show("doctor")
        app.pages["doctor"].show(doctor.run_all())
    except Exception:
        errors.append("doctor cards: " + traceback.format_exc())
    try:
        click_repair()
    except Exception:
        errors.append("doctor repair: " + traceback.format_exc())
    try:
        load_order_buttons()
    except Exception:
        errors.append("load order buttons: " + traceback.format_exc())
    try:
        pick_a_pack_file()
    except Exception:
        errors.append("install file picker: " + traceback.format_exc())
    try:
        logs = []
        for name in ("crash-2026-10-30.log", "Crash_2026_10_30.txt"):    # two crash loggers' logs
            log = Path(tempfile.mkdtemp()) / name
            log.write_text("log", encoding="utf-8")
            logs.append(str(log))
        analysis = crashsquatch.Analysis("Error: EXCEPTION_ACCESS_VIOLATION at SkyrimSE.exe+0C3D4D4",
                                       (crashsquatch.Suspect("BadHooks.dll", "SKSE plugin", 16, "Bad Hooks NG"),
                                        crashsquatch.Suspect("Mod.esp", "plugin", 3, None)), logs[0], (logs[1],))
        crash = crashsquatch.CrashEvent("crash", "2026-10-30 12:00:00", 95.0, "Most likely involved: Bad Hooks NG",
                                      analysis)
        crashsquatch.save_event(crash)                     # into the temp HOME's work folder
        page = app.pages["crash"]
        app.show("crash")
        page.on_event(crashsquatch.Status("waiting"))
        page.on_event(crashsquatch.Status("running", uptime=65, ram=2 * 1024 ** 3))
        app._watch_event(crash)                           # what the watcher thread delivers
        crash_seen["buttons"] = [w.cget("text") for w in page.detail_btns.winfo_children()]
        page.on_event(crashsquatch.Status("stopped"))
        page.select(crashsquatch.CrashEvent("hang", "2026-10-30 12:05:00", 30.0, "Skyrim stopped responding (froze)."))
        app.show("home")                                  # its notice reads the last crash
    except Exception:
        errors.append("crash page: " + traceback.format_exc())
    try:
        home = app.pages["home"]
        home_seen["startup_setup"] = home.setup_value.cget("text")       # from the real startup check
        ok, warn, fail = (doctor.Finding(level, area, "t") for level, area in
                          (("OK", "Sync"), ("WARN", "Sync"), ("FAIL", "Deployment")))
        states = {"no game": None, "matches": [ok, doctor.Finding("OK", "Deployment", "t")],
                  "differs": [warn, fail], "nothing to compare": []}
        home_seen["setup"] = {}
        for name, setup in states.items():
            app.status.update(setup=setup, state="none")
            home.on_show()
            home_seen["setup"][name] = home.setup_value.cget("text")
            if name == "matches":
                home_seen["already_set_up_notice"] = home.notice_btn.cget("text")
    except Exception:
        errors.append("home setup check: " + traceback.format_exc())
    try:
        home.open_guide()
        home_seen["guide_lines"] = int(home.guide_window.textbox.index("end-1c").split(".")[0])
        home.guide_window.destroy()
    except Exception:
        errors.append("installation guide: " + traceback.format_exc())
    try:
        cancel_a_wait()
    except Exception:
        errors.append("install cancel: " + traceback.format_exc())
        app.after(300, finish)


def click_repair():
    """A Deployment card's Repair button opens Install & Update on a repair of that card's mods.

    The Install page's start() is stubbed: a real one would ask to download the pack.
    """
    from whiney import doctor
    page, install = app.pages["doctor"], app.pages["install"]
    page.show([doctor.Finding("FAIL", "Deployment", "1 pack mod(s) aren't deployed in the game", "Alpha", "fix",
                              ("Alpha-11111-1-0-1700000000",))])
    stack, buttons = [page.list], []
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if type(w).__name__ == "CTkButton" and str(w.cget("text")).startswith("Repair"):
            buttons.append(w)
    doctor_seen["repair_buttons"] = [str(b.cget("text")) for b in buttons]
    started = {}
    install.start = lambda: started.update(mode=install.mode_key(), mods=list(install.repair_mods))
    try:
        buttons[0].invoke()
    finally:
        del install.start
        install.repair_mods = []
    doctor_seen["started"] = started
    doctor_seen["page"] = app.current


def load_order_buttons():
    """"Apply the pack's load order" shows on Home and the Doctor's Sync card only with every mod in place."""
    from whiney import doctor
    home, doc = app.pages["home"], app.pages["doctor"]
    sync_off = doctor.Finding("WARN", "Sync", "Your load order differs from the pack", "Same plugins, different order.")
    seen = {}
    for in_place in (True, False):
        app.status.update(setup=[sync_off], mods_in_place=in_place, state="installed")
        app.show("home")
        seen[f"home_{in_place}"] = home.order_btn.winfo_manager() == "pack"
        doc.show([sync_off], in_place)
        stack, texts = [doc.list], []
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if type(w).__name__ == "CTkButton":
                texts.append(str(w.cget("text")))
        seen[f"doctor_{in_place}"] = "Apply the pack's load order" in texts
    before = set(app.winfo_children())
    app.apply_load_order()                             # asks first: the dialog opens, nothing is written yet
    dialogs = [w for w in app.winfo_children() if w not in before and type(w).__name__ == "Dialog"]
    seen["asks_first"] = len(dialogs) == 1
    for w in dialogs:
        w.destroy()
    home_seen["load_order_button"] = seen


def pick_a_pack_file():
    """Install's "I already have the file" (the dialog stubbed): the file is shown, used, and can be cleared."""
    from whiney.ui.pages import install as install_module
    page = app.pages["install"]
    app.show("install")
    real = install_module.filedialog.askopenfilename
    install_module.filedialog.askopenfilename = lambda **kw: "/somewhere/modpack.tar.gz"
    try:
        page.pick_file()
    finally:
        install_module.filedialog.askopenfilename = real
    app.update()
    install_seen["picked"] = {"file": page.pack_file.name, "label_names_it": "modpack.tar.gz" in
                              page.file_lbl.cget("text"), "clear_shown": page.clear_file_btn.winfo_manager() == "pack"}
    page.clear_file()
    install_seen["cleared"] = page.pack_file is None and page.clear_file_btn.winfo_manager() == ""


def cancel_a_wait():
    """An install waiting at the Vortex hand-off, cancelled: the worker gets Cancelled and the card goes away."""
    from whiney import installer
    from whiney.ui.pages.install import GuiBridge
    page = app.pages["install"]
    app.show("install")
    page.draw_steps()
    page.set_step("download", "cancelled")
    cancel = threading.Event()
    bridge = GuiBridge(app, page, cancel)

    def worker():
        try:
            bridge.wait_for_user("Your turn", "body", "Done", [])
            install_seen["wait"] = "returned"
        except installer.Cancelled:
            install_seen["wait"] = "cancelled"

    threading.Thread(target=worker, daemon=True).start()

    def check():
        install_seen["action_card_shown"] = bool(page.action.winfo_ismapped())
        app.after(300, finish)
    app.after(500, cancel.set)
    app.after(1500, check)


def visit(keys):
    if not keys:
        return exercise()
    try:
        app.show(keys[0])
    except Exception:
        errors.append(f"show({keys[0]}): " + traceback.format_exc())
    app.after(300, visit, keys[1:])


def start():
    if len(app.pages) < len(app.NAV):     # the splash and the first status check are still running
        return app.after(300, start)
    visit([key for key, _, _ in app.NAV])


app.after(300, start)
app.after(45000, finish, "timed out before every tab was shown")
app.mainloop()
sys.exit(0)
