"""
UI Renderer — clean Instagram Reels look.

Layout (auto-detects screen resolution):
  Background: blurred room photo
  9:16 video panel centred, rounded corners
  Subtle dim overlay when paused
  Action menu (Like / Save) pill slides up on down-gaze dwell
"""

import cv2
import numpy as np
import os
import math
import time as _time_mod
from PIL import Image, ImageDraw, ImageFont

WIN_W, WIN_H = 1280, 720

VID_H = int(WIN_H * 0.92)
VID_W = int(VID_H * 9 / 16)
VID_X = (WIN_W - VID_W) // 2
VID_Y = (WIN_H - VID_H) // 2

CORNER_R  = 56

MATERIALS   = os.path.join(os.path.dirname(__file__), "materials")
BG_PATH     = os.path.join(MATERIALS,
              "city_night_illuminated_promotion_advertising_neon_lights_colorful-745571.jpg!s2 1.jpg")
BG_FALLBACK = os.path.join(MATERIALS, "street_photo.jpeg")
PAUSE_PATH  = os.path.join(MATERIALS, "pause.png")
AR_OVERLAY_PATH = os.path.join(MATERIALS, "накладкаAR.png")
ICONS_DIR   = os.path.join(MATERIALS, "Icons")
MENU_ICON_FILES = {
    'like_idle'  : "сердечко_неактивное.png",
    'like_on'    : "лайк_активное.png",
    'save_idle'  : "сохрание_неактивная.png",
    'save_on'    : "избраное_активное.png",
}

# User-specified palette
LIKE_RED_BGR = (86, 86, 220)    # #DC5656
LOAD_YEL_BGR = (86, 207, 220)   # #DCCF56

_menu_icon_cache = {}   # keyed by (name, size)


def _get_menu_icon(name, size):
    """Load PNG icon with alpha, resized to square size. Cached."""
    key = (name, size)
    if key in _menu_icon_cache:
        return _menu_icon_cache[key]
    path = os.path.join(ICONS_DIR, MENU_ICON_FILES[name])
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        _menu_icon_cache[key] = None
        return None
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    if img.shape[2] == 4:
        bgr = img[:, :, :3]
        a   = img[:, :, 3]
    else:
        bgr = img
        a   = np.full(img.shape[:2], 255, dtype=np.uint8)
    _menu_icon_cache[key] = (bgr, a)
    return _menu_icon_cache[key]


def _paste_icon(canvas, icon, cx, cy, alpha_mul=1.0):
    """Alpha-composite icon (bgr, a) centered at (cx, cy)."""
    if icon is None:
        return
    bgr, a = icon
    h, w = bgr.shape[:2]
    x1 = cx - w // 2
    y1 = cy - h // 2
    x2 = x1 + w
    y2 = y1 + h
    H, W = canvas.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > W or y2 > H:
        return
    roi   = canvas[y1:y2, x1:x2].astype(np.float32)
    alpha = (a.astype(np.float32) / 255.0 * alpha_mul)[:, :, np.newaxis]
    canvas[y1:y2, x1:x2] = (roi * (1 - alpha) +
                            bgr.astype(np.float32) * alpha).astype(np.uint8)
SF_FONT     = os.path.expanduser("~/Library/Fonts/SF-Pro-Display-Bold.otf")

_bg_cache      = None
_mask_cache    = None
_pause_cache   = None
_ar_cache      = {}    # keyed by (w, h)
_text_cache    = {}    # PIL-rendered text tiles

VIDEO_ALPHA = 0.42   # video opacity — AR glasses effect, background visible through

PAUSE_SIZE = 72


def _get_pause_icon():
    global _pause_cache
    if _pause_cache is None:
        img = cv2.imread(PAUSE_PATH, cv2.IMREAD_UNCHANGED)
        if img is None:
            icon = np.zeros((PAUSE_SIZE, PAUSE_SIZE, 4), dtype=np.uint8)
            bw = PAUSE_SIZE // 5
            for x in [PAUSE_SIZE//4 - bw//2, PAUSE_SIZE*3//4 - bw//2]:
                icon[PAUSE_SIZE//5:PAUSE_SIZE*4//5, x:x+bw] = (255, 255, 255, 200)
            img = icon
        img = cv2.resize(img, (PAUSE_SIZE, PAUSE_SIZE))
        if img.shape[2] == 4:
            _pause_cache = (img[:, :, :3], img[:, :, 3])
        else:
            _pause_cache = (img, np.full((PAUSE_SIZE, PAUSE_SIZE), 200, dtype=np.uint8))
    return _pause_cache


def _get_bg():
    global _bg_cache
    if _bg_cache is None:
        img = cv2.imread(BG_PATH)
        if img is None:
            img = cv2.imread(BG_FALLBACK)
        if img is None:
            img = np.zeros((WIN_H, WIN_W, 3), dtype=np.uint8)

        img_h, img_w = img.shape[:2]
        # "cover" scaling: scale to fill entire screen, then center-crop
        scale = max(WIN_W / img_w, WIN_H / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img   = cv2.resize(img, (new_w, new_h))
        x0    = (new_w - WIN_W) // 2
        y0    = (new_h - WIN_H) // 2
        img   = img[y0:y0 + WIN_H, x0:x0 + WIN_W]

        # Slight darken so video panel pops
        img = (img.astype(np.float32) * 0.55).astype(np.uint8)
        _bg_cache = img
    return _bg_cache.copy()


def _draw_text_sf(canvas, text, cx, y, size, color_bgr=(255, 255, 255)):
    """
    Draw text centred at (cx, y) using SF Pro Display Bold via PIL.
    Returns rendered text width.
    """
    global _text_cache
    key = (text, size, color_bgr)
    if key not in _text_cache:
        try:
            font = ImageFont.truetype(SF_FONT, size)
        except Exception:
            font = ImageFont.load_default()
        dummy = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        bb    = dummy.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0] + 4, bb[3] - bb[1] + 4
        tile   = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text(
            (2 - bb[0], 2 - bb[1]), text, font=font,
            fill=(color_bgr[2], color_bgr[1], color_bgr[0], 255))
        _text_cache[key] = np.array(tile)

    arr      = _text_cache[key]
    h, w     = arr.shape[:2]
    x1       = int(cx) - w // 2
    y1       = int(y)
    x2, y2   = min(x1 + w, canvas.shape[1]), min(y1 + h, canvas.shape[0])
    x1c      = max(x1, 0)
    if x2 <= x1c or y2 <= y1:
        return w
    aw, ah   = x2 - x1c, y2 - y1
    ox       = x1c - x1
    a        = arr[:ah, ox:ox+aw, 3:4].astype(np.float32) / 255.0
    rgb      = arr[:ah, ox:ox+aw, :3][:, :, ::-1].astype(np.float32)
    roi      = canvas[y1:y2, x1c:x2].astype(np.float32)
    canvas[y1:y2, x1c:x2] = (roi*(1-a) + rgb*a).astype(np.uint8)
    return w


def _get_mask():
    global _mask_cache
    if _mask_cache is None:
        m = np.zeros((VID_H, VID_W), dtype=np.uint8)
        r = CORNER_R
        cv2.rectangle(m, (r, 0),   (VID_W-r, VID_H),   255, -1)
        cv2.rectangle(m, (0, r),   (VID_W,   VID_H-r), 255, -1)
        for cx, cy in [(r,r),(VID_W-r,r),(r,VID_H-r),(VID_W-r,VID_H-r)]:
            cv2.circle(m, (cx, cy), r, 255, -1)
        _mask_cache = m
    return _mask_cache


def _get_ar_overlay(w, h):
    """Load and cache the AR frame overlay resized to (w, h)."""
    global _ar_cache
    key = (w, h)
    if key not in _ar_cache:
        img = cv2.imread(AR_OVERLAY_PATH, cv2.IMREAD_UNCHANGED)
        if img is None or img.shape[2] < 4:
            _ar_cache[key] = None
            return None
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        bgr   = img[:, :, :3].astype(np.float32)
        alpha = (img[:, :, 3] / 255.0)[:, :, np.newaxis]
        _ar_cache[key] = (bgr, alpha)
    return _ar_cache[key]


# ── Icon drawing helpers ──────────────────────────────────────────────────────

def _heart_pts(cx, cy, half_size):
    """Parametric heart curve — perfect shape, 80 points."""
    s   = half_size / 16.0
    pts = []
    N   = 80
    for i in range(N):
        t = 2 * math.pi * i / N
        x = 16 * math.sin(t) ** 3
        y = (13*math.cos(t) - 5*math.cos(2*t)
             - 2*math.cos(3*t) - math.cos(4*t))
        pts.append([cx + int(x * s), cy - int(y * s)])
    return np.array(pts, dtype=np.int32)


def _bookmark_pts(cx, cy, hw, hh):
    """Clean bookmark: rectangle + V-notch at bottom."""
    notch = int(hh * 0.42)
    return np.array([
        [cx - hw, cy - hh],
        [cx + hw, cy - hh],
        [cx + hw, cy + hh],
        [cx,      cy + hh - notch],
        [cx - hw, cy + hh],
    ], dtype=np.int32)


def _draw_heart_outline(canvas, cx, cy, half_size, color, thickness=2):
    pts = _heart_pts(cx, cy, half_size)
    cv2.polylines(canvas, [pts], True, color, thickness, cv2.LINE_AA)


def _draw_heart_filled(canvas, cx, cy, half_size, color):
    pts = _heart_pts(cx, cy, half_size)
    cv2.fillPoly(canvas, [pts], color)
    cv2.polylines(canvas, [pts], True, color, 1, cv2.LINE_AA)


def _draw_bookmark_outline(canvas, cx, cy, size, color, thickness=2):
    hw = int(size * 0.46)
    hh = int(size * 0.60)
    cv2.polylines(canvas, [_bookmark_pts(cx, cy, hw, hh)],
                  True, color, thickness, cv2.LINE_AA)


def _draw_bookmark_filled(canvas, cx, cy, size, color):
    hw = int(size * 0.46)
    hh = int(size * 0.60)
    pts = _bookmark_pts(cx, cy, hw, hh)
    cv2.fillPoly(canvas, [pts], color)
    cv2.polylines(canvas, [pts], True, color, 1, cv2.LINE_AA)


def _rounded_rect(canvas, x1, y1, x2, y2, r, color, alpha_val=1.0, thickness=-1):
    """Draw a rounded rectangle, optionally blended."""
    if alpha_val < 1.0:
        overlay = canvas.copy()
        _rounded_rect(overlay, x1, y1, x2, y2, r, color)
        cv2.addWeighted(overlay, alpha_val, canvas, 1 - alpha_val, 0, canvas)
        return
    cv2.rectangle(canvas, (x1+r, y1), (x2-r, y2), color, thickness)
    cv2.rectangle(canvas, (x1, y1+r), (x2, y2-r), color, thickness)
    for cx, cy in [(x1+r, y1+r), (x2-r, y1+r), (x1+r, y2-r), (x2-r, y2-r)]:
        cv2.circle(canvas, (cx, cy), r, color, thickness)


# ── Main draw function ────────────────────────────────────────────────────────

def draw_frame(canvas, video_frame, playing, gaze_ratio=0.5,
               gaze_ratio_v=0.0, center_h=0.5, center_v=0.0,
               h_dev=0.0, v_dev=0.0, debug=False,
               warmup_state=None, scroll_prog=1.0, scroll_prev=None,
               action_progress=0.0, btn_focus=None, btn_progress=0.0,
               like_anim_t=0.0, save_anim_t=0.0,
               menu_liked=False, menu_saved=False,
               bg_video_frame=None,
               **_kwargs):
    """
    like_anim_t / save_anim_t: time.time() of last activation (for micro-anim)
    menu_liked / menu_saved: persistent activated state for this reel
    """

    # ── Background ────────────────────────────────────────────────────────────
    if bg_video_frame is not None:
        bvf = cv2.resize(bg_video_frame, (WIN_W, WIN_H))
        canvas[:] = (bvf.astype(np.float32) * 0.52).astype(np.uint8)
    else:
        canvas[:] = _get_bg()

    # ── Video frame ───────────────────────────────────────────────────────────
    if video_frame is not None:
        vf = cv2.resize(video_frame, (VID_W, VID_H))
    else:
        vf = np.full((VID_H, VID_W, 3), 30, dtype=np.uint8)

    mask  = _get_mask()
    mask3 = cv2.merge([mask, mask, mask])

    # ── Scroll animation ──────────────────────────────────────────────────────
    if scroll_prog < 1.0 and scroll_prev is not None:
        prev   = cv2.resize(scroll_prev, (VID_W, VID_H))
        t      = 1.0 - (1.0 - scroll_prog) ** 3
        offset = int(VID_H * t)
        combined = np.zeros_like(vf)
        if offset < VID_H:
            combined[VID_H - offset:, :] = vf[:offset, :]
            combined[:VID_H - offset, :] = prev[offset:, :]
        else:
            combined = vf
        vf = combined

    # AR transparency: blend video with background beneath it
    bg_roi  = canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W].copy()
    vf_ar   = cv2.addWeighted(vf, VIDEO_ALPHA, bg_roi, 1.0 - VIDEO_ALPHA, 0)
    vf      = np.where(mask3 > 0, vf_ar, 0)

    roi = canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W]
    roi[:] = np.where(mask3 > 0, vf, roi)

    # ── AR frame overlay (накладкаAR.png) — drawn over video, under UI ───────
    ar = _get_ar_overlay(VID_W, VID_H)
    if ar is not None:
        ar_bgr, ar_alpha = ar
        roi2 = canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W].astype(np.float32)
        canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W] = (
            roi2 * (1.0 - ar_alpha) + ar_bgr * ar_alpha
        ).astype(np.uint8)

    # ── "Reels" title — SF Pro Display Bold, centred, no stroke ─────────────
    _draw_text_sf(canvas, "Reels",
                  cx=VID_X + VID_W // 2, y=VID_Y + 22,
                  size=32, color_bgr=(255, 255, 255))

    # ── Warmup overlay ────────────────────────────────────────────────────────
    if warmup_state is not None:
        kind = warmup_state[0]
        cx   = VID_X + VID_W // 2
        cy   = VID_Y + VID_H // 2
        if kind == 'delay':
            secs_left = warmup_state[1]
            for m, dy in [("Look at the screen", -20),
                          (f"Starting in {secs_left:.0f}s...", 20)]:
                tw = cv2.getTextSize(m, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0][0]
                cv2.putText(canvas, m, (cx - tw//2, cy + dy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2, cv2.LINE_AA)
        elif kind == 'collect':
            prog = warmup_state[1]
            msg  = "Calibrating..."
            tw   = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0][0]
            cv2.putText(canvas, msg, (cx - tw//2, cy - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100,255,100), 2, cv2.LINE_AA)
            bw, bh = 200, 10
            bx, by = cx - bw//2, cy + 10
            cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh), (60,60,60), -1)
            cv2.rectangle(canvas, (bx, by), (bx+int(bw*prog), by+bh), (100,255,100), -1)

    # ── Paused overlay ────────────────────────────────────────────────────────
    if not playing:
        dimmed = cv2.addWeighted(vf, 0.6, np.zeros_like(vf), 0.4, 0)
        canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W] = np.where(
            mask3 > 0, dimmed,
            canvas[VID_Y:VID_Y+VID_H, VID_X:VID_X+VID_W])
        icon_bgr, icon_a = _get_pause_icon()
        s   = PAUSE_SIZE
        cx  = VID_X + VID_W // 2
        cy  = VID_Y + VID_H // 2
        x1, y1 = cx - s//2, cy - s//2
        x2, y2 = x1 + s,    y1 + s
        if 0 <= x1 and x2 <= WIN_W and 0 <= y1 and y2 <= WIN_H:
            roi2  = canvas[y1:y2, x1:x2].astype(np.float32)
            alpha = (icon_a / 255.0)[:, :, np.newaxis]
            canvas[y1:y2, x1:x2] = (roi2*(1-alpha) +
                                     icon_bgr.astype(np.float32)*alpha).astype(np.uint8)

    # ── Action menu — Like / Save ─────────────────────────────────────────────
    if action_progress > 0.0:
        import math
        now_t = _time_mod.time()

        slide_t = min(action_progress / 0.40, 1.0)
        ease    = 1.0 - (1.0 - slide_t) ** 2   # ease-out quad
        a       = ease

        BTN_R  = 44
        BASE_Y = VID_Y + VID_H - 58
        SLIDE  = int((1.0 - ease) * (BTN_R * 2 + 40))
        btn_cy = BASE_Y - BTN_R - SLIDE
        btn1_x = VID_X + VID_W // 5
        btn2_x = VID_X + VID_W * 4 // 5

        # Icon half-sizes — proportional to circle, same for both
        BASE_HS = int(BTN_R * 0.56)   # heart half-size ≈ 25px → width ≈ 50px

        # Micro-animation pulses
        like_pulse = (math.sin((now_t - like_anim_t) / 0.6 * math.pi)
                      if now_t - like_anim_t < 0.6 else 0.0)
        save_pulse = (math.sin((now_t - save_anim_t) / 0.6 * math.pi)
                      if now_t - save_anim_t < 0.6 else 0.0)

        # Icon size = full button circle (PNG includes its own dark circle)
        ICON_BASE = BTN_R * 2

        # ── LIKE ─────────────────────────────────────────────────────────
        like_focused = btn_focus == 'like'
        like_scale   = 1.0 + 0.12 * like_pulse
        like_size    = max(8, int(ICON_BASE * like_scale))

        like_icon = _get_menu_icon(
            'like_on' if menu_liked else 'like_idle', like_size)
        _paste_icon(canvas, like_icon, btn1_x, btn_cy, alpha_mul=a)

        # Dwell ring — user red #DC5656
        if like_focused and btn_progress > 0.0 and not menu_liked:
            rr      = BTN_R + 9
            end_ang = int(-90 + 360 * btn_progress)
            cv2.ellipse(canvas, (btn1_x, btn_cy), (rr, rr),
                        0, 0, 360, (40, 40, 40), 4, cv2.LINE_AA)
            cv2.ellipse(canvas, (btn1_x, btn_cy), (rr, rr),
                        0, -90, end_ang, LIKE_RED_BGR, 5, cv2.LINE_AA)

        # ── SAVE ─────────────────────────────────────────────────────────
        save_focused = btn_focus == 'save'
        save_scale   = 1.0 + 0.12 * save_pulse
        save_size    = max(8, int(ICON_BASE * save_scale))

        save_icon = _get_menu_icon(
            'save_on' if menu_saved else 'save_idle', save_size)
        _paste_icon(canvas, save_icon, btn2_x, btn_cy, alpha_mul=a)

        # Dwell ring — user yellow #DCCF56
        if save_focused and btn_progress > 0.0 and not menu_saved:
            rr      = BTN_R + 9
            end_ang = int(-90 + 360 * btn_progress)
            cv2.ellipse(canvas, (btn2_x, btn_cy), (rr, rr),
                        0, 0, 360, (40, 40, 40), 4, cv2.LINE_AA)
            cv2.ellipse(canvas, (btn2_x, btn_cy), (rr, rr),
                        0, -90, end_ang, LOAD_YEL_BGR, 5, cv2.LINE_AA)

        # Entry-dwell arc while menu slides in
        if action_progress < 1.0:
            arc_cx  = VID_X + VID_W // 2
            arc_cy  = btn_cy - BTN_R - 12
            arc_end = int(-90 + 360 * action_progress)
            cv2.ellipse(canvas, (arc_cx, arc_cy), (20, 6),
                        0, -90, arc_end, LOAD_YEL_BGR, 2, cv2.LINE_AA)

    # ── Debug overlay ─────────────────────────────────────────────────────────
    if debug:
        import math
        from controller import H_HALF_ZONE, V_HALF_ZONE, V_ACTION_LO

        ch  = center_h if center_h is not None else 0.0
        cv_ = center_v if center_v is not None else 0.0

        h_attn  = min(h_dev / H_HALF_ZONE, 1.0)
        v_attn  = min(v_dev / V_HALF_ZONE, 1.0)
        attn    = max(h_attn, v_attn)
        focused = attn < 1.0 and playing
        now_t   = _time_mod.time()
        pulse   = 0.5 + 0.5 * math.sin(now_t * (2 + attn * 8) * math.pi)

        if focused:
            badge_txt = "ATTENTION"
            badge_col = (0, int(180 + 75 * (1 - attn)), 0)
        else:
            badge_txt = "DISTRACTED"
            badge_col = (0, 0, int(180 + 75 * pulse))

        tw   = cv2.getTextSize(badge_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)[0][0]
        bx_b = VID_X + VID_W // 2 - tw // 2
        by_b = VID_Y - 22
        if not focused:
            gv = int(40 * pulse)
            cv2.rectangle(canvas, (bx_b-10, by_b-18), (bx_b+tw+10, by_b+6), (0,0,gv), -1)
        cv2.putText(canvas, badge_txt, (bx_b, by_b),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, badge_col, 2, cv2.LINE_AA)

        lines = [
            f"H {gaze_ratio:+.3f} dev:{h_dev:.3f}/{H_HALF_ZONE}",
            f"V {gaze_ratio_v:+.3f} dev:{v_dev:.3f}/{V_HALF_ZONE}",
            f"action:{action_progress:.2f}  btn:{btn_focus}  prg:{btn_progress:.2f}",
        ]
        for i, line in enumerate(lines):
            y = 22 + i * 20
            cv2.putText(canvas, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (120,120,120), 1, cv2.LINE_AA)

        # H bar
        BAR_W = VID_W - 20
        BAR_H = 14
        bx    = VID_X + 10
        by    = VID_Y + VID_H + 8
        if by + BAR_H < WIN_H:
            cv2.rectangle(canvas, (bx, by), (bx+BAR_W, by+BAR_H), (40,40,40), -1)
            zone_px = int(H_HALF_ZONE / 0.5 * BAR_W / 2)
            mid     = bx + BAR_W // 2
            dz_r    = int(80 + 120 * h_attn)
            cv2.rectangle(canvas, (bx, by), (mid-zone_px, by+BAR_H), (0,0,dz_r), -1)
            cv2.rectangle(canvas, (mid+zone_px, by), (bx+BAR_W, by+BAR_H), (0,0,dz_r), -1)
            gz_g = int(60 + 80 * (1 - h_attn))
            cv2.rectangle(canvas, (mid-zone_px, by), (mid+zone_px, by+BAR_H), (0,gz_g,0), -1)
            gx = int(mid + (gaze_ratio - ch) / 0.5 * BAR_W / 2)
            gx = max(bx+2, min(bx+BAR_W-2, gx))
            dot_r = 5 + int(4 * pulse * h_attn)
            cv2.circle(canvas, (gx, by+BAR_H//2), dot_r,
                       (0, int(255*(1-h_attn)), int(255*h_attn)), -1)
            cv2.putText(canvas, "H", (bx-16, by+11),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180,180,180), 1)

        # V bar
        BAR_L = VID_H - 20
        BAR_T = 14
        vbx   = VID_X + VID_W + 8
        vby   = VID_Y + 10
        if vbx + BAR_T < WIN_W:
            cv2.rectangle(canvas, (vbx, vby), (vbx+BAR_T, vby+BAR_L), (40,40,40), -1)
            zone_py = int(V_HALF_ZONE / 0.5 * BAR_L / 2)
            mid_v   = vby + BAR_L // 2
            dz_v    = int(80 + 120 * v_attn)
            cv2.rectangle(canvas, (vbx, vby), (vbx+BAR_T, mid_v-zone_py), (0,0,dz_v), -1)
            cv2.rectangle(canvas, (vbx, mid_v+zone_py), (vbx+BAR_T, vby+BAR_L), (0,0,dz_v), -1)
            gz_v = int(60 + 80 * (1 - v_attn))
            cv2.rectangle(canvas, (vbx, mid_v-zone_py), (vbx+BAR_T, mid_v+zone_py),
                          (0, gz_v, 0), -1)
            act_px = int(V_ACTION_LO / 0.5 * BAR_L / 2)
            cv2.line(canvas, (vbx, mid_v+act_px), (vbx+BAR_T, mid_v+act_px),
                     (0, 180, 180), 1)
            gy = int(mid_v + (gaze_ratio_v - cv_) / 0.5 * BAR_L / 2)
            gy = max(vby+2, min(vby+BAR_L-2, gy))
            dot_r_v = 5 + int(4 * pulse * v_attn)
            cv2.circle(canvas, (vbx+BAR_T//2, gy), dot_r_v,
                       (0, int(255*(1-v_attn)), int(255*v_attn)), -1)
            cv2.putText(canvas, "V", (vbx+1, vby-4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180,180,180), 1)

    return canvas


def heart_zone_rect():
    cx = WIN_W // 2
    cy = VID_Y + VID_H - 70
    r  = 50
    return (cx - r, cy - r, cx + r, cy + r)
