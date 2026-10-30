"""The Host Server tab: start and stop Skyrim Together's server, share the address, allow it through the firewall.

Purpose:
    Hosting fails for reasons a player can't see (server not deployed,
    firewall, CGNAT); this page shows each one and how to fix it.

Main package:
    HostPage.

Flow:
    Find the server -> show its state, port and addresses -> start/stop it and
    check or add the firewall rule.
"""
from pathlib import Path

import customtkinter as ctk

from whiney import host, winapi
from whiney.ui.theme import GOLD, MUTED, OK_C, TEXT, WARN_C, F
from whiney.ui.widgets import Card, Page, Widget, btn, label, set_on


class HostPage(Page):
    title = "Host a Server"
    subtitle = "Run the Skyrim Together server on this PC and share the address with friends."

    def build(self, body: Widget) -> None:
        body.grid_columnconfigure((0, 1), weight=1, uniform="h")
        server = Card(body)
        server.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        label(server, "SERVER", 11, MUTED, "bold").pack(anchor="w", padx=20, pady=(16, 4))
        self.srv_state = label(server, "...", 18, TEXT, "bold")
        self.srv_state.pack(anchor="w", padx=20)
        self.srv_path = label(server, "", 12, MUTED, wrap=44)
        self.srv_path.pack(anchor="w", padx=20, pady=(2, 12))
        row = ctk.CTkFrame(server, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 18))
        self.start_btn = btn(row, "Start server", self.start, "primary", width=140)
        self.start_btn.pack(side="left")
        self.stop_btn = btn(row, "Stop", self.stop, "danger", width=90)
        self.stop_btn.pack(side="left", padx=(8, 0))

        addr = Card(body)
        addr.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        label(addr, "ADDRESS TO SHARE", 11, MUTED, "bold").pack(anchor="w", padx=20, pady=(16, 4))
        self.addr_lbl = label(addr, "Looking up...", 22, GOLD, "bold",
                              "Consolas" if winapi.IS_WINDOWS else "DejaVu Sans Mono")
        self.addr_lbl.pack(anchor="w", padx=20)
        self.local_lbl = label(addr, "", 12, MUTED)
        self.local_lbl.pack(anchor="w", padx=20, pady=(2, 12))
        row2 = ctk.CTkFrame(addr, fg_color="transparent")
        row2.pack(anchor="w", padx=20, pady=(0, 18))
        btn(row2, "Copy address", self.copy_addr, width=140).pack(side="left")
        btn(row2, "Refresh", self.refresh, "ghost", width=90).pack(side="left", padx=(8, 0))

        fw = Card(body)
        fw.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        frow = ctk.CTkFrame(fw, fg_color="transparent")
        frow.pack(fill="x", padx=20, pady=14)
        self.fw_lbl = label(frow, "Windows Firewall: checking...", 14, TEXT)
        self.fw_lbl.pack(side="left")
        self.fw_btn = btn(frow, "Allow through firewall", self.add_rule, width=190)
        self.fw_btn.pack(side="right")

        tips = Card(body)
        tips.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        label(tips, "IF FRIENDS CAN'T CONNECT", 11, MUTED, "bold").pack(anchor="w", padx=20, pady=(16, 6))
        self.tips_lbl = label(tips, "", 13, TEXT, wrap=44)
        self.tips_lbl.pack(fill="x", padx=20, pady=(0, 16))
        self.server_exe: Path | None = None
        self.port = host.DEFAULT_PORT
        self.public: str | None = None

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        game = self.app.status.get("game")
        self.server_exe = host.find_server(game)
        self.port = host.server_port(self.server_exe)
        if not self.server_exe:
            self.srv_state.configure(text="Server not found", text_color=WARN_C)
            self.srv_path.configure(
                text="Install the Skyrim Together Reborn mod (it's in the pack) and Deploy in Vortex.")
            set_on(self.start_btn, False)
            self.stop_btn.configure(state="disabled")
        else:
            running = host.server_running()
            self.srv_state.configure(text="Running" if running else "Stopped", text_color=OK_C if running else MUTED)
            self.srv_path.configure(text=str(self.server_exe))
            set_on(self.start_btn, not running)
            self.stop_btn.configure(state="normal" if running else "disabled")
        lip = host.local_ip()
        self.local_lbl.configure(text=f"Same Wi-Fi as you? They can use {lip}:{self.port}" if lip else "")
        self.tips_lbl.configure(text=(
            f"1. Port forwarding: in your router, forward UDP port {self.port} to this PC ({lip or 'your local IP'}). "
            "Give this PC a reserved/static IP in the router so the forward keeps working after reboots.\n"
            "2. Firewall: use the button above (Windows asks for admin permission).\n"
            "3. Still nothing? Your internet provider may use CGNAT, which blocks port forwarding. Free fix: "
            f"everyone installs Tailscale or Radmin VPN and connects to your Tailscale/Radmin IP on port {self.port}."))
        rule = host.firewall_rule_exists(self.port)
        if rule is None:
            self.fw_lbl.configure(text="Windows Firewall: can't check on this system", text_color=MUTED)
        elif rule:
            self.fw_lbl.configure(text=f"Windows Firewall: UDP {self.port} is allowed ✓", text_color=OK_C)
        else:
            self.fw_lbl.configure(text=f"Windows Firewall: no rule for UDP {self.port} yet", text_color=WARN_C)
        self.app.run_bg(host.public_ip, self.got_ip)

    def got_ip(self, ip: str | None) -> None:
        self.public = ip
        if ip:
            family = self.addr_lbl.cget("font").cget("family")
            self.addr_lbl.configure(text=f"{ip}:{self.port}", text_color=GOLD, font=F(22, "bold", family))
        else:
            self.addr_lbl.configure(text="Couldn't look up your public IP (offline?)", text_color=MUTED, font=F(14))

    def copy_addr(self) -> None:
        if self.public:
            self.app.copy(f"{self.public}:{self.port}", "Address copied")

    def start(self) -> None:
        if self.server_exe:
            host.start_server(self.server_exe)
            self.after(1500, self.refresh)

    def stop(self) -> None:
        host.stop_server()
        self.after(1000, self.refresh)

    def add_rule(self) -> None:
        if host.add_firewall_rule(self.port):
            self.after(3000, self.refresh)
        else:
            self.app.tell("Firewall", "Couldn't add the rule (admin permission was declined, or this isn't Windows).")
