from datetime import datetime, timedelta
from pathlib import Path
import os
import sqlite3
import threading
from contextlib import contextmanager

import requests
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("CROSSSAFE_DB", BASE_DIR / "events.db"))

# Match the ESP32-CAM Arduino firmware:
# GET http://ESP32_IP:82/light?state=on|off
# GET http://ESP32_IP:82/status
ESP32_BASE_URL = os.getenv(
    "ESP32_BASE_URL", "http://172.20.10.3:82").rstrip("/")
REQUEST_TIMEOUT = 2.0

app = Flask(__name__, template_folder="templates")

state_lock = threading.Lock()
system_health = {
    "camera_connected": False,
    "last_camera_ping": None,
    "controller_connected": False,
    "last_controller_ping": None,
    "light_command_status": "UNKNOWN",
    "last_light_command_at": None,
    "last_light_command_error": None,
    "simulated_light_failure": False,
}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def init_db():
    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS crossings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'pedestrian',
                pedestrian_detected INTEGER NOT NULL DEFAULT 1,
                confidence REAL NOT NULL DEFAULT 0,
                track_id INTEGER,
                source TEXT NOT NULL DEFAULT 'phone-camera'
            )
            """
        )
        connection.commit()


def command_light(state):
    """Command integrated ESP32-CAM via GET /light?state=on|off."""
    state = str(state).upper()
    if state not in ("ON", "OFF"):
        return False, "state must be ON or OFF"
    try:
        response = requests.get(
            f"{ESP32_BASE_URL}/light", params={"state": state.lower()}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = {"message": response.text.strip() or f"LED {state}"}
        with state_lock:
            system_health["light_command_status"] = state
            system_health["last_light_command_at"] = now_iso()
            system_health["last_light_command_error"] = None
            system_health["controller_connected"] = True
            system_health["last_controller_ping"] = now_iso()
        return True, {"message": result, "commanded_state": state}
    except requests.RequestException as exc:
        with state_lock:
            system_health["last_light_command_error"] = str(exc)
            system_health["controller_connected"] = False
        return False, str(exc)


def get_controller_status():
    """Read controller /status without changing the LED state."""
    try:
        response = requests.get(
            f"{ESP32_BASE_URL}/status", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("light_on"), bool):
            raise ValueError(
                "ESP32 /status must return JSON with boolean 'light_on'")
        with state_lock:
            system_health["controller_connected"] = True
            system_health["last_controller_ping"] = now_iso()
            system_health["light_command_status"] = "ON" if data["light_on"] else "OFF"
            system_health["last_light_command_error"] = None
        return True, data
    except (requests.RequestException, ValueError) as exc:
        with state_lock:
            system_health["controller_connected"] = False
            system_health["last_light_command_error"] = str(exc)
        return False, {"error": str(exc)}


def get_recent_events(limit=20):
    limit = max(1, min(int(limit), 200))
    with connect_db() as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, track_id, confidence, pedestrian_detected, source
            FROM crossings ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "track_id": row["track_id"] if row["track_id"] is not None else row["id"],
            "confidence": row["confidence"],
            "pedestrian_detected": bool(row["pedestrian_detected"]),
            "source": row["source"],
        }
        for row in rows
    ]


def get_summary():
    now = datetime.now().astimezone()
    start = now - timedelta(minutes=9)

    with connect_db() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM crossings"
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT timestamp FROM crossings WHERE timestamp >= ?",
            (start.isoformat(timespec="seconds"),),
        ).fetchall()

    counts = {}
    for i in range(10):
        bucket_time = now.replace(
            second=0, microsecond=0) - timedelta(minutes=9 - i)
        counts[bucket_time.strftime("%H:%M")] = 0

    for row in rows:
        try:
            dt = datetime.fromisoformat(row["timestamp"]).astimezone()
            label = dt.strftime("%H:%M")
            if label in counts:
                counts[label] += 1
        except (ValueError, TypeError):
            pass

    return {
        "total": total,
        "per_minute": [
            {"minute": label, "count": count}
            for label, count in counts.items()
        ],
    }


@app.route("/")
def dashboard():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def api_status():
    # Poll the ESP32 without changing the LED state.
    controller_ok, controller_data = get_controller_status()

    with state_lock:
        camera_seen = system_health["last_camera_ping"]
        camera_connected = system_health["camera_connected"] and bool(
            camera_seen
            and (
                datetime.now().astimezone()
                - datetime.fromisoformat(camera_seen).astimezone()
            ).total_seconds() <= 6
        )
        controller_seen = system_health["last_controller_ping"]
        last_command = system_health["light_command_status"]
        command_sent_at = system_health["last_light_command_at"]
        command_error = system_health["last_light_command_error"]
        sim_failure = system_health["simulated_light_failure"]

    physical_state = (
        controller_data.get("light_on") if controller_ok else None
    )

    return jsonify({
        "status": "online",
        "camera": {
            "connected": bool(camera_connected and camera_seen),
            "last_seen": camera_seen,
        },
        "controller": {
            "connected": controller_ok,
            "last_seen": controller_seen,
            "error": None if controller_ok else controller_data.get("error"),
        },
        "light": {
            "connected": controller_ok,
            "last_command": last_command,
            "sent_at": command_sent_at,
            # This is controller-reported GPIO state, not proof that the LED
            # physically emits light; no optical/current feedback is installed.
            "gpio_on": physical_state,
            "physical_state": physical_state,
            "state_confirmed_by_controller": (
                controller_ok and isinstance(physical_state, bool)
            ),
            "error": command_error,
        },
        "simulated_light_failure": sim_failure,
    })


@app.route("/api/events", methods=["GET", "POST"])
def api_events():
    if request.method == "GET":
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(get_recent_events(limit))

    data = request.get_json(silent=True) or {}
    detected = bool(data.get("pedestrian_detected", True))
    if not detected:
        return jsonify({"status": "ignored", "reason": "No pedestrian event"}), 200

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    track_id = data.get("track_id")
    try:
        track_id = int(track_id) if track_id is not None else None
    except (TypeError, ValueError):
        track_id = None

    source = str(data.get("source", "phone-camera"))[:80]
    timestamp = now_iso()

    with connect_db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO crossings
                (timestamp, event_type, pedestrian_detected, confidence, track_id, source)
            VALUES (?, 'pedestrian', 1, ?, ?, ?)
            """,
            (timestamp, confidence, track_id, source),
        )
        event_id = cursor.lastrowid
        connection.commit()

    event_entry = {
        "id": event_id,
        "timestamp": timestamp,
        "track_id": track_id if track_id is not None else event_id,
        "confidence": confidence,
        "pedestrian_detected": True,
        "source": source,
    }

    return jsonify({
        "status": "success",
        "logged_event": event_entry,
    }), 201


@app.route("/api/summary", methods=["GET"])
def api_summary():
    return jsonify(get_summary())


@app.route("/api/camera-heartbeat", methods=["POST"])
def camera_heartbeat():
    data = request.get_json(silent=True) or {}
    connected = bool(data.get("connected", True))

    with state_lock:
        system_health["camera_connected"] = connected
        if connected:
            system_health["last_camera_ping"] = now_iso()

    return jsonify({
        "status": "success",
        "camera_connected": connected,
    })


@app.route("/api/light-command", methods=["POST"])
def api_light_command():
    data = request.get_json(silent=True) or {}
    state = str(data.get("state", "")).upper()
    ok, result = command_light(state)
    return jsonify({
        "status": "success" if ok else "error",
        "result": result,
    }), 200 if ok else 502


@app.route("/api/toggle-failure", methods=["POST"])
def toggle_failure():
    # Demo-only flag; it does not alter the hardware.
    with state_lock:
        system_health["simulated_light_failure"] = (
            not system_health["simulated_light_failure"]
        )
        value = system_health["simulated_light_failure"]

    return jsonify({
        "status": "success",
        "simulated_light_failure": value,
    })


init_db()

if __name__ == "__main__":
    print(f"CrossSafe database: {DB_PATH}")
    print(f"ESP32 controller URL: {ESP32_BASE_URL}")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
