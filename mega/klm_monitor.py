"""
klm_monitor.py — HERC-26 Mega KLM Serial Monitor
Team MOVIS | Human Exploration Rover Challenge

Reads JSON debug lines from klm.ino over Serial (115200 baud) and displays
live rover state in a Tkinter GUI.

Run:
    python mega/klm_monitor.py

Requires:
    pip install pyserial
"""

import tkinter as tk
from tkinter import ttk, font
import serial
import serial.tools.list_ports
import threading
import json
import time

# ── Colour palette (matches web/templates/index.html) ───────────────────────
BG        = "#0b0f14"
CARD      = "#161b22"
PANEL     = "#1e2530"
GOOD      = "#22c55e"
BAD       = "#ef4444"
WARN      = "#f59e0b"
INFO      = "#3b82f6"
TEXT      = "#e2e8f0"
MUTED     = "#64748b"
MOVE_COL  = {"STOP": MUTED, "FWD": GOOD, "BACK": WARN, "LEFT": INFO, "RIGHT": INFO}

# ── LED helper ───────────────────────────────────────────────────────────────
def make_led(parent, size=18):
    c = tk.Canvas(parent, width=size, height=size, bg=CARD, highlightthickness=0)
    oval = c.create_oval(2, 2, size-2, size-2, fill=MUTED, outline="")
    return c, oval

def set_led(canvas, oval, state, on_col=GOOD, off_col=MUTED):
    canvas.itemconfig(oval, fill=on_col if state else off_col)


# ── Main monitor class ───────────────────────────────────────────────────────
class KLMMonitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HERC-26 Mega KLM Monitor")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self._port: serial.Serial | None = None
        self._running = False
        self._latest: dict = {}
        self._last_rx = 0.0

        self._build_ui()
        self._refresh_ports()
        self._schedule_update()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        tf = ("Consolas", 10)
        tf_b = ("Consolas", 10, "bold")
        tf_lg = ("Consolas", 13, "bold")
        tf_xl = ("Consolas", 18, "bold")

        pad = dict(padx=6, pady=4)

        # ── Top bar ──────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 0))

        tk.Label(top, text="PORT:", bg=BG, fg=MUTED, font=tf).pack(side="left")
        self._port_var = tk.StringVar()
        self._port_cb = ttk.Combobox(top, textvariable=self._port_var,
                                     width=14, state="readonly", font=tf)
        self._port_cb.pack(side="left", padx=(4, 6))

        self._btn = tk.Button(top, text="CONNECT", font=tf_b,
                              bg=INFO, fg="white", activebackground="#2563eb",
                              relief="flat", padx=10,
                              command=self._toggle_connect)
        self._btn.pack(side="left")

        tk.Button(top, text="↺", font=tf_b, bg=PANEL, fg=MUTED,
                  relief="flat", padx=6,
                  command=self._refresh_ports).pack(side="left", padx=4)

        self._status_lbl = tk.Label(top, text="● DISCONNECTED",
                                    bg=BG, fg=BAD, font=tf_b)
        self._status_lbl.pack(side="left", padx=10)

        self._age_lbl = tk.Label(top, text="", bg=BG, fg=MUTED, font=tf)
        self._age_lbl.pack(side="right")

        # ── Main grid (3 columns) ────────────────────────────────────────────
        main = tk.Frame(self.root, bg=BG)
        main.pack(padx=8, pady=8)

        # Row 0 — Safety | Drive | RC Channels
        self._build_safety(main, 0, 0)
        self._build_drive(main, 0, 1)
        self._build_channels(main, 0, 2)

        # Row 1 — Tools (spans 2) | Arm
        self._build_tools(main, 1, 0, colspan=2)
        self._build_arm(main, 1, 2)

        # Row 2 — I2C packet (full width)
        self._build_i2c(main, 2, 0, colspan=3)

    def _card(self, parent, title, row, col, colspan=1, rowspan=1):
        """Create a labelled dark card and return its inner frame."""
        frame = tk.Frame(parent, bg=CARD, bd=0, relief="flat")
        frame.grid(row=row, column=col, columnspan=colspan, rowspan=rowspan,
                   padx=4, pady=4, sticky="nsew")
        tk.Label(frame, text=title.upper(), bg=CARD, fg=MUTED,
                 font=("Consolas", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        return inner

    # ── Safety panel ─────────────────────────────────────────────────────────
    def _build_safety(self, parent, row, col):
        f = self._card(parent, "Safety", row, col)

        def led_row(text, col_on=GOOD):
            r = tk.Frame(f, bg=CARD)
            r.pack(anchor="w", pady=2)
            c, o = make_led(r, 16)
            c.pack(side="left", padx=(0, 6))
            tk.Label(r, text=text, bg=CARD, fg=TEXT,
                     font=("Consolas", 10)).pack(side="left")
            return c, o

        self._led_sig,  self._ov_sig  = led_row("SIGNAL")
        self._led_kill, self._ov_kill = led_row("KILL",     BAD)
        self._led_fs,   self._ov_fs   = led_row("FAILSAFE", BAD)
        self._led_test, self._ov_test = led_row("TEST MODE", WARN)

    # ── Drive panel ───────────────────────────────────────────────────────────
    def _build_drive(self, parent, row, col):
        f = self._card(parent, "Drive", row, col)

        # Movement state pill
        self._move_lbl = tk.Label(f, text="STOP", width=8,
                                  bg=MUTED, fg="white",
                                  font=("Consolas", 13, "bold"),
                                  relief="flat")
        self._move_lbl.pack(pady=(2, 6))

        # Speed bars
        bar_w, bar_h = 180, 18
        mid = bar_w // 2

        for side in ("L", "R"):
            row_f = tk.Frame(f, bg=CARD)
            row_f.pack(anchor="w", pady=2)
            tk.Label(row_f, text=f"{side}:", width=2, bg=CARD, fg=MUTED,
                     font=("Consolas", 10)).pack(side="left")
            c = tk.Canvas(row_f, width=bar_w, height=bar_h,
                          bg=PANEL, highlightthickness=0)
            c.pack(side="left", padx=4)
            c.create_line(mid, 0, mid, bar_h, fill=MUTED, width=1)
            bar = c.create_rectangle(mid, 2, mid, bar_h-2, fill=INFO, outline="")
            lbl = tk.Label(row_f, text="   0", width=5, bg=CARD, fg=TEXT,
                           font=("Consolas", 10))
            lbl.pack(side="left")
            if side == "L":
                self._bar_L, self._bar_canvas_L, self._speed_lbl_L = bar, c, lbl
                self._bar_mid_L = mid
            else:
                self._bar_R, self._bar_canvas_R, self._speed_lbl_R = bar, c, lbl
                self._bar_mid_R = mid
        self._bar_w = bar_w
        self._bar_h = bar_h

    def _update_speed_bar(self, canvas, bar, mid, bar_w, bar_h, speed):
        frac = speed / 255.0
        x = mid + int(frac * mid)
        x = max(1, min(bar_w - 1, x))
        x1, x2 = (x, mid) if x < mid else (mid, x)
        col = BAD if speed < 0 else (GOOD if speed > 0 else MUTED)
        canvas.coords(bar, x1, 2, x2, bar_h - 2)
        canvas.itemconfig(bar, fill=col)

    # ── Tools panel ──────────────────────────────────────────────────────────
    def _build_tools(self, parent, row, col, colspan=1):
        f = self._card(parent, "Task Tools", row, col, colspan=colspan)

        row1 = tk.Frame(f, bg=CARD)
        row1.pack(anchor="w")

        def tool_widget(parent, name):
            g = tk.Frame(parent, bg=CARD)
            g.pack(side="left", padx=12)
            c, o = make_led(g, 22)
            c.pack()
            tk.Label(g, text=name, bg=CARD, fg=MUTED,
                     font=("Consolas", 9)).pack()
            return c, o

        self._led_air,   self._ov_air   = tool_widget(row1, "AIR")
        self._led_water, self._ov_water = tool_widget(row1, "WATER")
        self._led_soil,  self._ov_soil  = tool_widget(row1, "SOIL")

        # Pump row
        pump_f = tk.Frame(f, bg=CARD)
        pump_f.pack(anchor="w", pady=(6, 0), fill="x")

        tk.Label(pump_f, text="PUMP:", bg=CARD, fg=MUTED,
                 font=("Consolas", 10)).pack(side="left")

        self._pump_led_c, self._pump_led_o = make_led(pump_f, 14)
        self._pump_led_c.pack(side="left", padx=4)

        pump_bar_w = 140
        self._pump_canvas = tk.Canvas(pump_f, width=pump_bar_w, height=14,
                                      bg=PANEL, highlightthickness=0)
        self._pump_canvas.pack(side="left", padx=4)
        self._pump_bar = self._pump_canvas.create_rectangle(
            0, 1, 0, 13, fill=WARN, outline="")
        self._pump_bar_w = pump_bar_w

        self._pump_lbl = tk.Label(pump_f, text="0.0s", width=5,
                                  bg=CARD, fg=TEXT, font=("Consolas", 10))
        self._pump_lbl.pack(side="left")

    # ── Arm panel ────────────────────────────────────────────────────────────
    def _build_arm(self, parent, row, col):
        f = self._card(parent, "Arm", row, col)

        self._arm_state_lbl = tk.Label(f, text="IDLE", width=8,
                                       bg=PANEL, fg=MUTED,
                                       font=("Consolas", 11, "bold"))
        self._arm_state_lbl.pack(pady=(0, 6))

        self._arm_angle_lbls = {}
        for joint in ("θ1 (base)", "θ2 (elbow)", "θ3 (wrist)"):
            r = tk.Frame(f, bg=CARD)
            r.pack(anchor="w", pady=1)
            tk.Label(r, text=joint + ":", width=11, anchor="w",
                     bg=CARD, fg=MUTED, font=("Consolas", 10)).pack(side="left")
            lbl = tk.Label(r, text="  0.0°", width=8,
                           bg=CARD, fg=TEXT, font=("Consolas", 10, "bold"))
            lbl.pack(side="left")
            self._arm_angle_lbls[joint] = lbl

    # ── I2C packet panel ─────────────────────────────────────────────────────
    def _build_i2c(self, parent, row, col, colspan=1):
        f = self._card(parent, "I2C Packet → Raspberry Pi  (6 bytes at address 0x08)",
                       row, col, colspan=colspan)

        names = ["air", "water", "soil", "move", "ch3_lo", "ch3_hi"]
        self._i2c_labels = []

        row_f = tk.Frame(f, bg=CARD)
        row_f.pack(anchor="w")

        for name in names:
            cell = tk.Frame(row_f, bg=PANEL, padx=6, pady=4)
            cell.pack(side="left", padx=3)
            val_lbl = tk.Label(cell, text="0", width=6,
                               bg=PANEL, fg=TEXT, font=("Consolas", 14, "bold"))
            val_lbl.pack()
            tk.Label(cell, text=name, bg=PANEL, fg=MUTED,
                     font=("Consolas", 8)).pack()
            self._i2c_labels.append(val_lbl)

    # ── RC channels panel ────────────────────────────────────────────────────
    def _build_channels(self, parent, row, col):
        f = self._card(parent, "RC Channels (µs)", row, col)

        channels = [
            ("CH1 turn",  "ch1"), ("CH5 air",   "ch5"),
            ("CH2 fwd",   "ch2"), ("CH6 kill",  "ch6"),
            ("CH3 scale", "ch3"), ("CH7 water", "ch7"),
            ("",          ""),    ("CH8 soil",  "ch8"),
        ]

        self._ch_labels = {}
        for i, (label, key) in enumerate(channels):
            r_idx = i // 2
            c_idx = (i % 2) * 2
            if not label:
                continue
            tk.Label(f, text=label + ":", width=10, anchor="e",
                     bg=CARD, fg=MUTED, font=("Consolas", 9)).grid(
                row=r_idx, column=c_idx, sticky="e", padx=(0, 2))
            lbl = tk.Label(f, text="----", width=5,
                           bg=CARD, fg=TEXT, font=("Consolas", 10, "bold"))
            lbl.grid(row=r_idx, column=c_idx + 1, sticky="w")
            self._ch_labels[key] = lbl

    # ── Serial connection ────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb["values"] = ports
        if ports and not self._port_var.get():
            self._port_var.set(ports[0])

    def _toggle_connect(self):
        if self._running:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self._port_var.get()
        if not port:
            return
        try:
            self._port = serial.Serial(port, 115200, timeout=1)
            self._running = True
            self._btn.config(text="DISCONNECT", bg=BAD)
            self._status_lbl.config(text="● CONNECTED", fg=GOOD)
            t = threading.Thread(target=self._read_loop, daemon=True)
            t.start()
        except serial.SerialException as e:
            self._status_lbl.config(text=f"● ERROR: {e}", fg=BAD)

    def _disconnect(self):
        self._running = False
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None
        self._btn.config(text="CONNECT", bg=INFO)
        self._status_lbl.config(text="● DISCONNECTED", fg=BAD)

    def _read_loop(self):
        """Background thread: read JSON lines from Serial."""
        buf = ""
        while self._running:
            try:
                if self._port and self._port.in_waiting:
                    buf += self._port.read(self._port.in_waiting).decode("utf-8", errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line.startswith("{"):
                            try:
                                data = json.loads(line)
                                self._latest = data
                                self._last_rx = time.time()
                            except json.JSONDecodeError:
                                pass
                else:
                    time.sleep(0.005)
            except (serial.SerialException, OSError):
                self._running = False
                self.root.after(0, self._disconnect)
                break

    # ── UI update loop ───────────────────────────────────────────────────────

    def _schedule_update(self):
        self._update_ui()
        self.root.after(50, self._schedule_update)   # 20 Hz UI refresh

    def _update_ui(self):
        d = self._latest
        if not d:
            return

        age = time.time() - self._last_rx if self._last_rx else 999
        stale = age > 1.0
        self._age_lbl.config(
            text=f"Last rx: {age*1000:.0f} ms ago" if age < 10 else "NO DATA",
            fg=BAD if stale else MUTED)

        # Safety
        set_led(self._led_sig,  self._ov_sig,  d.get("sig",  0))
        set_led(self._led_kill, self._ov_kill, d.get("kill", 0), BAD, MUTED)
        set_led(self._led_fs,   self._ov_fs,   d.get("fs",   0), BAD, MUTED)
        set_led(self._led_test, self._ov_test, d.get("test", 0), WARN, MUTED)

        # Drive — movement pill
        move = d.get("move", "STOP")
        self._move_lbl.config(text=move, bg=MOVE_COL.get(move, MUTED))

        # Drive — speed bars
        spL = d.get("spL", 0)
        spR = d.get("spR", 0)
        self._update_speed_bar(self._bar_canvas_L, self._bar_L,
                               self._bar_mid_L, self._bar_w, self._bar_h, spL)
        self._update_speed_bar(self._bar_canvas_R, self._bar_R,
                               self._bar_mid_R, self._bar_w, self._bar_h, spR)
        self._speed_lbl_L.config(text=f"{spL:+4d}")
        self._speed_lbl_R.config(text=f"{spR:+4d}")

        # Tools — LEDs
        set_led(self._led_air,   self._ov_air,   d.get("air",   0))
        set_led(self._led_water, self._ov_water, d.get("water", 0))
        set_led(self._led_soil,  self._ov_soil,  d.get("soil",  0))

        # Pump
        pump_on = d.get("pump", 0)
        pump_t  = d.get("pumpT", 0.0)
        set_led(self._pump_led_c, self._pump_led_o, pump_on, WARN, MUTED)
        frac = min(1.0, pump_t / 5.0) if pump_on else 0.0
        bw = int(frac * self._pump_bar_w)
        self._pump_canvas.coords(self._pump_bar, 0, 1, max(0, bw), 13)
        self._pump_lbl.config(text=f"{pump_t:.1f}s", fg=WARN if pump_on else MUTED)

        # Arm
        arm_on = d.get("arm", 0)
        self._arm_state_lbl.config(
            text="RUNNING" if arm_on else "IDLE",
            bg=GOOD if arm_on else PANEL,
            fg="white" if arm_on else MUTED)
        joints = ["θ1 (base)", "θ2 (elbow)", "θ3 (wrist)"]
        keys   = ["th1", "th2", "th3"]
        for joint, key in zip(joints, keys):
            val = d.get(key, 0.0)
            self._arm_angle_lbls[joint].config(text=f"{val:6.1f}°",
                                               fg=GOOD if arm_on else TEXT)

        # I2C packet
        i2c = d.get("i2c", [0]*6)
        move_names = {0:"STOP",1:"FWD",2:"BACK",3:"LEFT",4:"RIGHT"}
        for idx, lbl in enumerate(self._i2c_labels):
            if idx < len(i2c):
                val = i2c[idx]
                # Colour the tool bytes
                if idx in (0, 1, 2):
                    col = GOOD if val else TEXT
                elif idx == 3:
                    col = MOVE_COL.get(move_names.get(val, "STOP"), MUTED)
                else:
                    col = TEXT
                lbl.config(text=str(val), fg=col)

        # RC channels
        for key, lbl in self._ch_labels.items():
            val = d.get(key, 0)
            # Colour kill/failsafe channels
            if key == "ch6" and val > 1500:
                col = BAD
            elif key in ("ch5", "ch7", "ch8") and val > 1500:
                col = GOOD
            else:
                col = TEXT
            lbl.config(text=str(val), fg=col)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = KLMMonitor(root)
    root.mainloop()