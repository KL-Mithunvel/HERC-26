from flask import Flask, jsonify, render_template
from flask import request

from sensor import dev_stack

app = Flask(__name__)

# main.py will update this reference continuously
LATEST = {"ts": 0, "run_enabled": False, "data": {}, "errors": {}, "health": {}, "status_log": []}

def set_latest(snapshot: dict):
    global LATEST
    LATEST = snapshot

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/snapshot")
def api_snapshot():
    return jsonify(LATEST)

@app.post("/api/run/on")
def api_run_on():
    dev_stack.set_run_enabled(True)
    return jsonify({"ok": True, "run_enabled": True})

@app.post("/api/run/off")
def api_run_off():
    dev_stack.set_run_enabled(False)
    return jsonify({"ok": True, "run_enabled": False})

@app.post("/api/ping")
def api_ping():
    # useful for connectivity check
    return jsonify({"ok": True})
