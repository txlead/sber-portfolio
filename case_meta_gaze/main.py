"""
Gaze-Controlled Instagram Reels — Meta Orion Prototype
=======================================================
Controls:
  Look centre        → play
  Look left / right  → pause
  Close eyes 0.5s+   → next reel
  Gaze at ❤  2s      → like
  [Q] / ESC          → quit
"""

import cv2
import numpy as np
import time
import os
import glob
import subprocess

from tracker    import EyeTracker
from controller import Controller
from renderer   import draw_frame, heart_zone_rect, WIN_W, WIN_H


# ── Audio player (ffplay, no window, loop=no) ─────────────────────────────────
class AudioPlayer:
    def __init__(self):
        self._proc = None

    def play(self, path, seek=0.0):
        self.stop()
        cmd = [
            'ffplay', '-nodisp', '-autoexit',
            '-loglevel', 'quiet',
            '-ss', str(seek),
            path
        ]
        self._proc = subprocess.Popen(cmd)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc = None

    def is_done(self):
        return self._proc is None or self._proc.poll() is not None


# ── Config ────────────────────────────────────────────────────────────────────
WEBCAM_ID     = 0
MATERIALS_DIR = os.path.join(os.path.dirname(__file__), "materials")
REELS_DIR     = os.path.join(os.path.dirname(__file__), "reels")
BG_VIDEO_PATH    = os.path.join(MATERIALS_DIR, "video_bg.MP4")
BG_VIDEO_PATH_2  = os.path.join(MATERIALS_DIR, "Light_video.MP4")
BG_SWITCH_AFTER  = 2   # switch to BG_VIDEO_PATH_2 starting from reel index 2 (3rd reel)
FPS_TARGET    = 30
NEXT_FLASH_MS = 300


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_reels(materials_dir, reels_dir):
    """Load videos: materials/ first, then reels/, sorted."""
    exts  = ["*.mp4", "*.MP4", "*.mov", "*.MOV", "*.avi"]
    paths = []
    for folder in [materials_dir, reels_dir]:
        if os.path.isdir(folder):
            for ext in exts:
                paths += glob.glob(os.path.join(folder, ext))
    paths = sorted(set(paths))
    caps  = [cv2.VideoCapture(p) for p in paths]
    if not caps:
        print("[INFO] No video files found. Showing placeholder.")
    else:
        for p in paths:
            print(f"[INFO] Loaded: {os.path.basename(p)}")
    return caps, paths


def read_next_frame(cap):
    ret, frame = cap.read()
    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = cap.read()
    return frame if ret else None


def gaze_on_heart(gaze_screen, canvas_w, canvas_h):
    if gaze_screen is None:
        return False
    cam_w, cam_h = 640, 480
    gx = int(gaze_screen[0] / cam_w * canvas_w)
    gy = int(gaze_screen[1] / cam_h * canvas_h)
    x1, y1, x2, y2 = heart_zone_rect()
    return x1 <= gx <= x2 and y1 <= gy <= y2


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cam = cv2.VideoCapture(WEBCAM_ID)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cam.set(cv2.CAP_PROP_FPS, FPS_TARGET)
    # Low-light: longer exposure + gain for screen-only illumination
    cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # 1 = manual on most drivers
    cam.set(cv2.CAP_PROP_EXPOSURE, -4)        # longer exposure for very dark room
    cam.set(cv2.CAP_PROP_GAIN, 8)             # stronger gain for screen-only light

    if not cam.isOpened():
        print("[ERROR] Cannot open webcam.")
        return

    reel_caps, reel_paths = load_reels(MATERIALS_DIR, REELS_DIR)
    reel_idx   = 0
    reel_total = max(len(reel_caps), 1)

    tracker = EyeTracker()
    ctrl    = Controller()
    audio   = AudioPlayer()

    # Background video (loops silently) — two variants, switched by reel index
    bg_cap = None
    bg_current_path = None

    def _open_bg(path):
        if path and os.path.exists(path):
            print(f"[INFO] Background video: {os.path.basename(path)}")
            return cv2.VideoCapture(path)
        return None

    def _bg_path_for_reel(idx):
        if idx >= BG_SWITCH_AFTER and os.path.exists(BG_VIDEO_PATH_2):
            return BG_VIDEO_PATH_2
        if os.path.exists(BG_VIDEO_PATH):
            return BG_VIDEO_PATH
        return None

    bg_current_path = _bg_path_for_reel(0)
    bg_cap          = _open_bg(bg_current_path)
    bg_frame_cur    = None

    next_anim_start  = 0.0
    last_vid_frame   = None
    scroll_anim_start = 0.0
    scroll_anim_dur   = 0.35   # seconds for scroll animation
    scroll_prev_frame = None   # frame before scroll (slides out upward)
    show_debug        = False   # press [D] to toggle debug overlay

    import platform
    import renderer as _rnd

    _dock_autohide_was_set = False

    # ── FULL screen size — canvas must match this EXACTLY ─────────────────────
    # OpenCV FULLSCREEN window = full display pixels.
    # If canvas is smaller → OpenCV letterboxes → white stripe.
    # Solution: canvas = full frame. Dock/menubar overlay on top — no stripe.
    scr_w, scr_h = 1512, 982  # safe fallback MacBook Pro 14"
    try:
        out = subprocess.check_output(
            ['swift', '-e',
             'import AppKit; let f=NSScreen.main!.frame;'
             ' print(Int(f.width), Int(f.height))'],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        scr_w, scr_h = [int(v) for v in out.split()]
    except Exception:
        try:
            import tkinter as tk
            _r = tk.Tk(); _r.withdraw()
            scr_w, scr_h = _r.winfo_screenwidth(), _r.winfo_screenheight()
            _r.destroy()
        except Exception:
            pass

    print(f"[INFO] Screen: {scr_w}×{scr_h}  os={platform.system()}")

    win_name = "Meta Orion — Gaze Reels"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # ── Update renderer ───────────────────────────────────────────────────────
    _rnd.WIN_W = scr_w
    _rnd.WIN_H = scr_h
    _rnd.VID_H = int(scr_h * 0.92)
    _rnd.VID_W = int(_rnd.VID_H * 9 / 16)
    _rnd.VID_X = (scr_w - _rnd.VID_W) // 2
    _rnd.VID_Y = (scr_h - _rnd.VID_H) // 2
    _rnd._bg_cache   = None
    _rnd._mask_cache = None
    _rnd._ar_cache   = {}

    canvas = np.zeros((scr_h, scr_w, 3), dtype=np.uint8)

    print("=== Gaze Reels started ===")
    print("  Look at video → PLAY  |  Look away → PAUSE")
    print("  Close eyes 0.5s → NEXT  |  [Q] quit")
    print("  Auto-calibrating for first 3 seconds — just look at the screen")

    prev_time     = time.time()
    _playing_audio = False   # track audio state

    # Start audio for first reel
    if reel_paths:
        audio.play(reel_paths[reel_idx])
        _playing_audio = True

    while True:
        now  = time.time()
        prev_time = now

        # Read background video frame (loop)
        if bg_cap is not None:
            ret_bg, bg_f = bg_cap.read()
            if not ret_bg:
                bg_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                _, bg_f = bg_cap.read()
            if bg_f is not None:
                bg_frame_cur = bg_f

        ret, cam_frame = cam.read()
        if not ret:
            break
        cam_frame = cv2.flip(cam_frame, 1)

        track        = tracker.process(cam_frame)
        ear          = track["ear"]
        gaze_ratio   = track["gaze_ratio"]
        gaze_ratio_v = track.get("gaze_ratio_v", 0.5)
        gaze_screen  = track["gaze_screen"]

        on_heart = gaze_on_heart(gaze_screen, _rnd.WIN_W, _rnd.WIN_H)
        ctrl.update(ear, gaze_ratio, on_heart, reel_idx, gaze_ratio_v)

        if ctrl.trigger_next:
            scroll_prev_frame = last_vid_frame
            reel_idx          = (reel_idx + 1) % reel_total
            last_vid_frame    = None
            scroll_anim_start = now
            ctrl.on_next_reel()
            if reel_caps:
                reel_caps[reel_idx].set(cv2.CAP_PROP_POS_FRAMES, 0)
            # Switch audio to new reel
            if reel_paths:
                audio.play(reel_paths[reel_idx])
            # Switch background video when threshold crossed
            new_bg_path = _bg_path_for_reel(reel_idx)
            if new_bg_path != bg_current_path:
                if bg_cap is not None:
                    bg_cap.release()
                bg_cap          = _open_bg(new_bg_path)
                bg_current_path = new_bg_path
            print(f"[NEXT] → Reel {reel_idx + 1}")

        # Pause / resume audio with video
        if reel_paths:
            if ctrl.playing and not _playing_audio:
                # Sync audio position with video position
                if reel_caps:
                    fps = reel_caps[reel_idx].get(cv2.CAP_PROP_FPS) or 30
                    pos = reel_caps[reel_idx].get(cv2.CAP_PROP_POS_FRAMES)
                    seek = pos / fps
                else:
                    seek = 0.0
                audio.play(reel_paths[reel_idx], seek=seek)
                _playing_audio = True
            elif not ctrl.playing and _playing_audio:
                audio.stop()
                _playing_audio = False

        # Loop audio when done
        if ctrl.playing and reel_paths and audio.is_done():
            audio.play(reel_paths[reel_idx])

        if ctrl.trigger_like:
            print(f"[LIKE]      Reel {reel_idx + 1} liked ❤")
        if ctrl.trigger_like_menu:
            print(f"[LIKE menu] Reel {reel_idx + 1} liked ❤")
        if ctrl.trigger_save:
            print(f"[SAVE]      Reel {reel_idx + 1} saved 🔖")

        if reel_caps:
            cap = reel_caps[reel_idx]
            if ctrl.playing:
                new_frame = read_next_frame(cap)
                if new_frame is not None:
                    last_vid_frame = new_frame
        vid_frame = last_vid_frame   # always show last frame (freeze on pause)

        scroll_prog = min(1.0, (now - scroll_anim_start) / scroll_anim_dur)  # 0→1

        h_dev = abs(gaze_ratio   - ctrl.center_h)
        v_dev = abs(gaze_ratio_v - ctrl.center_v) * 3.5  # match controller multiplier

        # Warmup state for overlay
        if not ctrl._warmed_up:
            elapsed = time.time() - ctrl._start_time
            if elapsed < 3.0:
                warmup_state = ('delay', 3.0 - elapsed)
            else:
                prog = len(ctrl._warmup_h) / 60.0
                warmup_state = ('collect', min(prog, 1.0))
        else:
            warmup_state = None

        draw_frame(
            canvas          = canvas,
            video_frame     = vid_frame,
            playing         = ctrl.playing,
            gaze_ratio      = gaze_ratio,
            gaze_ratio_v    = gaze_ratio_v,
            center_h        = ctrl.center_h,
            center_v        = ctrl.center_v,
            h_dev           = h_dev,
            scroll_prog     = scroll_prog,
            scroll_prev     = scroll_prev_frame,
            v_dev           = v_dev,
            debug           = show_debug,
            warmup_state    = warmup_state,
            action_progress = ctrl.action_progress,
            btn_focus       = ctrl.btn_focus,
            btn_progress    = ctrl.btn_progress,
            like_anim_t     = ctrl.like_anim_t,
            save_anim_t     = ctrl.save_anim_t,
            menu_liked      = reel_idx in ctrl.menu_liked_ids,
            menu_saved      = reel_idx in ctrl.menu_saved_ids,
            bg_video_frame  = bg_frame_cur,
        )

        cv2.imshow(win_name, canvas)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), ord('Q'), 27):
            break
        elif key in (ord('d'), ord('D')):
            show_debug = not show_debug

    audio.stop()
    cam.release()

    if bg_cap is not None:
        bg_cap.release()
    for c in reel_caps:
        c.release()
    tracker.release()
    cv2.destroyAllWindows()
    print("Bye!")


if __name__ == "__main__":
    main()
