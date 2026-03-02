import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "example_rover_logs.sqlite" # I am termporarily routing everything to example for testing should be changed


def print_table(conn, query, title, limit=20):
    cur = conn.cursor()
    cur.execute(query, (limit,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]

    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

    if not rows:
        print("(no rows)")
        return

    widths = [len(c) for c in cols]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(str(v)))

    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    print(header)
    print("-" * len(header))

    for r in rows:
        line = " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r))
        print(line)


def main():
    print("Looking for DB at:", DB_PATH)
    if not DB_PATH.exists():
        print("DB not found. Run main_sim.py once to create it.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        print_table(
            conn,
            """
            SELECT id, ts_utc, level, source, message
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST EVENTS",
            limit=25,
        )

        # TEMPERATURE
        print_table(
            conn,
            """
            SELECT id, ts_utc, temp_c, temp_quality
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST TEMPERATURE",
            limit=10,
        )

        # IMU
        print_table(
            conn,
            """
            SELECT id, ts_utc,
                   imu_roll_deg,
                   imu_pitch_deg,
                   imu_yaw_deg,
                   imu_g_force,
                   imu_quality
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST IMU",
            limit=10,
        )

        # GPS
        print_table(
            conn,
            """
            SELECT id, ts_utc,
                   gps_lat,
                   gps_lon,
                   gps_speed_mps,
                   gps_sats,
                   gps_fix,
                   gps_quality
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST GPS",
            limit=10,
        )

        # AIR (CO2)
        print_table(
            conn,
            """
            SELECT id, ts_utc,
                   co2_ppm,
                   air_quality,
                   air_valid
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST AIR (CO2)",
            limit=10,
        )
        
        # SOIL
        print_table(
            conn,
            """
            SELECT id, ts_utc,
                   soil_moisture_pct,
                   soil_voltage_v,
                   soil_valid
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST SOIL",
            limit=10,
        )
        
        # WATER (pH)
        print_table(
            conn,
            """
            SELECT id, ts_utc,
                   water_ph,
                   water_valid
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            "LATEST WATER (pH)",
            limit=10,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
