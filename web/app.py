from flask import Flask, jsonify, render_template, request
from sensor import dev_stack

app = Flask(__name__)

# Development: always serve fresh templates; tell browsers not to cache static files
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Active sensor stack — defaults to dev_stack (sim mode).
# Call register_stack(real_stack) in main.py before app.run() to switch.
_stack = dev_stack


def register_stack(stack):
    """Wire the active sensor stack into Flask routes (called by main.py / main_sim.py)."""
    global _stack
    _stack = stack

# Choose UI here:
#   "sensors"   -> sensors dashboard only
#   "obstacles" -> sensors dashboard + obstacle marker controls
#UI_MODE = "obstacles"
UI_MODE = "sensors"

LATEST = {
    "schema_version": 1,
    "ts": 0.0,
    "run_enabled": False,
    "data": {},
    "errors": {},
    "health": {},
    "validation": {},
    "status_log": [],
}

def set_latest(snapshot: dict):
    global LATEST
    if isinstance(snapshot, dict):
        snapshot.setdefault("schema_version", 1)
        LATEST = snapshot


@app.get("/")
def index():
    # one page, one template; UI mode controls whether obstacle widgets appear
    return render_template("index.html", ui_mode=UI_MODE)


@app.get("/api/snapshot")
def api_snapshot():
    return jsonify(LATEST)


@app.post("/api/run/on")
def api_run_on():
    _stack.set_run_enabled(True)
    return jsonify({"ok": True, "run_enabled": True})


@app.post("/api/run/off")
def api_run_off():
    _stack.set_run_enabled(False)
    return jsonify({"ok": True, "run_enabled": False})


@app.post("/api/event")
def api_event():
    """
    Used only when ui_mode == "obstacles".
    Payload: { "obstacle_id": int, "action": "enter"|"exit"|"bypass" }
    """
    payload = request.get_json(silent=True) or {}
    obstacle_id = payload.get("obstacle_id")
    action = payload.get("action", "")

    try:
        obstacle_id = int(obstacle_id)
    except Exception:
        return jsonify({"ok": False, "error": "invalid obstacle_id"}), 400

    if action not in ("enter", "exit", "bypass"):
        return jsonify({"ok": False, "error": "invalid action"}), 400

    msg = f"OBSTACLE {obstacle_id}: {action.upper()}"

    # show instantly in Status Updates
    try:
        _stack._log(msg)
    except Exception:
        pass

    return jsonify({"ok": True, "saved": True, "msg": msg})
