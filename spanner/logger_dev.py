import os
import json
import time

LOG_PATH = os.path.join("data", "dev_log.jsonl")

def ensure_data_dir():
    os.makedirs("data", exist_ok=True)

def log_snapshot(snapshot: dict):
    """
    Always logs. One JSON per line.
    """
    ensure_data_dir()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

def log_event(msg: str):
    """
    Optional: write an event line
    """
    ensure_data_dir()
    event = {"ts": time.time(), "event": msg}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
