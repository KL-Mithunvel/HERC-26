import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# logger/tools/ -> logger/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "rover_logs.sqlite"

# ---------------------------------------------------------------------------
# Views available in the dropdown.
# Each entry: "Label" -> (SQL query with one ? for LIMIT, default_limit)
# All queries hit the single unified `telemetry` table except Events.
# ---------------------------------------------------------------------------
QUERIES = {
    # ---- events ----
    "Events (latest)": (
        "SELECT id, ts_utc, level, source, message, data_json "
        "FROM events ORDER BY id DESC LIMIT ?",
        200,
    ),

    # ---- full telemetry snapshot ----
    "All Telemetry (latest)": (
        "SELECT id, ts_utc, "
        "temp_c, temp_quality, "
        "imu_roll_deg, imu_pitch_deg, imu_yaw_deg, imu_g_force, "
        "imu_vel_x, imu_vel_y, imu_vel_z, imu_quality, "
        "gps_lat, gps_lon, gps_speed_mps, gps_sats, gps_fix, gps_quality, "
        "power_voltage_v, power_current_a, power_w, power_quality, "
        "co2_ppm, air_quality, air_phase, air_valid, air_samples_left, "
        "soil_raw, soil_voltage_v, soil_moisture_pct, soil_quality, soil_phase, soil_valid, soil_samples_left, "
        "water_ph, water_quality, water_phase, water_valid, water_samples_left, "
        "mega_air_on, mega_water_on, mega_soil_on, mega_ibus_pulse, mega_movement, mega_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),

    # ---- per-sensor quick views ----
    "Temperature (latest)": (
        "SELECT id, ts_utc, temp_c, temp_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "IMU (latest)": (
        "SELECT id, ts_utc, "
        "imu_roll_deg, imu_pitch_deg, imu_yaw_deg, imu_g_force, "
        "imu_vel_x, imu_vel_y, imu_vel_z, imu_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "GPS (latest)": (
        "SELECT id, ts_utc, gps_lat, gps_lon, gps_speed_mps, gps_sats, gps_fix, gps_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Power (latest)": (
        "SELECT id, ts_utc, power_voltage_v, power_current_a, power_w, power_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Air / CO2 (latest)": (
        "SELECT id, ts_utc, co2_ppm, air_quality, air_phase, air_valid, air_samples_left "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Soil Moisture (latest)": (
        "SELECT id, ts_utc, soil_raw, soil_voltage_v, soil_moisture_pct, "
        "soil_quality, soil_phase, soil_valid, soil_samples_left "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Water / pH (latest)": (
        "SELECT id, ts_utc, water_ph, water_quality, water_phase, water_valid, water_samples_left "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Mega (latest)": (
        "SELECT id, ts_utc, mega_air_on, mega_water_on, mega_soil_on, "
        "mega_ibus_pulse, mega_movement, mega_quality "
        "FROM telemetry ORDER BY id DESC LIMIT ?",
        200,
    ),

    # ---- mission-valid reads only ----
    "Valid Air Readings": (
        "SELECT id, ts_utc, co2_ppm, air_quality, air_phase, air_samples_left "
        "FROM telemetry WHERE air_valid = 1 ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Valid Soil Readings": (
        "SELECT id, ts_utc, soil_moisture_pct, soil_raw, soil_voltage_v, "
        "soil_quality, soil_phase, soil_samples_left "
        "FROM telemetry WHERE soil_valid = 1 ORDER BY id DESC LIMIT ?",
        200,
    ),
    "Valid Water Readings": (
        "SELECT id, ts_utc, water_ph, water_quality, water_phase, water_samples_left "
        "FROM telemetry WHERE water_valid = 1 ORDER BY id DESC LIMIT ?",
        200,
    ),

    # ---- session list ----
    "Sessions": (
        "SELECT session_id, started_utc, notes FROM sessions ORDER BY started_utc DESC LIMIT ?",
        50,
    ),
}


class DBViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rover SQLite Log Viewer")
        self.geometry("1300x680")

        if not DB_PATH.exists():
            messagebox.showerror(
                "DB not found",
                f"Database file not found:\n{DB_PATH}\n\nRun main.py once to create it.",
            )
            self.destroy()
            return

        self.conn = sqlite3.connect(DB_PATH)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---- top bar ----
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="DB:").pack(side="left")
        ttk.Label(top, text=str(DB_PATH)).pack(side="left", padx=(6, 18))

        ttk.Label(top, text="View:").pack(side="left")
        self.view_var = tk.StringVar(value=list(QUERIES.keys())[0])
        view_combo = ttk.Combobox(
            top,
            textvariable=self.view_var,
            values=list(QUERIES.keys()),
            state="readonly",
            width=32,
        )
        view_combo.pack(side="left", padx=6)

        ttk.Label(top, text="Limit:").pack(side="left")
        self.limit_var = tk.IntVar(value=200)
        ttk.Entry(top, textvariable=self.limit_var, width=8).pack(side="left", padx=6)

        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=8)

        # ---- table ----
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree = ttk.Treeview(table_frame, show="headings")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical",   command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)

        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right",  fill="y")
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

        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=130, anchor="w")

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
