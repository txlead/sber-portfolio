"""
Gesture controller — nose-bridge adaptive gaze (head-pose cancelled).
"""

import time

EAR_CLOSED        = 0.20
BLINK_IGNORE_MS   = 300
SCROLL_TRIGGER_MS = 2000
SCROLL_REPEAT_MS  = 1000

H_HALF_ZONE      = 0.14
V_HALF_ZONE      = 0.32
GAZE_DEBOUNCE_MS = 500

H_ESCAPE    = 0.36
V_ESCAPE_UP = 0.45

V_ACTION_LO      = 0.09
ACTION_DWELL_MS  = 1500
BTN_DWELL_MS     = 2000
MENU_CLOSE_GRACE = 2500
BTN_HYSTERESIS   = 0.10

CENTRE_UPDATE_ZONE = 0.22
ALPHA_FAST         = 0.05

WARMUP_FRAMES   = 60
RESCUE_MS       = 3000
RESCUE_GRACE_MS = 1500


class Controller:
    def __init__(self):
        self._closed_since        = None
        self._scroll_triggered    = False
        self._last_scroll_ms      = 0
        self._gaze_away_since     = None
        self._paused_since        = None
        self._rescue_at           = None
        self._menu_opened_at      = None

        self._warmup_h   = []
        self._warmup_v   = []
        self._warmed_up  = False
        self._start_time = time.time()

        self._action_since  = None
        self._menu_close_at = None
        self._btn_since     = None
        self._btn_active    = None
        self._dbg_count     = 0

        self.center_h = 0.0
        self.center_v = 0.0

        self.playing           = True
        self.trigger_next      = False
        self.trigger_like      = False
        self.trigger_like_menu = False
        self.trigger_save      = False
        self.like_progress     = 0.0
        self.liked_ids         = set()
        self.menu_liked_ids    = set()
        self.menu_saved_ids    = set()
        self.blink_count       = 0
        self.action_progress   = 0.0
        self.btn_focus         = None
        self.btn_progress      = 0.0
        self.like_anim_t       = 0.0
        self.save_anim_t       = 0.0

    def _reset_menu(self):
        self._action_since   = None
        self._menu_close_at  = None
        self._menu_opened_at = None
        self.action_progress = 0.0
        self._btn_since      = None
        self._btn_active     = None
        self.btn_focus       = None
        self.btn_progress    = 0.0

    def on_next_reel(self):
        """Call when scrolling to a new reel — clears menu + resets gaze state."""
        self._reset_menu()
        self.like_progress    = 0.0
        # Reset gaze debounce so stale "looking away" from previous reel
        # doesn't immediately pause the new reel
        self._gaze_away_since = None
        self._paused_since    = None
        self._rescue_at       = None   # clear rescue grace from previous reel

    def update(self, ear, gaze_ratio, gaze_on_heart, reel_index,
               gaze_ratio_v=0.0):

        now = time.time() * 1000
        self.trigger_next      = False
        self.trigger_like      = False
        self.trigger_like_menu = False
        self.trigger_save      = False

        if ear > EAR_CLOSED:

            # ── Warmup ────────────────────────────────────────────────────
            if not self._warmed_up:
                self.playing = True
                if time.time() - self._start_time < 3.0:
                    return
                self._warmup_h.append(gaze_ratio)
                self._warmup_v.append(gaze_ratio_v)
                if len(self._warmup_h) >= WARMUP_FRAMES:
                    self.center_h   = sum(self._warmup_h) / len(self._warmup_h)
                    self.center_v   = sum(self._warmup_v) / len(self._warmup_v)
                    self._warmed_up = True
                    print(f"[CAL] Centre H={self.center_h:.3f} V={self.center_v:.3f}")
                return

            # ── Grace after rescue ────────────────────────────────────────
            if self._rescue_at and now - self._rescue_at < RESCUE_GRACE_MS:
                self.playing         = True
                self.action_progress = 0.0
                return

            h_dev        = abs(gaze_ratio   - self.center_h)
            v_dev        = abs(gaze_ratio_v - self.center_v) * 3.5
            looking_down = (gaze_ratio_v - self.center_v) > 0
            menu_open    = self.action_progress >= 1.0

            # ── Debug ─────────────────────────────────────────────────────
            self._dbg_count += 1
            if self._dbg_count % 60 == 0:
                print(f"[DBG] v_dev={v_dev:.3f} h_dev={h_dev:.3f} "
                      f"down={looking_down} act={self.action_progress:.2f} "
                      f"btn={self.btn_focus} prg={self.btn_progress:.2f}")

            # ── STEP 1: Action menu ───────────────────────────────────────
            # Hysteresis: full threshold to START charging, lower to STAY.
            # Prevents brief tracker-noise dips from resetting the dwell progress.
            _v_thresh      = V_ACTION_LO if self._action_since is None \
                             else V_ACTION_LO * 0.60
            in_action_zone = looking_down and v_dev >= _v_thresh

            if in_action_zone:
                if self._action_since is None:
                    self._action_since = now
                self._menu_close_at  = None
                self.action_progress = min(
                    (now - self._action_since) / ACTION_DWELL_MS, 1.0)
                # Track when the menu first fully opened
                if self.action_progress >= 1.0 and self._menu_opened_at is None:
                    self._menu_opened_at = now

            elif menu_open:
                if not looking_down:
                    # Looking at video centre or up — close immediately
                    self._reset_menu()
                else:
                    # Still looking down but drifted from action zone — grace
                    if self._menu_close_at is None:
                        self._menu_close_at = now
                    if now - self._menu_close_at >= MENU_CLOSE_GRACE:
                        self._reset_menu()

            else:
                self._reset_menu()

            # ── STEP 2: Button dwell ──────────────────────────────────────
            if self.action_progress >= 1.0:
                h_offset = gaze_ratio - self.center_h

                if self._btn_active is None:
                    new_focus = 'like' if h_offset < 0 else 'save'
                elif self._btn_active == 'like':
                    new_focus = 'save' if h_offset > BTN_HYSTERESIS else 'like'
                else:
                    new_focus = 'like' if h_offset < -BTN_HYSTERESIS else 'save'

                if new_focus != self._btn_active:
                    self._btn_active  = new_focus
                    self._btn_since   = now
                    self.btn_progress = 0.0
                else:
                    self.btn_progress = min(
                        (now - self._btn_since) / BTN_DWELL_MS, 1.0)
                    if self.btn_progress >= 1.0:
                        if new_focus == 'like':
                            if reel_index in self.menu_liked_ids:
                                self.menu_liked_ids.discard(reel_index)  # unlike
                            else:
                                self.trigger_like_menu = True
                                self.menu_liked_ids.add(reel_index)      # like
                            self.like_anim_t = time.time()
                        else:
                            if reel_index in self.menu_saved_ids:
                                self.menu_saved_ids.discard(reel_index)  # unsave
                            else:
                                self.trigger_save = True
                                self.menu_saved_ids.add(reel_index)      # save
                            self.save_anim_t = time.time()
                        self._btn_since   = now
                        self.btn_progress = 0.0

                self.btn_focus = new_focus
            else:
                self._btn_since   = None
                self._btn_active  = None
                self.btn_focus    = None
                self.btn_progress = 0.0

            # ── STEP 3: Pause / play ──────────────────────────────────────
            if menu_open or in_action_zone:
                self._gaze_away_since = None
                self._paused_since    = None
                self.playing = True
            else:
                looking_away = h_dev > H_HALF_ZONE or v_dev > V_HALF_ZONE
                if looking_away:
                    if self._gaze_away_since is None:
                        self._gaze_away_since = now
                    elif now - self._gaze_away_since >= GAZE_DEBOUNCE_MS:
                        self.playing = False
                        if self._paused_since is None:
                            self._paused_since = now
                else:
                    self._gaze_away_since = None
                    self._paused_since    = None
                    self.playing = True

                    h_frac = h_dev / H_HALF_ZONE
                    v_frac = v_dev / V_HALF_ZONE
                    worst  = max(h_frac, v_frac)
                    if worst < CENTRE_UPDATE_ZONE:
                        alpha = ALPHA_FAST * (1.0 - worst / CENTRE_UPDATE_ZONE)
                        self.center_h = (1-alpha)*self.center_h + alpha*gaze_ratio
                        self.center_v = (1-alpha)*self.center_v + alpha*gaze_ratio_v

            # ── Rescue ────────────────────────────────────────────────────
            # Also fires if menu is stuck open > 8s (miscalibration guard)
            menu_stuck = (self._menu_opened_at is not None
                          and (now - self._menu_opened_at) > 8000)
            if ((not self.playing and self._paused_since is not None
                     and now - self._paused_since > RESCUE_MS) or menu_stuck):
                self.center_h         = gaze_ratio
                self.center_v         = gaze_ratio_v
                self._paused_since    = None
                self._gaze_away_since = None
                self._rescue_at       = now
                self.playing          = True
                self._reset_menu()
                print(f"[RESCUE{'(menu)' if menu_stuck else ''}]"
                      f" H={gaze_ratio:.3f} V={gaze_ratio_v:.3f}")

        # ── Eye close → scroll ────────────────────────────────────────────
        else:
            if self._closed_since is None:
                self._closed_since     = now
                self._scroll_triggered = False
                self._last_scroll_ms   = 0
            closed_dur = now - self._closed_since
            if not self._scroll_triggered and closed_dur >= SCROLL_TRIGGER_MS:
                self.trigger_next      = True
                self._scroll_triggered = True
                self._last_scroll_ms   = now
            elif self._scroll_triggered and now - self._last_scroll_ms >= SCROLL_REPEAT_MS:
                self.trigger_next    = True
                self._last_scroll_ms = now

        if ear > EAR_CLOSED and self._closed_since is not None:
            dur = now - self._closed_since
            if dur >= BLINK_IGNORE_MS:
                self.blink_count += 1
            self._closed_since     = None
            self._scroll_triggered = False

    def reset_like(self):
        self.like_progress = 0.0
