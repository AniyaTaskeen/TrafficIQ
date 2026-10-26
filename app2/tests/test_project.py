"""Run with: python -m unittest discover -s tests -v.

Uses temporary storage; detector integration uses a stub, not real YOLO.
"""
import io
import gc
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import pattern
from config import LANES, HOURS
from signal_logic import build_plan, cycle_seconds


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(database, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        import app
        self.backend = app
        database.init_db()
        self.upload_patch = patch.object(app, "UPLOAD_DIR", Path(self.temp.name))
        self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)
        app.set_job(state="idle", progress=0, message="")
        self.client = app.app.test_client()
        # SQLite context managers commit but do not close connections. Collect
        # released objects before Windows removes the temporary database.
        self.addCleanup(gc.collect)

    def test_pages_and_static_assets(self):
        for url in ["/", "/upload", "/output", "/analysis", "/static/app.js", "/static/style.css"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_empty_apis(self):
        self.assertEqual(self.client.get("/api/result").json, {})
        self.assertEqual(self.client.get("/api/status").json["state"], "idle")
        self.assertEqual(self.client.get("/api/analysis").json["counts"], {"real": 0, "sample": 0})

    def test_sample_history_and_peak_learning(self):
        for _ in range(2):
            self.assertEqual(self.client.post("/api/sample/load").status_code, 200)
            analysis = self.client.get("/api/analysis").json
            self.assertEqual(analysis["counts"]["sample"], 5 * len(HOURS) * len(LANES))
            self.assertEqual(analysis["peaks"]["West"], [9, 16])
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_clear_sample_preserves_real_history(self):
        self.client.post("/api/sample/load")
        database.add_history([("North", 9, 12)], "video")
        self.client.post("/api/sample/clear")
        self.assertEqual(database.history_counts(), {"real": 1, "sample": 0})

    def test_signal_timings(self):
        for counts in [dict.fromkeys(LANES, 0), dict.fromkeys(LANES, 10), dict(zip(LANES, [100, 0, 0, 0]))]:
            plan = build_plan(counts, {}, {})
            self.assertEqual([p["lane"] for p in plan], LANES)
            self.assertTrue(all(10 <= p["green"] <= 60 for p in plan))
            self.assertEqual(cycle_seconds(plan), sum(p["green"] for p in plan) + 16)
        self.assertEqual([p["green"] for p in build_plan(dict.fromkeys(LANES, 0), {}, {})], [30] * 4)

    def test_peak_hour_gives_west_more_green(self):
        self.client.post("/api/sample/load")
        greens = []
        for hour in [9, 12]:
            self.backend.finish_run(dict.fromkeys(LANES, 10), hour)
            result = self.client.get("/api/result").json
            greens.append(next(p["green"] for p in result["plan"] if p["lane"] == "West"))
            self.assertTrue(result["used_pattern"])
        self.assertGreater(greens[0], greens[1])
        self.assertEqual(database.history_counts()["real"], 8)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_first_run_uses_only_live_counts(self):
        self.backend.finish_run(dict.fromkeys(LANES, 10), 9)
        result = self.client.get("/api/result").json
        self.assertFalse(result["used_pattern"])
        self.assertTrue(all(p["predicted"] is None for p in result["plan"]))

    def test_upload_validation(self):
        for data in [{}, {"hour": "bad"}, {"hour": "25"}, {"hour": "9"}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post("/api/upload", data=data).status_code, 400)
        self.backend.set_job(state="processing")
        self.assertEqual(self.client.post("/api/upload").status_code, 409)

    def test_upload_pipeline_with_stub_detector(self):
        detector = types.SimpleNamespace(count_vehicles=lambda path, progress_cb: {"avg": 8, "peak": 8, "samples": 2})
        files = {lane: (io.BytesIO(b"test video placeholder"), lane + ".mp4") for lane in LANES}
        with patch.dict("sys.modules", {"detector": detector}):
            response = self.client.post("/api/upload", data={"hour": "9", **files})
            self.assertEqual(response.status_code, 200)
            deadline = time.monotonic() + 5
            while self.backend.JOB["state"] == "processing" and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(self.backend.JOB["state"], "done")
        self.assertEqual(len(self.client.get("/api/result").json["plan"]), 4)
        self.assertEqual(database.history_counts()["real"], 4)

    def test_detector_error_reaches_job_status(self):
        def fail(*args, **kwargs):
            raise ValueError("No readable frames")
        with patch.dict("sys.modules", {"detector": types.SimpleNamespace(count_vehicles=fail)}):
            self.backend.process_job(dict.fromkeys(LANES, "invalid.mp4"), 9)
        self.assertEqual(self.client.get("/api/status").json["state"], "error")
        self.assertEqual(database.run_count(), 0)

    def test_zero_traffic_history_does_not_crash_analysis(self):
        database.add_history([(lane, hour, 0) for lane in LANES for hour in HOURS], "video")
        for url in ["/api/analysis", "/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_reset(self):
        self.client.post("/api/sample/load")
        self.backend.finish_run(dict.fromkeys(LANES, 10), 9)
        self.assertEqual(self.client.post("/api/reset").status_code, 200)
        self.assertEqual(database.run_count(), 0)
        self.assertEqual(database.history_counts(), {"real": 0, "sample": 0})


if __name__ == "__main__":
    unittest.main()
