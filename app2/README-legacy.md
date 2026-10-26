# Smart Traffic Signal (mini project)

Adaptive traffic signals. YOLOv8 counts vehicles in four lane videos, the system
learns how busy each lane is at each hour of the day, and green times are set
from the live counts plus the learned pattern (e.g. the school lane at 9 AM and 4 PM).

## Run it in VS Code

1. Unzip the folder, then in VS Code: **File → Open Folder** and pick `smart-traffic`.
2. Open a terminal (**Terminal → New Terminal**) and create a virtual environment:

   ```
   python -m venv venv
   ```

   Activate it:
   - Windows: `venv\Scripts\activate`
   - Mac / Linux: `source venv/bin/activate`

3. Install the packages (takes a few minutes, PyTorch is large):

   ```
   pip install -r requirements.txt
   ```

4. Start the app:

   ```
   python app.py
   ```

5. Open http://127.0.0.1:5000 in your browser.

The first detection run downloads `yolov8n.pt` (needs internet once). If you already
have it, or your own trained weights, put the file in this folder and set `MODEL_PATH`
in `config.py`.

## Demo steps

1. **Dashboard → Load sample history.** This fills the database with simulated
   traffic for 6 AM to 9 PM, with a school-run surge on the West lane at 9 AM and 4 PM.
   Open **Analysis** to show the learned pattern and the detected peak hours.
2. **Upload:** choose one video per lane and pick **9 AM** in the dropdown. Click
   *Detect and calculate* and wait for the progress bar.
3. **Signals:** the four signals run with the calculated green times (use the speed
   selector to speed up the 60 s greens). The table shows live count, learned count,
   load used, and green time per lane.
4. **Show the learning working:** upload the same four videos again but choose
   **12 PM**. The live counts are identical, but West gets less green time because noon is
   not a peak hour for it. That is the learned pattern at work.
5. Use the **Dark / Light** button in the top right to switch theme.

Sample data is simulated and is labelled as such in the app. Videos you process are
saved as real records and are added to what the system learns from.

## How it works

| Step | What happens | File |
|---|---|---|
| Detect | YOLOv8 counts cars, motorcycles, buses and trucks on ~2 frames per second (first 60 s of each video). The lane's count is the average per frame. | `detector.py` |
| Learn | Average count per lane per hour is stored in SQLite. An hour is a **peak** if its average is at least 1.5x the lane's daily average. | `pattern.py`, `database.py` |
| Decide | Load = 0.6 x live + 0.4 x learned. In a peak hour the load is multiplied by 1.3. Each lane's share of the total sets its green time. | `signal_logic.py` |
| Show | Flask serves 4 pages and a small JSON API. | `app.py`, `templates/`, `static/` |

Green time = `10 s + share x (120 s - 4 x 10 s)`, kept between 10 s and 60 s, with a
3 s yellow and 1 s all-red between lanes. Lanes run in the order North, East, South, West.

## Change the settings

Everything is in `config.py`: which lane is the school lane, minimum and maximum
green, yellow time, the 0.6 / 0.4 blend, the peak ratio and boost, video length
analysed, and the hours in the dropdown.

## Folder layout

```
app.py            Flask app, routes, processing job
config.py         all settings
detector.py       YOLOv8 vehicle counting
pattern.py        hourly pattern learning and peak detection
signal_logic.py   green-time calculation
sample_data.py    simulated history for the demo
database.py       SQLite (traffic.db is created on first run)
templates/        dashboard, upload, output (signals), analysis
static/           style.css (light and dark theme), app.js (theme + charts)
uploads/          uploaded videos are saved here
```

## Notes

- Videos are processed after upload, then the signal simulation runs from the results.
  This is more reliable for a demo than live streaming.
- Use short clips (30 to 60 s) of a fixed camera for the best counts.
- To start fresh, stop the app and delete `traffic.db`.
