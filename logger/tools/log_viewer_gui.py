import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# logging/tools/ -> logging/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "rover_logs.sqlite"

QUERIES = {
    "Events (latest)": (
        "SELECT id, ts_utc, level, source, message FROM events ORDER BY id DESC LIMIT ?",
        200,
    ),
    "TMP102 (latest)": (
        "SELECT id, ts_utc, temp_c, quality FROM telemetry_tmp102 ORDER BY id DESC LIMIT ?",
        200,
    ),
    "BNO055 (latest)": (
        "SELECT id, ts_utc, roll_deg, pitch_deg, yaw_deg, g_force, vel_x, vel_y, vel_z, quality "
        "FROM telemetry_bno055 ORDER BY id DESC LIMIT ?",
        200,
    ),
    "GPS (latest)": (
        "SELECT id, ts_utc, lat, lon, speed_mps, sats, hdop, fix, quality FROM telemetry_gps ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Power (latest)": (
        "SELECT id, ts_utc, voltage_v, current_a, power_w, quality FROM telemetry_power ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Air / CO2 (latest)": (
        "SELECT id, ts_utc, co2_ppm, quality FROM telemetry_air ORDER BY id DESC LIMIT ?",
        200,
    ),
    "ADC / Soil (latest)": (
        "SELECT id, ts_utc, raw_moisture, v_moisture, moisture_value, quality FROM telemetry_adc ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Mega (latest)": (
        "SELECT id, ts_utc, air_on, water_on, soil_on, ibus_pulse, movement, quality FROM telemetry_mega ORDER BY id DESC LIMIT ?",
        200,
    ),
}


class DBViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rover SQLite Log Viewer")
        self.geometry("1150x650")

        if not DB_PATH.exists():
            messagebox.showerror(
                "DB not found",
                f"Database file not found:\n{DB_PATH}\n\nRun main.py once to create it.",
            )
            self.destroy()
            return

        self.conn = sqlite3.connect(DB_PATH)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="DB:").pack(side="left")
        ttk.Label(top, text=str(DB_PATH)).pack(side="left", padx=(6, 18))

        ttk.Label(top, text="View:").pack(side="left")
        self.view_var = tk.StringVar(value=list(QUERIES.keys())[0])
        view_combo = ttk.Combobox(
            top, textvariable=self.view_var, values=list(QUERIES.keys()), state="readonly", width=28
        )
        view_combo.pack(side="left", padx=6)

        ttk.Label(top, text="Limit:").pack(side="left")
        self.limit_var = tk.IntVar(value=200)
        ttk.Entry(top, textvariable=self.limit_var, width=8).pack(side="left", padx=6)

        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=8)

        # Table
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree = ttk.Treeview(table_frame, show="headings")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)

        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")

        self.refresh()

    def refresh(self):
        view = self.view_var.get()
        try:
            limit = int(self.limit_var.get())
        except Exception:
            limit = 200
            self.limit_var.set(limit)

        query, default_limit = QUERIES[view]
        if limit <= 0:
            limit = default_limit
            self.limit_var.set(limit)

        cur = self.conn.cursor()
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        # reset columns
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=140, anchor="w")

        for r in rows:
            self.tree.insert("", "end", values=r)

    def on_close(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    DBViewer().mainloop()
