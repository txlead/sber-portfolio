# Meta Orion — Gaze-Controlled Reels Prototype

> Design prototype simulating gaze-driven interaction for AR glasses (Meta Orion).  
> Webcam simulates eye-tracking hardware.

## Setup

```bash
cd meta_gaze
pip install -r requirements.txt
```

## Add your Reels

Drop `.mp4` / `.mov` files into the `reels/` folder.  
They play in alphabetical order. Without files a placeholder screen is shown.

## Run

```bash
python main.py
```

## Controls

| Gesture | Action |
|---|---|
| Look at screen (centre) | ▶ Play |
| Look left or right | ⏸ Pause |
| Close eyes ≥ 0.5 s | ⏭ Next reel |
| Normal blink (< 200 ms) | Ignored |
| Gaze on ❤ for 2 s | ❤ Like |
| `D` key | Toggle debug overlay |
| `Q` / `ESC` | Quit |

## Thresholds (controller.py)

| Param | Default | Description |
|---|---|---|
| `EAR_CLOSED` | 0.20 | EAR below = eyes closed |
| `BLINK_MAX_MS` | 200 | Max duration for normal blink |
| `LONG_CLOSE_MIN_MS` | 500 | Min duration for intentional close |
| `GAZE_LEFT_THR` | 0.35 | Iris ratio below = looking left |
| `GAZE_RIGHT_THR` | 0.65 | Iris ratio above = looking right |
| `LIKE_DWELL_MS` | 2000 | Gaze-on-heart duration for like |

## Architecture

```
main.py         — main loop, webcam, input handling
tracker.py      — MediaPipe Face Mesh → EAR + gaze ratio
controller.py   — state machine: play/pause/next/like
renderer.py     — OpenCV UI drawing
reels/          — your .mp4 video files
```
