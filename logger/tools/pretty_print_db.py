import sqlite3
from pathlib import Path

# logging/tools/ -> logging/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "rover_logs.sqlite"


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
        print("DB not found. Run main.py once to create it.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        print_table(
            conn,
            "SELECT id, ts_utc, level, source, message FROM events ORDER BY id DESC LIMIT ?",
            "LATEST EVENTS",
            limit=25,
        )
        print_table(
            conn,
            "SELECT id, ts_utc, temp_c, quality FROM telemetry_tmp102 ORDER BY id DESC LIMIT ?",
            "LATEST TMP102",
            limit=10,
        )
        print_table(
            conn,
            "SELECT id, ts_utc, roll_deg, pitch_deg, yaw_deg, quality FROM telemetry_bno055 ORDER BY id DESC LIMIT ?",
            "LATEST BNO055",
            limit=10,
        )
        print_table(
            conn,
            "SELECT id, ts_utc, lat, lon, sats, hdop, fix, quality FROM telemetry_gps ORDER BY id DESC LIMIT ?",
            "LATEST GPS",
            limit=10,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
