"""One module per sidebar tab, each a Page subclass the App shows by name.

Purpose:
    Each tab owns its own layout and reactions; none imports another. The
    App builds them all once and switches between them.

Main package:
    HomePage, InstallPage, DoctorPage, CrashPage, HostPage, ManagePage.

Flow:
    App.show(key) -> page.on_show(); long work goes through App.run_bg and
    comes back on the GUI thread.
"""
