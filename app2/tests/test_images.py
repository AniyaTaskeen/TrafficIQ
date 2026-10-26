"""Real YOLO integration plus controller/validation regression tests.

Real inference uses Ultralytics' public bus image; no stub detector is used here.
"""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from config import LANES
from controller import SignalController
from signal_logic import image_plan


class ControllerTests(unittest.TestCase):
    def test_safe_cycle_pause_resume_reset_and_fairness(self):
        clock = [0.0]
        c = SignalController(clock=lambda: clock[0])
        c.load(dict(run_id=1, plan=[dict(lane=l, green=10) for l in LANES]))
        self.assertTrue(all(v == "red" for v in c.snapshot()["signals"].values()))
        c.action("start")
        visited = set()
        for tick in range(0, 120):
            clock[0] = tick / 2
            s = c.snapshot()
            greens = [l for l, value in s["signals"].items() if value == "green"]
            self.assertLessEqual(len(greens), 1)
            visited.update(greens)
        self.assertEqual(visited, set(LANES))
        clock[0] = 60
        paused = c.action("pause")
        clock[0] = 100
        self.assertEqual(c.snapshot(), paused)
        c.action("resume")
        clock[0] = 102
        self.assertEqual(c.snapshot()["elapsed"], paused["elapsed"] + 2)
        c.action("speed", 5)
        clock[0] = 103
        self.assertEqual(c.snapshot()["elapsed"], paused["elapsed"] + 7)
        c.action("reset")
        self.assertTrue(all(v == "red" for v in c.snapshot()["signals"].values()))

    def test_exact_transition_boundaries(self):
        clock = [0.0]
        c = SignalController(clock=lambda: clock[0])
        c.load(dict(run_id=1, plan=[dict(lane=l, green=10) for l in LANES]))
        c.action("start")
        for t, lane, phase in [(0,None,"red"),(1,"North","green"),(11,"North","yellow"),(14,None,"red"),(15,"East","green"),(57,"North","green")]:
            clock[0] = t
            with self.subTest(t=t):
                self.assertEqual((c.snapshot()["active_lane"], c.snapshot()["phase"]), (lane,phase))

    def test_proportional_allocation_preserves_budget_and_bounds(self):
        settings = dict(min_green=10, max_green=60, medium_threshold=10, high_threshold=20)
        for counts in [[0,0,0,0],[20,5,3,1],[100,0,0,0],[3,8,12,20]]:
            with self.subTest(counts=counts):
                d = {l:dict(count=v,categories={}) for l,v in zip(LANES,counts)}
                plan = image_plan(d,settings)
                self.assertEqual(sum(p["green"] for p in plan),120)
                self.assertTrue(all(10 <= p["green"] <= 60 for p in plan))
                for a in plan:
                    for b in plan:
                        if a["live"] > b["live"]:
                            self.assertGreaterEqual(a["green"],b["green"])


class ImageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        p = patch.object(database, "DB_PATH", Path(self.temp.name)/"traffic.db")
        p.start(); self.addCleanup(p.stop)
        import app
        self.backend = app
        database.init_db()
        for name, value in [("UPLOAD_DIR",Path(self.temp.name)),("controller",SignalController())]:
            p=patch.object(app,name,value);p.start();self.addCleanup(p.stop)
        self.client=app.app.test_client()

    def test_settings_validation_and_persistence(self):
        settings=self.client.get("/api/settings").json
        for changes in [dict(confidence=2),dict(confidence=float("nan")),dict(min_green=90),dict(high_threshold=5),dict(min_green=True),dict(max_green=11.5)]:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post("/api/settings",json={**settings,**changes}).status_code,400)
        settings.update(min_green=15, max_green=55)
        self.assertEqual(self.client.post("/api/settings",json=settings).status_code,200)
        self.assertEqual(self.client.get("/api/settings").json,settings)

    def test_invalid_requests_and_empty_states(self):
        for route in ["/settings","/api/dashboard","/api/analytics"]:
            self.assertEqual(self.client.get(route).status_code,200)
        for route in ["/api/analyze","/api/settings","/api/controller","/api/timings"]:
            self.assertEqual(self.client.post(route,json=[]).status_code,400)
        self.assertEqual(self.client.post("/api/detect/Unknown").status_code,400)
        self.assertEqual(self.client.post("/api/detect/North").status_code,400)
        self.assertEqual(self.client.post("/api/controller",json={"action":"start"}).status_code,400)
        self.assertEqual(self.client.get("/api/analytics").json["sessions"],0)
        self.assertEqual(len(list(csv.reader(io.StringIO(self.client.get("/api/export.csv").text)))),1)

    def test_invalid_image_bytes(self):
        response=self.client.post("/api/detect/North",data={"image":(io.BytesIO(b"not an image"),"traffic.jpg")})
        self.assertEqual(response.status_code,400)
        self.assertEqual(list(Path(self.temp.name).glob("*.jpg")),[])

    def test_real_yolo_image_session_and_analytics(self):
        fixture=Path(__file__).parent/"fixtures"/"bus.jpg"
        if not fixture.exists():
            self.skipTest("Download the documented public bus fixture to run real inference.")
        from PIL import Image
        # A blank image is a real zero-vehicle inference control, not a fake count.
        blank=io.BytesIO();Image.new("RGB",(640,480),(60,60,60)).save(blank,"PNG")
        ids={}
        for lane in LANES:
            payload=blank.getvalue() if lane=="West" else fixture.read_bytes()
            response=self.client.post("/api/detect/"+lane,data={"image":(io.BytesIO(payload),"traffic.jpg")})
            self.assertEqual(response.status_code,200,response.json)
            d=response.json
            self.assertEqual(d["count"],sum(d["categories"].values()))
            self.assertEqual(d["count"],len(d["boxes"]))
            self.assertTrue((Path(self.temp.name)/Path(d["annotated_url"]).name).exists())
            if lane=="West": self.assertEqual(d["count"],0)
            else: self.assertGreater(d["categories"]["bus"],0)
            ids[lane]=d["id"]
        draft = self.client.get("/api/dashboard").json["draft"]
        self.assertEqual({lane:d["id"] for lane,d in draft.items()},ids)
        response=self.client.post("/api/analyze",json={"detections":ids})
        self.assertEqual(response.status_code,200,response.json)
        result=response.json
        self.assertEqual(result["total"],sum(p["live"] for p in result["plan"]))
        self.assertGreater(result["plan"][0]["green"],result["plan"][3]["green"])
        self.assertEqual(self.client.post("/api/analyze",json={"detections":ids}).json["run_id"],result["run_id"])
        self.assertEqual(self.client.get("/api/analytics").json["sessions"],1)
        self.assertEqual(len(list(csv.reader(io.StringIO(self.client.get("/api/export.csv").text)))),5)
        started=self.client.post("/api/controller",json={"action":"start"}).json
        self.assertEqual(started["state"],"running")
        changed=self.client.post("/api/timings",json=dict(run_id=result["run_id"],mode="manual",greens=dict.fromkeys(LANES,25)))
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertTrue(all(p["green"]==25 for p in changed.json["plan"]))
        self.assertEqual(self.client.get("/api/controller").json["state"],"stopped")
        self.assertEqual(self.client.get("/api/analytics").json["sessions"],1)
        self.assertEqual(changed.json["total"],result["total"])
        self.assertEqual(self.client.post("/api/timings",json=dict(run_id=999,mode="automatic")).status_code,409)
        settings=self.client.get("/api/settings").json
        self.client.post("/api/settings",json={**settings,"min_green":15})
        updated=self.client.get("/api/dashboard").json["latest"]
        self.assertEqual(updated["mode"],"automatic")
        self.assertTrue(all(p["green"]>=15 for p in updated["plan"]))
        # Wrong-lane detection IDs cannot spoof a completed intersection.
        self.assertEqual(self.client.post("/api/analyze",json={"detections":{**ids,"West":ids["North"]}}).status_code,400)


if __name__ == "__main__":
    unittest.main()
