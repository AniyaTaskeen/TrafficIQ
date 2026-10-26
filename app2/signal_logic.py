"""Turns vehicle counts into green times for the four lanes.

Steps
  1. effective load = 0.6 * live count + 0.4 * learned (predicted) count
  2. if this hour is a learned peak for the lane, multiply its load by PEAK_BOOST
  3. share each lane's load / total load
  4. green = MIN_GREEN + share * (GREEN_BUDGET - 4 * MIN_GREEN), kept between MIN and MAX
"""
from config import (ALL_RED, GREEN_BUDGET, LANES, LIVE_WEIGHT, MAX_GREEN,
                    MIN_GREEN, PEAK_BOOST, YELLOW)


def build_plan(live, predicted, peaks):
    """
    live:      {lane: vehicle count from the video}
    predicted: {lane: learned count for this hour, or None}
    peaks:     {lane: True if this hour is a learned peak for the lane}
    Returns a list of dicts, one per lane, in signal order.
    """
    effective = {}
    for lane in LANES:
        p = predicted.get(lane)
        load = live[lane] if p is None else LIVE_WEIGHT * live[lane] + (1 - LIVE_WEIGHT) * p
        if peaks.get(lane):
            load *= PEAK_BOOST
        effective[lane] = load

    total = sum(effective.values())
    distributable = GREEN_BUDGET - len(LANES) * MIN_GREEN

    plan = []
    for lane in LANES:
        share = effective[lane] / total if total > 0 else 1 / len(LANES)
        green = MIN_GREEN + share * distributable
        green = int(round(min(MAX_GREEN, max(MIN_GREEN, green))))
        plan.append({
            "lane": lane,
            "live": round(live[lane], 1),
            "predicted": None if predicted.get(lane) is None else round(predicted[lane], 1),
            "effective": round(effective[lane], 1),
            "share": round(share * 100, 1),
            "peak": bool(peaks.get(lane)),
            "green": green,
        })
    return plan


def cycle_seconds(plan):
    return sum(p["green"] + YELLOW + ALL_RED for p in plan)


def image_plan(detections, settings, manual=None):
    """Bounded proportional allocation from actual still-image counts only.

    Redistribute capped shares; integer rounding retains the green budget.
    Fixed rotation and a positive minimum guarantee each lane a turn.
    """
    counts = {lane: detections[lane]["count"] for lane in LANES}
    lo, hi = settings["min_green"], settings["max_green"]
    budget = min(max(GREEN_BUDGET, lo * len(LANES)), hi * len(LANES))
    allocated = dict.fromkeys(LANES, float(lo))
    remaining = budget - sum(allocated.values())
    available = list(LANES)
    while remaining > 0.00001 and available:
        weight = sum(counts[l] for l in available)
        extra = {l: remaining * (counts[l] / weight if weight else 1 / len(available)) for l in available}
        used = 0
        for lane in available:
            portion = min(hi - allocated[lane], extra[lane])
            allocated[lane] += portion
            used += portion
        remaining -= used
        available = [l for l in available if allocated[l] < hi - 0.00001]
    integers = {l: int(allocated[l]) for l in LANES}
    for lane in sorted(LANES, key=lambda l: allocated[l] - integers[l], reverse=True):
        if sum(integers.values()) < budget and integers[lane] < hi:
            integers[lane] += 1
    total = sum(counts.values())
    plan = []
    for lane in LANES:
        count = counts[lane]
        green = manual[lane] if manual is not None else integers[lane]
        density = "High" if count >= settings["high_threshold"] else "Medium" if count >= settings["medium_threshold"] else "Low"
        explanation = (f"Manual test timing: {green}s; detected count remains {count}." if manual is not None else
                       f"{count} detected vehicles, {count / total * 100 if total else 25:.1f}% of demand. "
                       f"Allocated {green}s within the {lo}–{hi}s limits; every lane gets a turn.")
        plan.append(dict(lane=lane, live=count, green=green, density=density,
                         share=round(count / total * 100, 1) if total else 25,
                         categories=detections[lane]["categories"], explanation=explanation))
    return plan
