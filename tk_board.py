"""
tk_board.py — HERC-26 Post-Run Playback Viewer (Tkinter + matplotlib)
=====================================================================
Run with:
    python tk_board.py

Requirements: matplotlib, pandas
    pip install matplotlib pandas
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

# ── Colours ───────────────────────────────────────────────────────────────────
BG       = "#0b0f14"
BG2      = "#131920"
BG3      = "#1e2530"
FG       = "#e8eef6"
FG_MUTED = "#7a8fa8"
GOOD     = "#22c55e"
BAD      = "#ef4444"
WARN     = "#f59e0b"
BLUE     = "#3b82f6"
CYAN     = "#6ae4ff"
C_GRID   = "#1e2530"
C_CURSOR = "#ffffff"

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DBS = {
    "Pi / real hardware  (rover_logs.sqlite)": str(PROJECT_ROOT / "data" / "rover_logs.sqlite"),
    "Sim / dev           (dev_logs.sqlite)":   str(PROJECT_ROOT / "data" / "dev_logs.sqlite"),
}
SPEEDS = [("1×", 1), ("2×", 2), ("5×", 5), ("10×", 10)]

# Chart definitions: (label, column, line_colour, extra_cols)
#   extra_cols: list of (col, colour) drawn on the same axes (e.g. accel x/y/z)
CHARTS = [
    ("Battery %",   "batt_percentage",   GOOD,  []),
    ("Temp °C",     "temp_c",            WARN,  []),
    ("CO₂ ppm",     "co2_ppm",           CYAN,  []),
    ("G-Force (g)", "imu_g_force",       BAD,
        [("imu_accel_x", BAD), ("imu_accel_y", GOOD), ("imu_accel_z", CYAN)]),
    ("pH",          "water_ph",          "#38bdf8", []),
    ("Moisture %",  "soil_moisture_pct", "#a3e635", []),
]

# Which valid column to shade per chart (None = no shading)
CHART_VALID = [None, None, "air_valid", None, "water_valid", "soil_valid"]
CHART_TOOL  = [None, None, "air",       None, "water",       "soil"]


# ── Main application ──────────────────────────────────────────────────────────
class TkBoard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HERC-26 Playback Viewer")
        self.root.configure(bg=BG)
        self.root.geometry("1400x900")
        self.root.minsize(900, 600)

        self._df: pd.DataFrame | None = None
        self._db_path: str             = ""
        self._session_id: str          = ""
        self._sess_map: dict           = {}
        self._play_idx: int            = 0
        self._playing: bool            = False
        self._speed: int               = 1
        self._after_id                 = None
        self._cursor_lines: list       = []

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_top_bar()
        main = tk.Frame(self.root, bg=BG)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._build_metrics_panel(main)
        self._build_charts_panel(main)
        self._build_playback_bar()
        self._on_db_change()          # populate sessions immediately

    def _build_top_bar(self):
        bar = tk.Frame(self.root, bg=BG2, pady=7, padx=12)
        bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(bar, text="DB:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))

        self._db_var = tk.StringVar(value=list(DEFAULT_DBS.keys())[0])
        db_box = ttk.Combobox(bar, textvariable=self._db_var,
                              values=list(DEFAULT_DBS.keys()), width=38, state="readonly")
        db_box.pack(side=tk.LEFT, padx=(0, 6))
        db_box.bind("<<ComboboxSelected>>", lambda _: self._on_db_change())

        tk.Button(bar, text="Browse…", command=self._browse_db,
                  bg=BG3, fg=FG, relief="flat", padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(bar, text="Session:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))

        self._sess_var = tk.StringVar()
        self._sess_box = ttk.Combobox(bar, textvariable=self._sess_var, width=52, state="readonly")
        self._sess_box.pack(side=tk.LEFT, padx=(0, 8))
        self._sess_box.bind("<<ComboboxSelected>>", lambda _: self._on_session_select())

        tk.Button(bar, text="Load", command=self._load_session,
                  bg=GOOD, fg=BG, relief="flat", font=("Consolas", 10, "bold"),
                  padx=14, pady=3).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="Select a session and click Load")
        tk.Label(bar, textvariable=self._status_var, bg=BG2, fg=FG_MUTED,
                 font=("Consolas", 9)).pack(side=tk.RIGHT, padx=(0, 4))

    def _build_metrics_panel(self, parent: tk.Frame):
        panel = tk.Frame(parent, bg=BG2, width=170, padx=10, pady=10)
        panel.pack(side=tk.LEFT, fill=tk.Y)
        panel.pack_propagate(False)

        tk.Label(panel, text="LIVE VALUES", bg=BG2, fg=CYAN,
                 font=("Consolas", 10, "bold")).pack(anchor=tk.W, pady=(0, 6))

        self._mvar: dict[str, tk.StringVar] = {}

        def _row(label: str, key: str):
            f = tk.Frame(panel, bg=BG2)
            f.pack(fill=tk.X, pady=1)
            tk.Label(f, text=label, bg=BG2, fg=FG_MUTED,
                     font=("Consolas", 8), anchor=tk.W, width=12).pack(side=tk.LEFT)
            v = tk.StringVar(value="—")
            tk.Label(f, textvariable=v, bg=BG2, fg=FG,
                     font=("Consolas", 9, "bold"), anchor=tk.E).pack(side=tk.RIGHT)
            self._mvar[key] = v

        _row("Time",      "_time")
        _row("Elapsed",   "_elapsed")
        tk.Frame(panel, bg=BG3, height=1).pack(fill=tk.X, pady=4)
        _row("Battery %", "batt_percentage")
        _row("Voltage V", "power_voltage_v")
        _row("Temp °C",   "temp_c")
        tk.Frame(panel, bg=BG3, height=1).pack(fill=tk.X, pady=4)
        _row("CO₂ ppm",   "co2_ppm")
        _row("pH",        "water_ph")
        _row("Moisture%", "soil_moisture_pct")
        tk.Frame(panel, bg=BG3, height=1).pack(fill=tk.X, pady=4)
        _row("G-Force g", "imu_g_force")
        _row("Accel X g", "imu_accel_x")
        _row("Accel Y g", "imu_accel_y")
        _row("Accel Z g", "imu_accel_z")
        tk.Frame(panel, bg=BG3, height=1).pack(fill=tk.X, pady=4)
        _row("Movement",  "mega_movement")
        _row("RC",        "_rc")

        # Tool activation indicators
        tk.Label(panel, text="TOOLS", bg=BG2, fg=CYAN,
                 font=("Consolas", 10, "bold")).pack(anchor=tk.W, pady=(10, 4))

        self._tool_var: dict[str, tk.StringVar] = {}
        self._tool_lbl: dict[str, tk.Label]     = {}
        for tool in ("AIR", "WATER", "SOIL"):
            f = tk.Frame(panel, bg=BG2)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=tool, bg=BG2, fg=FG_MUTED,
                     font=("Consolas", 8), width=6, anchor=tk.W).pack(side=tk.LEFT)
            v = tk.StringVar(value="OFF")
            lbl = tk.Label(f, textvariable=v, bg=BG2, fg=BAD,
                           font=("Consolas", 9, "bold"), anchor=tk.E)
            lbl.pack(side=tk.RIGHT)
            self._tool_var[tool] = v
            self._tool_lbl[tool] = lbl

    def _build_charts_panel(self, parent: tk.Frame):
        n = len(CHARTS)
        self._fig = Figure(facecolor=BG)
        self._fig.subplots_adjust(hspace=0.55, left=0.07, right=0.97, top=0.98, bottom=0.04)

        self._axes: list = []
        for i, (title, _, _, _) in enumerate(CHARTS):
            ax = self._fig.add_subplot(n, 1, i + 1)
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=7, length=3)
            ax.set_ylabel(title, color=FG_MUTED, fontsize=7, labelpad=2)
            ax.grid(True, color=C_GRID, linewidth=0.5, linestyle="-")
            for spine in ax.spines.values():
                spine.set_edgecolor(C_GRID)
            # Only show x-tick labels on the last subplot
            if i < n - 1:
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.tick_params(axis="x", labelsize=6, rotation=15)
            self._axes.append(ax)

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_playback_bar(self):
        bar = tk.Frame(self.root, bg=BG2, pady=8, padx=12)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Rewind
        tk.Button(bar, text="⏮", command=self._rewind,
                  bg=BG3, fg=FG, relief="flat", font=("Consolas", 12),
                  padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 4))

        # Play / Pause
        self._play_btn = tk.Button(bar, text="▶  Play", command=self._toggle_play,
                                   bg=GOOD, fg=BG, relief="flat",
                                   font=("Consolas", 11, "bold"), padx=14, pady=3)
        self._play_btn.pack(side=tk.LEFT, padx=(0, 16))

        # Speed selector
        tk.Label(bar, text="Speed:", bg=BG2, fg=FG,
                 font=("Consolas", 10)).pack(side=tk.LEFT, padx=(0, 4))
        self._speed_var = tk.StringVar(value="1×")
        for label, val in SPEEDS:
            tk.Radiobutton(
                bar, text=label, variable=self._speed_var, value=label,
                bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
                font=("Consolas", 10), command=lambda v=val: self._set_speed(v),
            ).pack(side=tk.LEFT, padx=3)

        # Time label (right side)
        self._time_label = tk.StringVar(value="0:00 / 0:00")
        tk.Label(bar, textvariable=self._time_label, bg=BG2, fg=FG,
                 font=("Consolas", 10), width=14).pack(side=tk.RIGHT, padx=(0, 8))

        # Progress slider (fills remaining space)
        self._progress_var = tk.DoubleVar(value=0)
        self._slider = ttk.Scale(
            bar, from_=0, to=1000, orient=tk.HORIZONTAL,
            variable=self._progress_var, command=self._on_slider,
        )
        self._slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 16))

    # ── DB / Session loading ──────────────────────────────────────────────────

    def _on_db_change(self):
        key = self._db_var.get()
        self._db_path = DEFAULT_DBS.get(key, key)
        self._populate_sessions()

    def _browse_db(self):
        p = filedialog.askopenfilename(
            title="Select SQLite database",
            filetypes=[("SQLite databases", "*.sqlite *.db"), ("All files", "*.*")],
        )
        if p:
            self._db_path = p
            self._db_var.set(p)
            self._populate_sessions()

    def _populate_sessions(self):
        path = self._db_path
        if not Path(path).exists():
            self._status_var.set(f"Not found: {path}")
            return
        try:
            conn = sqlite3.connect(path)
            rows = conn.execute(
                "SELECT session_id, started_utc, notes FROM sessions ORDER BY started_utc DESC"
            ).fetchall()
            conn.close()
        except Exception as exc:
            self._status_var.set(f"DB error: {exc}")
            return

        self._sess_map = {}
        labels = []
        for sid, ts, notes in rows:
            label = f"{ts[:19]}  —  {notes or '(no notes)'}"
            self._sess_map[label] = sid
            labels.append(label)

        self._sess_box["values"] = labels
        if labels:
            self._sess_box.set(labels[0])
            self._session_id = self._sess_map[labels[0]]
            self._status_var.set(f"{len(labels)} session(s) found — click Load")
        else:
            self._status_var.set("No sessions found in this database")

    def _on_session_select(self):
        label = self._sess_var.get()
        self._session_id = self._sess_map.get(label, "")

    def _load_session(self):
        if not self._session_id:
            messagebox.showwarning("No session", "Select a session first.")
            return
        self._stop_playback()
        try:
            conn = sqlite3.connect(self._db_path)
            df = pd.read_sql_query(
                "SELECT * FROM telemetry WHERE session_id=? ORDER BY id ASC",
                conn, params=(self._session_id,),
            )
            conn.close()
        except Exception as exc:
            messagebox.showerror("Load error", str(exc))
            return

        if df.empty:
            messagebox.showinfo("Empty", "No telemetry rows for this session.")
            return

        df["ts_utc"] = pd.to_datetime(df["ts_utc"])
        # Replace -1 error sentinels with NaN
        num_cols = df.select_dtypes(include="number").columns
        df[num_cols] = df[num_cols].replace(-1.0, float("nan"))

        self._df = df
        self._play_idx = 0
        self._slider.configure(to=max(1, len(df) - 1))

        dur = (df["ts_utc"].iloc[-1] - df["ts_utc"].iloc[0]).total_seconds()
        m, s = divmod(int(dur), 60)
        self._status_var.set(f"Loaded {len(df):,} rows  ·  {m}m {s:02d}s")

        self._draw_charts()
        self._update_display(0)

    # ── Chart drawing (called once per session load) ───────────────────────────

    def _draw_charts(self):
        df = self._df
        if df is None:
            return
        t = df["ts_utc"]
        self._cursor_lines = []

        for ax, (title, col, color, extras), vcol, tool in zip(
            self._axes, CHARTS, CHART_VALID, CHART_TOOL
        ):
            ax.clear()
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=7, length=3)
            ax.set_ylabel(title, color=FG_MUTED, fontsize=7, labelpad=2)
            ax.grid(True, color=C_GRID, linewidth=0.5)
            for spine in ax.spines.values():
                spine.set_edgecolor(C_GRID)

            # Main line
            if col in df.columns:
                ax.plot(t, df[col], color=color, linewidth=1.2, alpha=0.9)

            # Extra lines (e.g. accel x/y/z on the g-force chart)
            for ecol, ecolor in extras:
                if ecol in df.columns:
                    ax.plot(t, df[ecol], color=ecolor, linewidth=0.8, alpha=0.55)

            # Valid window shading (green)
            if vcol and vcol in df.columns:
                self._shade_spans(ax, df, vcol, 1, "#22c55e", 0.15)

            # Misfire shading (red)
            if tool:
                col_on = f"mega_{tool}_on"
                if col_on in df.columns and vcol and vcol in df.columns:
                    self._shade_misfires(ax, df, col_on, vcol)

            # Cursor line (starts at first data point)
            cur = ax.axvline(x=t.iloc[0], color=C_CURSOR,
                             linewidth=1.5, alpha=0.70, linestyle="--", zorder=10)
            self._cursor_lines.append(cur)

        self._canvas.draw()

    def _shade_spans(self, ax, df, col, val, color, alpha):
        """Shade contiguous regions where df[col] == val."""
        in_span, t0, prev_t = False, None, None
        for _, row in df.iterrows():
            is_val = row.get(col, 0) == val
            if is_val and not in_span:
                in_span, t0 = True, row["ts_utc"]
            elif not is_val and in_span:
                ax.axvspan(t0, prev_t, color=color, alpha=alpha, zorder=0)
                in_span = False
            prev_t = row["ts_utc"]
        if in_span and t0 is not None:
            ax.axvspan(t0, df["ts_utc"].iloc[-1], color=color, alpha=alpha, zorder=0)

    def _shade_misfires(self, ax, df, col_on, col_valid):
        """Shade runs of the tool being ON where no valid sample was ever taken."""
        in_run, t0, had_v = False, None, False
        prev_t = None
        for _, row in df.iterrows():
            on    = row.get(col_on,    0) == 1
            valid = row.get(col_valid, 0) == 1
            if on and not in_run:
                in_run, t0, had_v = True, row["ts_utc"], False
            if on and in_run and valid:
                had_v = True
            if not on and in_run:
                if not had_v:
                    ax.axvspan(t0, row["ts_utc"], color=BAD, alpha=0.10, zorder=0)
                in_run = False
            prev_t = row["ts_utc"]
        if in_run and not had_v and t0 is not None:
            ax.axvspan(t0, df["ts_utc"].iloc[-1], color=BAD, alpha=0.10, zorder=0)

    # ── Display update (called every playback tick) ───────────────────────────

    def _update_display(self, idx: int):
        df = self._df
        if df is None:
            return
        idx = max(0, min(idx, len(df) - 1))
        row = df.iloc[idx]
        t0  = df["ts_utc"].iloc[0]
        elapsed_s = (row["ts_utc"] - t0).total_seconds()
        total_s   = (df["ts_utc"].iloc[-1] - t0).total_seconds()

        def _f(key, dec=2):
            v = row.get(key, float("nan"))
            try:
                f = float(v)
                return "—" if (f != f) else f"{f:.{dec}f}"
            except Exception:
                return str(v) if v and str(v) != "nan" else "—"

        def _fmt_t(sec):
            m, s = divmod(int(max(0, sec)), 60)
            return f"{m}:{s:02d}"

        self._mvar["_time"].set(str(row["ts_utc"])[:19])
        self._mvar["_elapsed"].set(_fmt_t(elapsed_s))
        self._mvar["batt_percentage"].set(_f("batt_percentage", 1))
        self._mvar["power_voltage_v"].set(_f("power_voltage_v", 2))
        self._mvar["temp_c"].set(_f("temp_c", 2))
        self._mvar["co2_ppm"].set(_f("co2_ppm", 0))
        self._mvar["water_ph"].set(_f("water_ph", 2))
        self._mvar["soil_moisture_pct"].set(_f("soil_moisture_pct", 1))
        self._mvar["imu_g_force"].set(_f("imu_g_force", 3))
        self._mvar["imu_accel_x"].set(_f("imu_accel_x", 3))
        self._mvar["imu_accel_y"].set(_f("imu_accel_y", 3))
        self._mvar["imu_accel_z"].set(_f("imu_accel_z", 3))
        self._mvar["mega_movement"].set(str(row.get("mega_movement", "—")))

        rc = row.get("mega_ibus_pulse", float("nan"))
        try:
            self._mvar["_rc"].set("OK" if int(rc) == 1 else "LOST")
        except Exception:
            self._mvar["_rc"].set("—")

        # Tool LEDs
        for tool, col in [("AIR","mega_air_on"),("WATER","mega_water_on"),("SOIL","mega_soil_on")]:
            try:
                on = int(row.get(col, 0)) == 1
            except Exception:
                on = False
            self._tool_var[tool].set("ON" if on else "OFF")
            self._tool_lbl[tool].configure(fg=BLUE if on else FG_MUTED)

        # Time label and slider
        self._time_label.set(f"{_fmt_t(elapsed_s)} / {_fmt_t(total_s)}")
        self._progress_var.set(idx)

        # Move cursor lines across all charts
        cur_t = row["ts_utc"]
        for line in self._cursor_lines:
            line.set_xdata([cur_t, cur_t])
        self._canvas.draw_idle()

    # ── Playback controls ─────────────────────────────────────────────────────

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

        # Calculate real-time delay between this sample and the next
        df = self._df
        if self._play_idx + 1 < len(df):
            dt_ms = (
                df["ts_utc"].iloc[self._play_idx + 1]
                - df["ts_utc"].iloc[self._play_idx]
            ).total_seconds() * 1000
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
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG3, background=BG3,
                        foreground=FG, selectbackground=BG3)
        style.configure("TScale", background=BG2, troughcolor=BG3)
    except Exception:
        pass
    TkBoard(root)
    root.mainloop()


if __name__ == "__main__":
    main()