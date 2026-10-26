"""Smart traffic signal demo - Flask backend.

Run:  python app.py   then open http://127.0.0.1:5000
"""
import threading
import time
import csv
import io
import math
import uuid
import importlib.util
import logging
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, Response
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import database
import pattern
import sample_data
from config import (ALL_RED, HOURS, LANES, SCHOOL_LANE, YELLOW, hour_label)
from signal_logic import build_plan, cycle_seconds
from signal_logic import image_plan
from controller import SignalController

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
# A quarter-second controller poll should not flood the local terminal.
class QuietPolling(logging.Filter):
    def filter(self, record):
        return "/api/controller" not in record.getMessage() and "/api/dashboard" not in record.getMessage()


logging.getLogger("werkzeug").addFilter(QuietPolling())
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3   # 2 GB for four videos
database.init_db()

# ---- background job state (one processing job at a time) -------------------
JOB = {"state": "idle", "progress": 0, "message": ""}
JOB_LOCK = threading.Lock()
IMAGE_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
controller = SignalController()
existing_images = database.image_runs()
if existing_images:
    controller.load(existing_images[-1])
_last_phase = None


def set_job(**kwargs):
    with JOB_LOCK:
        JOB.update(kwargs)


@app.context_processor
def inject_globals():
    return {
        "lanes": LANES,
        "school_lane": SCHOOL_LANE,
        "hours": [{"value": h, "label": hour_label(h)} for h in HOURS],
    }


# ---- pages ------------------------------------------------------------------
@app.route("/")
def dashboard():
    prof = pattern.profile()
    peaks = pattern.lane_peaks(prof)
    counts = database.history_counts()
    last = database.latest_run()
    peak_list = [
        {"lane": lane, "times": ", ".join(hour_label(h) for h in peaks[lane]["hours"])}
        for lane in LANES if peaks[lane]["hours"]
    ]
    return render_template(
        "dashboard.html", page="dashboard", runs=database.run_count(),
        counts=counts, last=last, peak_list=peak_list,
        last_hour=hour_label(last["hour"]) if last else None,
    )


@app.route("/upload")
def upload_page():
    return render_template("upload.html", page="upload")


@app.route("/output")
def output_page():
    return render_template("output.html", page="output")


@app.route("/analysis")
def analysis_page():
    return render_template("analysis.html", page="analysis")


@app.get("/settings")
def settings_page():
    return render_template("settings.html", page="settings")


# ---- processing -------------------------------------------------------------
def process_job(paths, hour):
    try:
        import detector   # imported here so the site still opens if YOLO isn't installed
    except ImportError:
        set_job(state="error", message="YOLO is not installed. Run: pip install -r requirements.txt")
        return

    try:
        live = {}
        for i, lane in enumerate(LANES):
            set_job(message=f"Detecting vehicles in the {lane} lane ({i + 1} of {len(LANES)})")

            def report(fraction, i=i):
                set_job(progress=int((i + fraction) / len(LANES) * 100))

            result = detector.count_vehicles(paths[lane], progress_cb=report)
            live[lane] = result["avg"]

        set_job(message="Working out signal timings")
        finish_run(live, hour)
        set_job(state="done", progress=100, message="Done")
    except Exception as exc:   # show the problem in the UI instead of failing silently
        set_job(state="error", message=f"{type(exc).__name__}: {exc}")


def finish_run(live, hour):
    """Predict from learned history, build the signal plan, then learn from this run."""
    prof = pattern.profile()                      # history BEFORE this run
    peaks = pattern.lane_peaks(prof)
    predicted = pattern.predicted_counts(hour, prof)
    flags = pattern.peak_flags(hour, peaks)
    plan = build_plan(live, predicted, flags)

    result = {
        "hour": hour,
        "hour_label": hour_label(hour),
        "plan": plan,
        "yellow": YELLOW,
        "all_red": ALL_RED,
        "cycle": cycle_seconds(plan),
        "used_pattern": any(p is not None for p in predicted.values()),
    }
    database.save_run(hour, result)
    database.add_history([(lane, hour, live[lane]) for lane in LANES], source="video")


@app.post("/api/upload")
def api_upload():
    if JOB["state"] == "processing":
        return jsonify(error="A job is already running. Please wait."), 409

    try:
        hour = int(request.form.get("hour", ""))
    except ValueError:
        return jsonify(error="Please choose the time of day."), 400
    if hour not in HOURS:
        return jsonify(error="Invalid time of day."), 400

    stamp = int(time.time())
    paths = {}
    for lane in LANES:
        f = request.files.get(lane)
        if not f or not f.filename:
            return jsonify(error=f"Please upload a video for the {lane} lane."), 400
        name = f"{stamp}_{lane}_{secure_filename(f.filename)}"
        path = UPLOAD_DIR / name
        f.save(path)
        paths[lane] = path

    set_job(state="processing", progress=0, message="Starting...")
    threading.Thread(target=process_job, args=(paths, hour), daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    with JOB_LOCK:
        return jsonify(dict(JOB))


@app.get("/api/result")
def api_result():
    return jsonify(database.latest_run() or {})


@app.get("/api/analysis")
def api_analysis():
    prof = pattern.profile()
    peaks = pattern.lane_peaks(prof)
    series = {lane: [prof.get(lane, {}).get(h) for h in HOURS] for lane in LANES}
    return jsonify(
        hours=HOURS,
        labels=[hour_label(h) for h in HOURS],
        series=series,
        peaks={lane: peaks[lane]["hours"] for lane in LANES},
        insights=pattern.insights(prof, peaks),
        counts=database.history_counts(),
        latest=database.latest_run(),
    )


# ---- sample data ------------------------------------------------------------
@app.post("/api/sample/load")
def api_sample_load():
    sample_data.load()
    return jsonify(ok=True)


@app.post("/api/sample/clear")
def api_sample_clear():
    database.clear_sample()
    return jsonify(ok=True)


@app.post("/api/reset")
def api_reset():
    with STATE_LOCK:
        database.clear_all()
        controller.load({})
    return jsonify(ok=True)


# ---- Image workflow: real detections, saved sessions and server simulation ----
def latest_image():
    runs = database.image_runs()
    return runs[-1] if runs else None


@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith("/api/"):
        message = "Upload is too large (maximum 12 MB per image)." if exc.code == 413 else exc.description
        return jsonify(error=message), exc.code
    return exc


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/health")
def health():
    ready = all(importlib.util.find_spec(m) is not None for m in ("cv2", "ultralytics"))
    return jsonify(ok=True, detector_installed=ready, model="YOLOv8n", input="Still images",
                   message="Ready for inference" if ready else "Install requirements.txt to enable detection")


@app.post("/api/detect/<lane>")
def api_detect(lane):
    request.max_content_length = 13 * 1024 * 1024
    if lane not in LANES:
        return jsonify(error="Unknown lane."), 400
    if request.content_length and request.content_length > 13 * 1024 * 1024:
        return jsonify(error="Maximum image size is 12 MB."), 413
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify(error="Choose a traffic image first."), 400
    if not IMAGE_LOCK.acquire(blocking=False):
        return jsonify(error="Another image is being analyzed. Please try again in a moment."), 409
    identifier = uuid.uuid4().hex
    original = UPLOAD_DIR / f"{identifier}_original.jpg"
    annotated = UPLOAD_DIR / f"{identifier}_annotated.jpg"
    success = False
    try:
        import detector
        # Validate actual bytes, not just the filename or browser MIME type.
        data = f.stream.read(12 * 1024 * 1024 + 1)
        if len(data) > 12 * 1024 * 1024:
            return jsonify(error="Maximum image size is 12 MB."), 413
        detector.prepare_image(io.BytesIO(data), original)
        settings = database.get_settings()
        result = detector.detect_image(original, annotated, settings["confidence"])
        result.update(id=identifier, lane=lane, original_url=f"/media/{original.name}",
                      annotated_url=f"/media/{annotated.name}", created_at=database.now())
        database.save_detection(identifier, lane, result)
        database.add_activity(f"{lane} image analyzed: {result['count']} vehicles detected.", "detection")
        success = True
        return jsonify(result)
    except ImportError:
        return jsonify(error="Detection dependencies are missing. Run .venv\\Scripts\\python -m pip install -r requirements.txt"), 503
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception("Image inference failed")
        return jsonify(error="YOLO inference failed. Check model weights, internet access for the first download, and the server log."), 503
    finally:
        if not success:
            original.unlink(missing_ok=True)
            annotated.unlink(missing_ok=True)
        IMAGE_LOCK.release()


def session_result(detections, settings, manual=None):
    plan = image_plan(detections, settings, manual)
    categories = {name: sum(d["categories"].get(name, 0) for d in detections.values())
                  for name in ("car", "motorcycle", "bus", "truck")}
    return dict(source="image", revision=uuid.uuid4().hex, mode="manual" if manual is not None else "automatic",
                detections=detections, plan=plan, settings=settings, categories=categories,
                total=sum(p["live"] for p in plan), yellow=YELLOW, all_red=ALL_RED,
                cycle=cycle_seconds(plan), used_pattern=False,
                busiest=max(plan, key=lambda p: p["live"])["lane"],
                quietest=min(plan, key=lambda p: p["live"])["lane"],
                average_green=round(sum(p["green"] for p in plan) / len(plan), 1))


@app.post("/api/analyze")
def api_analyze():
    payload = request.get_json(silent=True)
    ids = payload.get("detections") if isinstance(payload, dict) else None
    if not isinstance(ids, dict) or set(ids) != set(LANES) or not all(isinstance(v, str) for v in ids.values()):
        return jsonify(error="Analyze one image for each of the four directions first."), 400
    with STATE_LOCK:
        detections = {lane: database.get_detection(ids[lane]) for lane in LANES}
        if any(not d or d["lane"] != lane for lane, d in detections.items()):
            return jsonify(error="A lane image is missing or belongs to another direction."), 400
        latest = latest_image()
        if latest and all(latest["detections"][l]["id"] == ids[l] for l in LANES):
            return jsonify(latest)  # retry-safe: do not invent a duplicate history session
        result = session_result(detections, database.get_settings())
        hour = datetime.now().hour
        result.update(hour=hour, hour_label=hour_label(hour))
        result["run_id"] = database.save_run(hour, result)
        result["created_at"] = database.now()
        database.add_history([(lane, hour, d["count"]) for lane, d in detections.items()], "image")
        controller.load(result)
        database.add_activity(f"Session #{result['run_id']} saved: {result['total']} vehicles. Adaptive timings calculated.", "session")
        return jsonify(result)


@app.get("/api/dashboard")
def api_dashboard():
    with STATE_LOCK:
        return jsonify(latest=latest_image(), controller=controller.snapshot(),
                       settings=database.get_settings(), activity=database.recent_activity(),
                       draft=database.latest_detections())


@app.get("/api/controller")
def api_controller():
    global _last_phase
    with STATE_LOCK:
        snapshot = controller.snapshot()
        phase = (snapshot["run_id"], snapshot["active_lane"], snapshot["phase"], snapshot["state"])
        if phase != _last_phase and snapshot["state"] == "running":
            database.add_activity(f"Signal: {snapshot['active_lane'] or 'all directions'} · {snapshot['phase']}.", "signal")
        _last_phase = phase
        return jsonify(snapshot)


@app.post("/api/controller")
def api_controller_action():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Send a controller action."), 400
    try:
        with STATE_LOCK:
            result = controller.action(payload.get("action"), payload.get("speed"))
            database.add_activity(f"Simulation {payload.get('action')} · {result['speed']}× speed.", "signal")
        return jsonify(result)
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(database.get_settings())
    data = request.get_json(silent=True)
    expected = {"confidence", "min_green", "max_green", "medium_threshold", "high_threshold"}
    if not isinstance(data, dict) or set(data) != expected:
        return jsonify(error="All five settings are required."), 400
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in data.values()):
        return jsonify(error="Settings must be finite numbers."), 400
    if not 0.1 <= data["confidence"] <= 0.95:
        return jsonify(error="Confidence must be between 0.10 and 0.95."), 400
    if any(type(data[k]) is not int for k in expected - {"confidence"}):
        return jsonify(error="Durations and thresholds must be whole numbers."), 400
    if not 5 <= data["min_green"] <= data["max_green"] <= 120:
        return jsonify(error="Green limits must satisfy 5 ≤ minimum ≤ maximum ≤ 120 seconds."), 400
    if not 1 <= data["medium_threshold"] < data["high_threshold"] <= 1000:
        return jsonify(error="Density thresholds must satisfy 1 ≤ medium < high ≤ 1000."), 400
    with STATE_LOCK:
        database.save_settings(data)
        latest = latest_image()
        if latest:
            updated = session_result(latest["detections"], data)
            latest.update(updated)
            database.update_run(latest["run_id"], latest)
            controller.load(latest)
        database.add_activity("Settings updated. Timings recalculated; confidence applies to new detections.", "settings")
    return jsonify(ok=True, settings=data)


@app.post("/api/timings")
def api_timings():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("mode") not in {"automatic", "manual"}:
        return jsonify(error="Choose automatic or manual mode."), 400
    with STATE_LOCK:
        latest = latest_image()
        if not latest:
            return jsonify(error="Analyze four images first."), 400
        # Reject stale tabs instead of overwriting a newer session.
        if payload.get("run_id") != latest["run_id"]:
            return jsonify(error="A newer session exists. Refresh before applying timings."), 409
        manual = payload.get("greens") if payload["mode"] == "manual" else None
        settings = database.get_settings()
        if payload["mode"] == "manual" and (not isinstance(manual, dict) or set(manual) != set(LANES) or
                any(type(v) is not int or not settings["min_green"] <= v <= settings["max_green"] for v in manual.values())):
            return jsonify(error=f"Enter all four green times within {settings['min_green']}–{settings['max_green']} seconds."), 400
        latest.update(session_result(latest["detections"], settings, manual))
        database.update_run(latest["run_id"], latest)
        controller.load(latest)
        database.add_activity(f"{payload['mode'].title()} timings applied. Simulation reset to all red.", "settings")
        return jsonify(latest)


@app.get("/api/analytics")
def api_analytics():
    runs = database.image_runs()
    return jsonify(latest=runs[-1] if runs else None, sessions=len(runs),
                   history=[dict(run_id=r["run_id"], created_at=r["created_at"], total=r["total"],
                                 counts={p["lane"]: p["live"] for p in r["plan"]}) for r in runs],
                   activity=database.recent_activity())


@app.get("/api/export.csv")
def export_csv():
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["session", "captured_at", "lane", "vehicles", "cars", "motorcycles", "buses", "trucks", "density", "green_seconds", "mode", "confidence"])
    for run in database.image_runs():
        for p in run["plan"]:
            c = p["categories"]
            writer.writerow([run["run_id"], run["created_at"], p["lane"], p["live"],
                             c.get("car", 0), c.get("motorcycle", 0), c.get("bus", 0), c.get("truck", 0),
                             p["density"], p["green"], run["mode"], run["detections"][p["lane"]]["confidence"]])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=trafficiq-report.csv"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
