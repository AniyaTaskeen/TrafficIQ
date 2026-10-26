"""Sample traffic history so the pattern-learning demo works without weeks of real data.

The numbers are SIMULATED (and labelled as sample data in the UI): a normal city
rhythm, plus a school-run surge on the West lane around 9 AM and 4 PM.
"""
import random

import database
from config import HOURS, LANES, SCHOOL_LANE

BASE = {"North": 14, "East": 11, "South": 13, "West": 9}   # vehicles per frame at a normal hour

# General city rhythm (multiplier of BASE) for each hour
RHYTHM = {6: 0.5, 7: 0.8, 8: 1.1, 9: 1.1, 10: 0.9, 11: 0.9, 12: 1.0, 13: 1.0,
          14: 0.9, 15: 1.0, 16: 1.1, 17: 1.2, 18: 1.1, 19: 0.8, 20: 0.6, 21: 0.4}

# Extra vehicles on the school lane around school start / finish
SCHOOL_BUMP = {8: 5, 9: 16, 15: 5, 16: 15}

DAYS = 5   # pretend we recorded 5 days


def generate(seed=42):
    rng = random.Random(seed)
    rows = []
    for _day in range(DAYS):
        for hour in HOURS:
            for lane in LANES:
                value = BASE[lane] * RHYTHM[hour]
                if lane == SCHOOL_LANE:
                    value += SCHOOL_BUMP.get(hour, 0)
                value = max(0.0, rng.gauss(value, value * 0.10))
                rows.append((lane, hour, round(value, 1)))
    return rows


def load():
    """Replace any old sample data with a fresh set."""
    database.clear_sample()
    database.add_history(generate(), source="sample")
