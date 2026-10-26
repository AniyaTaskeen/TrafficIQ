"""SQLite storage: the traffic history the system learns from, and the latest run."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "traffic.db"


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS history (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   lane TEXT NOT NULL,
                   hour INTEGER NOT NULL,
                   count REAL NOT NULL,
                   source TEXT NOT NULL,          -- 'video' (real) or 'sample'
                   created_at TEXT NOT NULL)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   hour INTEGER NOT NULL,
                   created_at TEXT NOT NULL,
                   result_json TEXT NOT NULL)"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS detections (id TEXT PRIMARY KEY, lane TEXT NOT NULL, created_at TEXT NOT NULL, result_json TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, message TEXT NOT NULL, kind TEXT NOT NULL)")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_history(rows, source):
    """rows: list of (lane, hour, count)"""
    stamp = now()
    with connect() as conn:
        conn.executemany(
            "INSERT INTO history (lane, hour, count, source, created_at) VALUES (?,?,?,?,?)",
            [(lane, hour, count, source, stamp) for lane, hour, count in rows],
        )


def clear_sample():
    with connect() as conn:
        conn.execute("DELETE FROM history WHERE source = 'sample'")


def clear_all():
    with connect() as conn:
        conn.execute("DELETE FROM history")
        conn.execute("DELETE FROM runs")


def hourly_averages():
    """Return {lane: {hour: average_count}} using all history."""
    out = {}
    with connect() as conn:
        for r in conn.execute(
            "SELECT lane, hour, AVG(count) AS avg FROM history GROUP BY lane, hour"
        ):
            out.setdefault(r["lane"], {})[r["hour"]] = r["avg"]
    return out


def history_counts():
    with connect() as conn:
        real = conn.execute("SELECT COUNT(*) FROM history WHERE source='video'").fetchone()[0]
        sample = conn.execute("SELECT COUNT(*) FROM history WHERE source='sample'").fetchone()[0]
    return {"real": real, "sample": sample}


def save_run(hour, result):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (hour, created_at, result_json) VALUES (?,?,?)",
            (hour, now(), json.dumps(result)),
        )
        return cursor.lastrowid


def latest_run():
    with connect() as conn:
        r = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    data = json.loads(r["result_json"])
    data["run_id"] = r["id"]
    data["created_at"] = r["created_at"]
    return data


def run_count():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def image_runs():
    """Only genuine image sessions; legacy videos and sample records stay separate."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
    results = []
    for row in rows:
        data = json.loads(row["result_json"])
        if data.get("source") == "image":
            data.update(run_id=row["id"], created_at=row["created_at"])
            results.append(data)
    return results


def get_settings():
    from config import CONFIDENCE, MIN_GREEN, MAX_GREEN
    defaults = dict(confidence=CONFIDENCE, min_green=MIN_GREEN, max_green=MAX_GREEN,
                    medium_threshold=10, high_threshold=20)
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE id=1").fetchone()
    if row:
        defaults.update(json.loads(row[0]))
    return defaults


def save_settings(value):
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (id,value) VALUES (1,?)", (json.dumps(value),))


def save_detection(identifier, lane, result):
    with connect() as conn:
        conn.execute("INSERT INTO detections VALUES (?,?,?,?)", (identifier, lane, now(), json.dumps(result)))


def get_detection(identifier):
    with connect() as conn:
        row = conn.execute("SELECT result_json FROM detections WHERE id=?", (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def latest_detections():
    with connect() as conn:
        rows = conn.execute("SELECT result_json FROM detections WHERE rowid IN (SELECT MAX(rowid) FROM detections GROUP BY lane)").fetchall()
    results = [json.loads(row[0]) for row in rows]
    return {result["lane"]: result for result in results}


def add_activity(message, kind="info"):
    with connect() as conn:
        conn.execute("INSERT INTO activity (created_at,message,kind) VALUES (?,?,?)", (now(), message, kind))


def recent_activity():
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 30")]


def update_run(identifier, result):
    with connect() as conn:
        conn.execute("UPDATE runs SET result_json=? WHERE id=?", (json.dumps(result), identifier))
