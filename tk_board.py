"""
tk_board.py — HERC-26 Post-Run Playback Viewer (Tkinter + matplotlib)
=====================================================================
Run with:
    python tk_board.py

Two tabs:
  • Live Playback  — dashboard-style cards that update as playback runs
  • Charts         — full-run charts with a moving cursor line

Playback controls at the bottom work on both tabs.
    ⏮ rewind   ▶/⏸ play-pause   1× 2× 5× 10× speed   [seek slider]

Requirements:  pip install matplotlib pandas
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from pathlib import Path

# ── Colour palette ────────────────────────────────────────────────────────────
BG       = "#0b0f14"
BG2      = "#131920"
BG3      = "#1e2530"
FG       = "#e8eef6"
FGM      = "#7a8fa8"   # muted
GOOD     = "#22c55e"
BAD      = "#ef4444"
WARN     = "#f59e0b"
BLUE     = "#3b82f6"
CYAN     = "#6ae4ff"
CGRID    = "#1e2530"

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DBS  = {
    "Pi / real hardware  (rover_logs.sqlite)": str(PROJECT_ROOT / "data" / "rover_logs.sqlite"),
    "Sim / dev           (dev_logs.sqlite)":   str(PROJECT_ROOT / "data" / "dev_logs.sqlite"),
}
SPEEDS = [("1×", 1), ("2×", 2), ("5×", 5), ("10×", 10)]

# Chart config: (y-label, column, colour, extra_lines[(col, colour)])
CHARTS = [
    ("Battery %",   "batt_percentage",   GOOD,      []),
    ("Temp °C",     "temp_c",            WARN,      []),
    ("CO₂ ppm",     "co2_ppm",           CYAN,      []),
    ("G-Force (g)", "imu_g_force",       BAD,
        [("imu_accel_x", BAD), ("imu_accel_y", GOOD), ("imu_accel_z", CYAN)]),
    ("pH",          "water_ph",          "#38bdf8", []),
    ("Moisture %",  "soil_moisture_pct", "#a3e635", []),
]
CHART_VALID = [None, None, "air_valid",   None, "water_valid", "soil_valid"]
CHART_TOOL  = [None, None, "air",         None, "water",       "soil"]


# ── Application ───────────────────────────────────────────────────────────────
class TkBoard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HERC-26 Playback Viewer")
        self.root.configure(bg=BG)
        self.root.geometry("1420x920")
        self.root.minsize(900, 640)

        self._df: pd.DataFrame | None = None
        self._db_path   = ""
        self._sess_id   = ""
        self._sess_map: dict = {}
        self._play_idx  = 0
        self._playing   = False
        self._speed     = 1
        self._after_id  = None
        self._cursors: list = []

        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self._build_top_bar()
        # ⚠️  Pack the playback bar to BOTTOM *before* packing the expanding
        #     notebook — otherwise Tkinter gives all space to the notebook and
        #     the bar disappears off screen.
        self._build_playback_bar()

        nb = ttk.Notebook(self.root)
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._nb = nb

        live_frame   = tk.Frame(nb, bg=BG)
        charts_frame = tk.Frame(nb, bg=BG)
        nb.add(live_frame,   text="  Live Playback  ")
        nb.add(charts_frame, text="  Charts Overview  ")

        self._build_live_tab(live_frame)
        self._build_charts_tab(charts_frame)

        self._on_db_change()   # populate session list immediately

    # ── Top bar ───────────────────────────────────────────────────────────────
    def _build_top_bar(self):
        bar = tk.Frame(self.root, bg=BG2, pady=7, padx=12)
        bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(bar, text="DB:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))
        self._db_var = tk.StringVar(value=list(DEFAULT_DBS.keys())[0])
        db_box = ttk.Combobox(bar, textvariable=self._db_var,
                              values=list(DEFAULT_DBS.keys()), width=40, state="readonly")
        db_box.pack(side=tk.LEFT, padx=(0, 6))
        db_box.bind("<<ComboboxSelected>>", lambda _: self._on_db_change())

        tk.Button(bar, text="Browse…", command=self._browse_db,
                  bg=BG3, fg=FG, relief="flat", padx=8, pady=3
                  ).pack(side=tk.LEFT, padx=(0, 14))

        tk.Label(bar, text="Session:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))
        self._sess_var = tk.StringVar()
        self._sess_box = ttk.Combobox(bar, textvariable=self._sess_var,
                                      width=54, state="readonly")
        self._sess_box.pack(side=tk.LEFT, padx=(0, 8))
        self._sess_box.bind("<<ComboboxSelected>>", lambda _: self._on_sess_select())

        tk.Button(bar, text="Load", command=self._load_session,
                  bg=GOOD, fg=BG, relief="flat",
                  font=("Consolas", 10, "bold"), padx=14, pady=3
                  ).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="Select a session and click Load")
        tk.Label(bar, textvariable=self._status_var, bg=BG2, fg=FGM,
                 font=("Consolas", 9)).pack(side=tk.RIGHT, padx=(0, 4))

    # ── Playback bar ──────────────────────────────────────────────────────────
    def _build_playback_bar(self):
        bar = tk.Frame(self.root, bg=BG2, pady=8, padx=12)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(bar, text="⏮", command=self._rewind,
                  bg=BG3, fg=FG, relief="flat",
                  font=("Consolas", 12), padx=8, pady=3
                  ).pack(side=tk.LEFT, padx=(0, 4))

        self._play_btn = tk.Button(
            bar, text="▶  Play", command=self._toggle_play,
            bg=GOOD, fg=BG, relief="flat",
            font=("Consolas", 11, "bold"), padx=14, pady=3)
        self._play_btn.pack(side=tk.LEFT, padx=(0, 14))

        tk.Label(bar, text="Speed:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))
        self._speed_var = tk.StringVar(value="1×")
        for lbl, val in SPEEDS:
            tk.Radiobutton(
                bar, text=lbl, variable=self._speed_var, value=lbl,
                bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
                font=("Consolas", 10),
                command=lambda v=val: self._set_speed(v),
            ).pack(side=tk.LEFT, padx=3)

        self._time_var = tk.StringVar(value="0:00 / 0:00")
        tk.Label(bar, textvariable=self._time_var, bg=BG2, fg=FG,
                 font=("Consolas", 10), width=14).pack(side=tk.RIGHT, padx=(0, 6))

        self._prog_var = tk.DoubleVar(value=0)
        self._slider   = ttk.Scale(bar, from_=0, to=1000, orient=tk.HORIZONTAL,
                                   variable=self._prog_var, command=self._on_slider)
        self._slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 14))

    # ── Live playback tab ─────────────────────────────────────────────────────
    def _build_live_tab(self, parent):
        """
        Dashboard-style view:
          Row 1 — 4 large metric tiles (Battery, Temp, G-Force, CO₂)
          Row 2 — 3 task tool cards (Air, Water, Soil) with LED + value + phase
          Row 3 — Accel axes, Velocity axes, Rover status
        """
        # ── Row 1: big tiles ──────────────────────────────────────────────────
        r1 = tk.Frame(parent, bg=BG)
        r1.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 4))

        self._big: dict[str, tk.Label] = {}
        for key, label, color, unit, dec in [
            ("batt_percentage", "Battery",  GOOD,  "%",   1),
            ("temp_c",          "Temp",     WARN,  "°C",  2),
            ("imu_g_force",     "G-Force",  BAD,   "g",   3),
            ("co2_ppm",         "CO₂",      CYAN,  "ppm", 0),
        ]:
            tile, val_lbl = self._big_tile(r1, label, unit, color)
            tile.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
            self._big[key] = (val_lbl, dec)

        # ── Row 2: task cards ─────────────────────────────────────────────────
        r2 = tk.Frame(parent, bg=BG)
        r2.pack(side=tk.TOP, fill=tk.X, padx=10, pady=4)

        self._tasks: dict = {}
        for tool, title, vcol, unit, dec, col_on, col_valid, color in [
            ("air",   "AIR TASK",   "co2_ppm",          "ppm", 0, "mega_air_on",   "air_valid",   CYAN),
            ("water", "WATER TASK", "water_ph",          "",    2, "mega_water_on", "water_valid", "#38bdf8"),
            ("soil",  "SOIL TASK",  "soil_moisture_pct", "%",   1, "mega_soil_on",  "soil_valid",  "#a3e635"),
        ]:
            card, val_lbl, phase_lbl, led_cv, led_id = self._task_card(r2, title, unit, color)
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
            self._tasks[tool] = dict(
                card=card, val_lbl=val_lbl, phase_lbl=phase_lbl,
                led_cv=led_cv, led_id=led_id,
                vcol=vcol, dec=dec, col_on=col_on, col_valid=col_valid,
            )

        # ── Row 3: accel / velocity / rover status ────────────────────────────
        r3 = tk.Frame(parent, bg=BG)
        r3.pack(side=tk.TOP, fill=tk.X, padx=10, pady=4)

        self._accel: dict[str, tk.StringVar] = {}
        self._vel:   dict[str, tk.StringVar] = {}

        ac, ac_body = self._card(r3, "Accel (g)")
        ac.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        for axis, color in [("X", BAD), ("Y", GOOD), ("Z", CYAN)]:
            sv = self._kv_row(ac_body, f"Accel {axis}", color)
            self._accel[axis] = sv

        vc, vc_body = self._card(r3, "Velocity (m/s)")
        vc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        for axis, color in [("X", BAD), ("Y", GOOD), ("Z", CYAN)]:
            sv = self._kv_row(vc_body, f"Vel {axis}", color)
            self._vel[axis] = sv

        rc, rc_body = self._card(r3, "Rover Status")
        rc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self._rover: dict = {}
        for label, key in [
            ("Movement", "mega_movement"),
            ("RC Signal", "_rc"),
            ("GPS Lat",   "gps_lat"),
            ("GPS Lon",   "gps_lon"),
        ]:
            sv, lbl = self._kv_row_with_label(rc_body, label)
            self._rover[key] = (sv, lbl)

        # Elapsed progress strip
        ep = tk.Frame(parent, bg=BG2, padx=14, pady=8)
        ep.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(4, 8))
        self._elapsed_var = tk.StringVar(value="Elapsed:  0:00  /  0:00")
        tk.Label(ep, textvariable=self._elapsed_var, bg=BG2, fg=FG,
                 font=("Consolas", 13, "bold")).pack(anchor=tk.W)

    # ── Charts tab ────────────────────────────────────────────────────────────
    def _build_charts_tab(self, parent):
        n = len(CHARTS)
        self._fig = Figure(facecolor=BG)
        self._fig.subplots_adjust(hspace=0.52, left=0.07, right=0.97, top=0.98, bottom=0.04)
        self._axes: list = []
        for i, (title, _, _, _) in enumerate(CHARTS):
            ax = self._fig.add_subplot(n, 1, i + 1)
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=7, length=3)
            ax.set_ylabel(title, color=FGM, fontsize=7, labelpad=2)
            ax.grid(True, color=CGRID, linewidth=0.5)
            for sp in ax.spines.values():
                sp.set_edgecolor(CGRID)
            if i < n - 1:
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.tick_params(axis="x", labelsize=6, rotation=12)
            self._axes.append(ax)
        self._mpl_canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._mpl_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _big_tile(self, parent, label, unit, color):
        f = tk.Frame(parent, bg=BG2, padx=12, pady=10)
        tk.Label(f, text=label.upper(), bg=BG2, fg=FGM,
                 font=("Consolas", 9, "bold"), anchor=tk.W).pack(fill=tk.X)
        val = tk.Label(f, text="—", bg=BG2, fg=color,
                       font=("Consolas", 30, "bold"), anchor=tk.CENTER)
        val.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text=unit, bg=BG2, fg=FGM,
                 font=("Consolas", 10), anchor=tk.E).pack(fill=tk.X)
        return f, val

    def _task_card(self, parent, title, unit, color):
        f = tk.Frame(parent, bg=BG2, padx=12, pady=10)

        head = tk.Frame(f, bg=BG2)
        head.pack(fill=tk.X, pady=(0, 6))
        tk.Label(head, text=title, bg=BG2, fg=FG,
                 font=("Consolas", 11, "bold")).pack(side=tk.LEFT)

        # Small LED circle on the right of the header (blue = task active)
        cv = tk.Canvas(head, width=24, height=24, bg=BG2, highlightthickness=0)
        cv.pack(side=tk.RIGHT)
        lid = cv.create_oval(3, 3, 21, 21, fill=BG3, outline="")

        val_lbl = tk.Label(f, text="—", bg=BG2, fg=color,
                           font=("Consolas", 24, "bold"), anchor=tk.W)
        val_lbl.pack(fill=tk.X)
        tk.Label(f, text=unit, bg=BG2, fg=FGM,
                 font=("Consolas", 9), anchor=tk.W).pack(fill=tk.X)

        phase_lbl = tk.Label(f, text="—", bg=BG2, fg=FGM,
                              font=("Consolas", 9, "bold"), anchor=tk.W)
        phase_lbl.pack(fill=tk.X, pady=(4, 0))

        return f, val_lbl, phase_lbl, cv, lid

    def _card(self, parent, title):
        f    = tk.Frame(parent, bg=BG2, padx=12, pady=10)
        tk.Label(f, text=title.upper(), bg=BG2, fg=FGM,
                 font=("Consolas", 9, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 6))
        body = tk.Frame(f, bg=BG2)
        body.pack(fill=tk.BOTH, expand=True)
        return f, body

    def _kv_row(self, parent, label, color) -> tk.StringVar:
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text=label, bg=BG2, fg=FGM,
                 font=("Consolas", 9), width=9, anchor=tk.W).pack(side=tk.LEFT)
        sv = tk.StringVar(value="—")
        tk.Label(row, textvariable=sv, bg=BG2, fg=color,
                 font=("Consolas", 11, "bold"), anchor=tk.E).pack(side=tk.RIGHT)
        return sv

    def _kv_row_with_label(self, parent, label):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text=label, bg=BG2, fg=FGM,
                 font=("Consolas", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
        sv  = tk.StringVar(value="—")
        lbl = tk.Label(row, textvariable=sv, bg=BG2, fg=FG,
                       font=("Consolas", 11, "bold"), anchor=tk.E)
        lbl.pack(side=tk.RIGHT)
        return sv, lbl

    # ═══════════════════════════════════════════════════════════════════════════
    # DB / session loading
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_db_change(self):
        key = self._db_var.get()
        self._db_path = DEFAULT_DBS.get(key, key)
        self._populate_sessions()

    def _browse_db(self):
        p = filedialog.askopenfilename(
            title="Select SQLite database",
            filetypes=[("SQLite", "*.sqlite *.db"), ("All", "*.*")])
        if p:
            self._db_path = p
            self._db_var.set(p)
            self._populate_sessions()

    def _populate_sessions(self):
        if not Path(self._db_path).exists():
            self._status_var.set(f"Not found: {self._db_path}")
            return
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT session_id, started_utc, notes FROM sessions ORDER BY started_utc DESC"
            ).fetchall()
            conn.close()
        except Exception as e:
            self._status_var.set(f"DB error: {e}")
            return

        self._sess_map = {}
        labels = []
        for sid, ts, notes in rows:
            lbl = f"{ts[:19]}  —  {notes or '(no notes)'}"
            self._sess_map[lbl] = sid
            labels.append(lbl)

        self._sess_box["values"] = labels
        if labels:
            self._sess_box.set(labels[0])
            self._sess_id = self._sess_map[labels[0]]
            self._status_var.set(f"{len(labels)} session(s) — click Load")
        else:
            self._status_var.set("No sessions found")

    def _on_sess_select(self):
        self._sess_id = self._sess_map.get(self._sess_var.get(), "")

    def _load_session(self):
        if not self._sess_id:
            messagebox.showwarning("No session", "Select a session first.")
            return
        self._stop_playback()
        try:
            conn = sqlite3.connect(self._db_path)
            df   = pd.read_sql_query(
                "SELECT * FROM telemetry WHERE session_id=? ORDER BY id ASC",
                conn, params=(self._sess_id,))
            conn.close()
        except Exception as e:
            messagebox.showerror("Load error", str(e))
            return

        if df.empty:
            messagebox.showinfo("Empty", "No telemetry rows for this session.")
            return

        df["ts_utc"] = pd.to_datetime(df["ts_utc"])
        num = df.select_dtypes(include="number").columns
        df[num] = df[num].replace(-1.0, float("nan"))

        self._df        = df
        self._play_idx  = 0
        self._slider.configure(to=max(1, len(df) - 1))

        dur = (df["ts_utc"].iloc[-1] - df["ts_utc"].iloc[0]).total_seconds()
        m, s = divmod(int(dur), 60)
        self._status_var.set(f"Loaded {len(df):,} rows  ·  {m}m {s:02d}s")

        self._draw_charts()
        self._update_display(0)

    # ═══════════════════════════════════════════════════════════════════════════
    # Chart drawing (runs once per session load)
    # ═══════════════════════════════════════════════════════════════════════════

    def _draw_charts(self):
        df = self._df
        if df is None:
            return
        t = df["ts_utc"]
        self._cursors = []

        for ax, (title, col, color, extras), vcol, tool in zip(
            self._axes, CHARTS, CHART_VALID, CHART_TOOL
        ):
            ax.clear()
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=7, length=3)
            ax.set_ylabel(title, color=FGM, fontsize=7, labelpad=2)
            ax.grid(True, color=CGRID, linewidth=0.5)
            for sp in ax.spines.values():
                sp.set_edgecolor(CGRID)

            if col in df.columns:
                ax.plot(t, df[col], color=color, linewidth=1.2, alpha=0.9)
            for ecol, ecol_color in extras:
                if ecol in df.columns:
                    ax.plot(t, df[ecol], color=ecol_color, linewidth=0.8, alpha=0.55)

            if vcol and vcol in df.columns:
                self._shade_valid(ax, df, vcol)
            if tool:
                col_on = f"mega_{tool}_on"
                if col_on in df.columns and vcol and vcol in df.columns:
                    self._shade_misfires(ax, df, col_on, vcol)

            cur = ax.axvline(x=t.iloc[0], color="white",
                             linewidth=1.5, alpha=0.70, linestyle="--", zorder=10)
            self._cursors.append(cur)

        self._mpl_canvas.draw()

    def _shade_valid(self, ax, df, vcol):
        in_span, t0, prev_t = False, None, None
        for _, row in df.iterrows():
            if row.get(vcol, 0) == 1 and not in_span:
                in_span, t0 = True, row["ts_utc"]
            elif row.get(vcol, 0) != 1 and in_span:
                ax.axvspan(t0, prev_t, color=GOOD, alpha=0.15, zorder=0)
                in_span = False
            prev_t = row["ts_utc"]
        if in_span and t0 is not None:
            ax.axvspan(t0, df["ts_utc"].iloc[-1], color=GOOD, alpha=0.15, zorder=0)

    def _shade_misfires(self, ax, df, col_on, col_valid):
        in_run, t0, had_v = False, None, False
        for _, row in df.iterrows():
            on    = row.get(col_on,    0) == 1
            valid = row.get(col_valid, 0) == 1
            if on and not in_run:
                in_run, t0, had_v = True, row["ts_utc"], False
            if on and valid:
                had_v = True
            if not on and in_run:
                if not had_v:
                    ax.axvspan(t0, row["ts_utc"], color=BAD, alpha=0.10, zorder=0)
                in_run = False
        if in_run and not had_v and t0 is not None:
            ax.axvspan(t0, df["ts_utc"].iloc[-1], color=BAD, alpha=0.10, zorder=0)

    # ═══════════════════════════════════════════════════════════════════════════
    # Display update — called every playback tick
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_display(self, idx: int):
        df = self._df
        if df is None:
            return
        idx = max(0, min(idx, len(df) - 1))
        row = df.iloc[idx]
        t0  = df["ts_utc"].iloc[0]
        elapsed = (row["ts_utc"] - t0).total_seconds()
        total   = (df["ts_utc"].iloc[-1] - t0).total_seconds()

        def _f(key, dec=2):
            try:
                v = float(row.get(key, float("nan")))
                return "—" if v != v else f"{v:.{dec}f}"   # nan != nan
            except Exception:
                s = str(row.get(key, ""))
                return s if s and s not in ("nan", "None", "") else "—"

        def _fmt_t(sec):
            m, s = divmod(int(max(0, sec)), 60)
            return f"{m}:{s:02d}"

        # ── Big tiles ─────────────────────────────────────────────────────────
        for key, (lbl, dec) in self._big.items():
            lbl.configure(text=_f(key, dec))

        # ── Task cards ────────────────────────────────────────────────────────
        for tool, td in self._tasks.items():
            td["val_lbl"].configure(text=_f(td["vcol"], td["dec"]))

            # Activation LED (blue = on)
            try:
                on = int(row.get(td["col_on"], 0)) == 1
            except Exception:
                on = False
            td["led_cv"].itemconfig(td["led_id"], fill=BLUE if on else BG3)

            # Phase text
            phase_col = f"{tool}_phase"
            phase     = str(row.get(phase_col, "off")) if phase_col in df.columns else "off"
            valid     = row.get(td["col_valid"], 0) == 1

            if valid:
                td["phase_lbl"].configure(text="✓  VALID", fg=GOOD)
            elif phase == "done":
                td["phase_lbl"].configure(text="✓  DONE",  fg=GOOD)
            elif on and phase not in ("off",):
                td["phase_lbl"].configure(text=phase.upper(), fg=WARN)
            else:
                td["phase_lbl"].configure(text="OFF", fg=FGM)

        # ── Accel / Velocity ──────────────────────────────────────────────────
        self._accel["X"].set(_f("imu_accel_x", 3))
        self._accel["Y"].set(_f("imu_accel_y", 3))
        self._accel["Z"].set(_f("imu_accel_z", 3))
        self._vel["X"].set(_f("imu_vel_x", 3))
        self._vel["Y"].set(_f("imu_vel_y", 3))
        self._vel["Z"].set(_f("imu_vel_z", 3))

        # ── Rover status ──────────────────────────────────────────────────────
        self._rover["mega_movement"][0].set(_f("mega_movement"))
        try:
            rc_on = int(row.get("mega_ibus_pulse", float("nan"))) == 1
            self._rover["_rc"][0].set("OK" if rc_on else "LOST")
            self._rover["_rc"][1].configure(fg=GOOD if rc_on else BAD)
        except Exception:
            self._rover["_rc"][0].set("—")
        self._rover["gps_lat"][0].set(_f("gps_lat", 6))
        self._rover["gps_lon"][0].set(_f("gps_lon", 6))

        # ── Time / progress ───────────────────────────────────────────────────
        self._elapsed_var.set(f"Elapsed:   {_fmt_t(elapsed)}   /   {_fmt_t(total)}")
        self._time_var.set(f"{_fmt_t(elapsed)} / {_fmt_t(total)}")
        self._prog_var.set(idx)

        # ── Move cursor on charts tab ─────────────────────────────────────────
        cur_t = row["ts_utc"]
        for line in self._cursors:
            line.set_xdata([cur_t, cur_t])
        self._mpl_canvas.draw_idle()

    # ═══════════════════════════════════════════════════════════════════════════
    # Playback controls
    # ═══════════════════════════════════════════════════════════════════════════

    def _toggle_play(self):
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        if self._df is None:
            messagebox.showinfo("No data", "Load a session first.")
            return
        if self._play_idx >= len(self._df) - 1:
            self._play_idx = 0
        self._playing = True
        self._play_btn.configure(text="⏸  Pause", bg=WARN, fg=BG)
        self._tick()

    def _stop_playback(self):
        self._playing = False
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._play_btn.configure(text="▶  Play", bg=GOOD, fg=BG)

    def _tick(self):
        if not self._playing or self._df is None:
            return
        if self._play_idx >= len(self._df) - 1:
            self._stop_playback()
            return

        self._play_idx += 1
        self._update_display(self._play_idx)

        # Honour real-time interval between samples, scaled by speed
        df = self._df
        if self._play_idx + 1 < len(df):
            dt_ms = (df["ts_utc"].iloc[self._play_idx + 1]
                     - df["ts_utc"].iloc[self._play_idx]).total_seconds() * 1000
            delay = max(16, int(dt_ms / self._speed))
        else:
            delay = 500

        self._after_id = self.root.after(delay, self._tick)

    def _rewind(self):
        self._stop_playback()
        if self._df is not None:
            self._play_idx = 0
            self._update_display(0)

    def _set_speed(self, val: int):
        self._speed = val

    def _on_slider(self, val):
        if self._df is None:
            return
        idx = int(float(val))
        self._play_idx = idx
        self._update_display(idx)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    try:
        s = ttk.Style(root)
        s.theme_use("clam")
        s.configure("TCombobox",   fieldbackground=BG3, background=BG3,
                    foreground=FG, selectbackground=BG3)
        s.configure("TScale",      background=BG2, troughcolor=BG3)
        s.configure("TNotebook",   background=BG,  borderwidth=0)
        s.configure("TNotebook.Tab", background=BG2, foreground=FG,
                    padding=[14, 6], font=("Consolas", 10))
        s.map("TNotebook.Tab",
              background=[("selected", BG3)],
              foreground=[("selected", CYAN)])
    except Exception:
        pass

    TkBoard(root)
    root.mainloop()


if __name__ == "__main__":
    main()