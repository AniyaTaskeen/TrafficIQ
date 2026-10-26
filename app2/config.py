"""All the settings for the project in one place (easy to explain and tweak)."""

# ---- Lanes ----------------------------------------------------------------
LANES = ["North", "East", "South", "West"]   # signal cycle order
SCHOOL_LANE = "West"                         # the lane near the school

# ---- Signal timing (seconds) ----------------------------------------------
MIN_GREEN = 10          # every lane gets at least this much green
MAX_GREEN = 60          # no lane gets more than this
YELLOW = 3
ALL_RED = 1             # short gap where every light is red (safety)
GREEN_BUDGET = 120      # total green time shared between the 4 lanes per cycle

# ---- Pattern learning -------------------------------------------------------
LIVE_WEIGHT = 0.6       # effective load = 0.6 * live count + 0.4 * learned pattern
PEAK_RATIO = 1.5        # hour is a "peak" if its average >= 1.5 x lane's daily average
PEAK_BOOST = 1.3        # extra weight given to a lane during its learned peak hour
MIN_HOURS_FOR_PEAKS = 4 # need at least this many hours of history to call a peak

# Hours offered in the dropdown on the Upload page (24h clock)
HOURS = list(range(6, 22))   # 6 AM ... 9 PM

# ---- Detection --------------------------------------------------------------
MODEL_PATH = "yolov8n.pt"    # put your own trained weights here if you have them
CONFIDENCE = 0.35
SAMPLE_FPS = 2               # analyse 2 frames per second of video
MAX_SECONDS = 60             # only analyse the first 60 s of each video (keeps it quick)
VEHICLE_CLASSES = [2, 3, 5, 7]   # COCO ids: car, motorcycle, bus, truck


def hour_label(h):
    """9 -> '9 AM', 16 -> '4 PM'"""
    suffix = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12} {suffix}"
