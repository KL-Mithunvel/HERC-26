
from logging.sqlite_db import SQLiteLogger

if __name__ == "__main__":
    logger = SQLiteLogger("data/rover_logs.sqlite")
    logger.start(notes="dev run")

    logger.event("INFO", "main", "DB created and ready", None)

    # Example inserts
    logger.log_tmp102(30.5, "OK")
    logger.log_bno055(0.0, 0.0, 0.0, 3, 3, 3, 3, "OK")
    logger.log_gps(12.9716, 77.5946, 0.0, 10, 0.9, 1, "OK")
    logger.flush()
    logger.close()
