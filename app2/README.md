# TrafficIQ — Intelligent Traffic Management System

An in-place upgrade of the original Flask / YOLOv8 traffic project. Upload or
capture one **still traffic image per direction**, inspect real vehicle detections,
calculate adaptive green times, and explore saved analysis sessions.

## Install and run (Windows PowerShell)

Python 3.10 is installed on this computer and was used for verification.

```powershell
cd D:\app2
# Only needed if .venv has not already been created:
& 'C:\Users\taman\AppData\Local\Programs\Python\Python310\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000/** in Chrome on this computer. The server must remain
running. This is a local URL, not a public deployment. Stop with Ctrl+C.
On another installation, `python -m venv .venv` works with a compatible Python.
PyTorch is a large dependency; initial installation can take several minutes.

`yolov8n.pt` is already downloaded here. On a fresh installation, the first actual
inference downloads the original model weights once. Set `MODEL_PATH` in
`config.py` to reuse a custom compatible model. Relative weights resolve against
the project directory. Vehicle class IDs currently assume the COCO class mapping.

## Try the complete workflow

1. **Overview / Image workspace:** upload a real JPEG, PNG, or WebP for each of
   North, East, South, and West. Maximum 12 MB / 24 megapixels each; minimum 32×32.
   Drag-and-drop is supported. Each upload runs real YOLO inference immediately.
2. Inspect the annotated preview, vehicle types, total count, and density badge.
   **Compare** opens the original and annotated images side by side.
3. Once four images are available, a session and adaptive signal plan are saved
   automatically. Replacing any image creates a new session using that image and
   the three unchanged directions. Pending images survive page refresh. If saving
   a plan fails, use **Calculate timings** to retry.
4. **Start**, **Pause**, **Resume**, and **Reset** control the shared server simulation.
   Try 1× / 5× / 10× speed. Open Signal control in a second tab to verify the same
   phase, active direction, and countdown. Reset stops at all red; it does not
   delete detections or history.
5. **Signal control:** switch to Manual, enter four green durations within the
   configured limits, and apply. Counts stay unchanged. Return to Automatic to
   restore demand-based timings. Applying a plan stops the simulation at all red.
6. **Analytics:** inspect all five Chart.js charts, hover for values, toggle line
   and doughnut legend entries, refresh, and export the saved session rows to CSV.
7. **Settings:** adjust detection confidence, density thresholds, and green limits.
   Saving recalculates automatic timings and stops the simulation at all red.
   Confidence changes apply to *new* inferences; replace/reanalyze images to use
   the new confidence. Existing detections retain their original threshold.
8. Test bad files, missing images, camera denial, and out-of-range manual values.
   Errors should be shown without inventing detections or overwriting a confirmed
   lane result.

The camera button uses browser `getUserMedia` on localhost and requests a still
photo. A device capture picker is offered when camera access is unavailable.
Physical camera capture depends on the device, browser permissions, and HTTPS
when not using localhost. It was not tested with a physical camera here.

## How detection connects to the dashboard

`dashboard.js` sends multipart image bytes to `POST /api/detect/<lane>`. Flask
checks size and lane, and `detector.prepare_image` validates the actual image,
normalizes orientation, and strips metadata. `detector.detect_image` reuses the
original YOLOv8n model, applies the saved confidence threshold, and filters COCO
classes 2/3/5/7 (car/motorcycle/bus/truck). The same boxes produce category counts,
box coordinates/confidence, and the annotated JPEG. No random or hardcoded
vehicle counts are used in the application.

Detection responses contain an ID and original/annotated image URLs. Flask saves
the inference output in SQLite. `/api/analyze` accepts four **saved detection IDs**,
checks that they belong to the correct directions, and calculates/saves a session.
The browser cannot submit its own vehicle counts. Duplicate submissions of the
same four images do not create extra sessions.

Inference is serialized because one model instance is shared. Concurrent uploads
receive a useful busy response. All media stays under `uploads/`; no cloud
inference service is used.

## Adaptive timing algorithm

The original bounded proportional timing formula is preserved and improved for
images in `signal_logic.image_plan`:

- Give every lane the configured minimum green.
- Share the remaining green budget in proportion to actual image counts.
- Cap lanes at the maximum and redistribute excess to the other lanes.
- Round using largest remainders so the total budget is retained.
- If all four counts are zero, share the budget equally.

The default total green budget is 120 seconds. It is clamped to a feasible budget
when the configured minimum/maximum make 120 impossible. Default limits are
10–60 seconds. A fixed North → East → South → West rotation prevents starvation.
Higher counts receive at least as much automatic green as lower counts, subject
to the same limits. Manual mode uses explicit tested durations within those limits.

`controller.py` is the shared server source of time, using a monotonic clock and
a lock. Every green is followed by **3 seconds yellow and 1 second all red**.
Starting includes an initial 1-second all-red clearance. Only one direction can
be green. Pause freezes simulation time, Resume continues it, and speed changes
preserve the elapsed phase. Browsers poll the controller every 250 ms rather than
independently calculating phases. A new/revised plan or server restart stops the
simulation at all red. The displayed cycle excludes the one-time startup clearance.

This is a still-image simulation. Counts do not represent a live feed and remain
fixed until another image is analyzed. This software does not drive physical lights.

## Storage and compatibility

Existing `traffic.db` history/runs are preserved. Additive tables store settings,
image detections, and activity. Database connections now close explicitly.
Original `pattern.py` hourly learning and `build_plan` are retained for the legacy
video backend; the zero-average peak-division crash is fixed.

The redesigned Analytics uses **only genuine saved image sessions**. Existing
simulated sample history and old video runs are excluded from its charts and CSV.
The legacy `/api/upload`, `/api/status`, `/api/result`, `/api/analysis`, and sample
endpoints remain for compatibility; the new UI uses the image APIs. Old video
instructions are preserved in `README-legacy.md`.

CSV contains one row per session and direction, with counts by type, density,
green seconds, controller mode, timestamp, and inference confidence. Manual and
settings changes update the current session's controller plan; they do not invent
additional image-analysis sessions. Images/history accumulate on disk.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

19 tests pass, covering the legacy backend and new image workflow. The image
integration test runs **actual YOLO** on `tests/fixtures/bus.jpg` and a blank
zero-vehicle image, with an isolated temporary database and upload folder. It
verifies counts, annotations, unequal allocation, saved history, CSV rows, manual
mode, settings, retry safety, and wrong-lane rejection. Controller tests exercise
exact phase boundaries, single-green exclusion, full rotation, pause/resume,
speed changes, and reset. Legacy video tests explicitly use a stub detector;
the image test does not.

Browser verification covers real image upload, annotated preview/comparison,
Start/Pause/Resume/Reset, navigation, analytics charts and refresh, and responsive
desktop/mobile layouts. Physical camera capture and accuracy on your particular
intersection/camera were not verified. Detection counts can miss occluded or very
small vehicles; the comparison view is provided so results can be inspected.

`test-results.txt` contains the latest automated run. `docs/` holds UI screenshots.

## Main files changed

| File | Responsibility |
| --- | --- |
| `app.py` | Existing Flask routes plus image APIs, validation, settings, controller, analytics, CSV |
| `detector.py` | Existing YOLO model plus validated still-image inference/annotation |
| `signal_logic.py` | Existing formula plus bounded budget redistribution for images |
| `controller.py` | New shared server simulation and safe phase transitions |
| `database.py` | Existing SQLite storage, additive tables, image sessions/drafts, explicit connection closing |
| `pattern.py` | Zero-traffic peak fix |
| `templates/*.html` | Redesigned existing pages, shared lane/simulation panels, settings |
| `static/*.js`, `static/style.css` | Fetch integration, camera, preview, controls, charts, responsive design |
| `static/vendor/chart.umd.js` | Local Chart.js 4.4.8 (MIT header retained) |
| `tests/` | Backend, real-inference, and controller regression tests |

Public test image: [Ultralytics assets bus.jpg](https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg).
Original model remains YOLOv8n. Review the upstream Ultralytics licensing terms
before distributing this project. Fonts use Google Fonts when available, with
local system fallbacks; the application and locally bundled charts work offline
after dependencies and model weights have been installed.

Run one Flask process for this local demo: controller state is intentionally
in-process. A multi-worker or public deployment would require shared controller
state, authentication, and appropriate server configuration.
