"""One shared, server-timed intersection simulation (not a hardware controller)."""
import math
import threading
import time

from config import LANES, YELLOW, ALL_RED


class SignalController:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.plan = []
        self.run_id = None
        self.revision = None
        self.elapsed = 0.0
        self.anchor = clock()
        self.state = "stopped"
        self.speed = 1

    def load(self, result):
        with self.lock:
            self.plan = result.get("plan", [])
            self.run_id = result.get("run_id")
            self.revision = result.get("revision")
            self.elapsed = 0
            self.anchor = self.clock()
            self.state = "stopped"

    def _elapsed(self):
        return self.elapsed + ((self.clock() - self.anchor) * self.speed if self.state == "running" else 0)

    def action(self, action, speed=None):
        with self.lock:
            if action not in {"start", "pause", "resume", "reset", "speed"}:
                raise ValueError("Unknown controller action.")
            if not self.plan:
                raise ValueError("Analyze all four lane images first.")
            elapsed = self._elapsed()
            if action == "start":
                if self.state != "stopped":
                    raise ValueError("Use Pause or Reset on an active simulation.")
                self.elapsed = 0
                self.state = "running"
            elif action == "resume":
                if self.state != "paused":
                    raise ValueError("Pause the simulation before resuming.")
                self.state = "running"
            elif action == "pause":
                if self.state != "running":
                    raise ValueError("The simulation is not running.")
                self.elapsed = elapsed
                self.state = "paused"
            elif action == "reset":
                self.state = "stopped"
                self.elapsed = 0
            elif action == "speed":
                if type(speed) is not int or speed not in (1, 5, 10):
                    raise ValueError("Speed must be 1, 5, or 10.")
                self.elapsed = elapsed
                self.speed = speed
            self.anchor = self.clock()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            phases = [(None, "red", ALL_RED)]
            for p in self.plan:
                phases.extend([(p["lane"], "green", p["green"]), (p["lane"], "yellow", YELLOW), (None, "red", ALL_RED)])
            cycle = sum(p[2] for p in phases) - ALL_RED if self.plan else 0
            elapsed = self._elapsed()
            lane, phase, remaining, next_lane = None, "red", 0, LANES[0]
            if self.plan and self.state != "stopped":
                # Initial all-red lead-in, then repeat the normal cycle.
                t = elapsed if elapsed < ALL_RED else ALL_RED + (elapsed - ALL_RED) % cycle
                offset = 0
                for i, (direction, color, seconds) in enumerate(phases):
                    if t < offset + seconds:
                        lane, phase, remaining = direction, color, math.ceil(offset + seconds - t)
                        next_lane = next((v[0] for v in phases[i + 1:] if v[1] == "green"), LANES[0])
                        break
                    offset += seconds
            return dict(state=self.state, active_lane=lane, phase=phase, remaining=remaining,
                        next_lane=next_lane, speed=self.speed, elapsed=round(elapsed, 3),
                        cycle=cycle, run_id=self.run_id, revision=self.revision,
                        signals={l: phase if l == lane else "red" for l in LANES})
