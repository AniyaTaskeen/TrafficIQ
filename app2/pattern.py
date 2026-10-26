"""Pattern learning: how busy is each lane at each hour of the day?

This is intentionally a simple statistical model (hourly averages), which is
easy to explain: the system remembers the average vehicle count per lane per
hour, spots the hours that are much busier than usual, and uses that to give
those lanes more green time.
"""
from statistics import mean

import database
from config import (HOURS, LANES, MIN_HOURS_FOR_PEAKS, PEAK_RATIO, hour_label)


def profile():
    """{lane: {hour: avg_count}} learned from history."""
    return database.hourly_averages()


def predicted_counts(hour, prof=None):
    """Expected vehicle count per lane at this hour (None if no history for it)."""
    prof = prof if prof is not None else profile()
    return {lane: prof.get(lane, {}).get(hour) for lane in LANES}


def lane_peaks(prof=None):
    """{lane: {'hours': [..], 'daily_avg': x, 'ratio': highest peak / daily avg}}"""
    prof = prof if prof is not None else profile()
    out = {}
    for lane in LANES:
        hours = prof.get(lane, {})
        if len(hours) < MIN_HOURS_FOR_PEAKS:
            out[lane] = {"hours": [], "daily_avg": None, "ratio": None}
            continue
        daily_avg = mean(hours.values())
        peak_hours = sorted(h for h, v in hours.items() if daily_avg > 0 and v >= PEAK_RATIO * daily_avg)
        ratio = max((hours[h] for h in peak_hours), default=0) / daily_avg if peak_hours else None
        out[lane] = {"hours": peak_hours, "daily_avg": daily_avg, "ratio": ratio}
    return out


def peak_flags(hour, peaks=None):
    """{lane: True/False} - is this hour a learned peak for the lane?"""
    peaks = peaks if peaks is not None else lane_peaks()
    return {lane: hour in peaks[lane]["hours"] for lane in LANES}


def insights(prof=None, peaks=None):
    """Plain-English findings for the Analysis page."""
    prof = prof if prof is not None else profile()
    peaks = peaks if peaks is not None else lane_peaks(prof)
    notes = []
    if not any(prof.values()):
        return ["No traffic history yet. Load the sample history or process some videos."]

    overall = {lane: mean(prof[lane].values()) for lane in LANES if prof.get(lane)}
    if overall:
        busiest = max(overall, key=overall.get)
        notes.append(f"{busiest} is the busiest lane overall, averaging {overall[busiest]:.1f} vehicles per frame.")

    for lane in LANES:
        p = peaks[lane]
        if p["hours"]:
            times = ", ".join(hour_label(h) for h in p["hours"])
            notes.append(
                f"{lane} lane has a learned peak at {times} "
                f"(up to {p['ratio']:.1f}x its daily average), so it gets extra green time then."
            )
    if not any(peaks[l]["hours"] for l in LANES):
        notes.append("No lane is much busier than usual at any hour yet, so no peak boost is applied.")

    hours_with_data = sorted({h for lane in prof.values() for h in lane})
    if hours_with_data:
        notes.append(f"History covers {len(hours_with_data)} hours of the day "
                     f"({hour_label(hours_with_data[0])} to {hour_label(hours_with_data[-1])}).")
    return notes
