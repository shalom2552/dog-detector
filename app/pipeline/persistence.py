"""Postprocess: turn per-frame presence into a confirmed, rate-limited trigger.

A dog must stay in the zone for `persist_seconds` before firing; triggers are
rate-limited by `cooldown_seconds`. A short absence (< grace) is forgiven so one
bad inference frame can't restart a nearly-complete accumulation. All timing uses
the monotonic clock on DetectionState.
"""

import logging

log = logging.getLogger("detector")


def stale_box_seconds(detect_fps, grace):
    """Age past which a detection box is treated as absent (stops a stale box latching presence)."""
    return max(2.0 / detect_fps, grace)


def confirmed(present, boxes_at, state, now, persist_seconds, cooldown_seconds, grace):
    """Update persistence tracking; return True when the dog has held the zone long enough to fire.

    The streak only advances/resets on a genuinely new inference result (boxes_at
    changed), so re-reading the same stale result across loop ticks can't arm the
    timer by itself.
    """
    new_inference = boxes_at != state.last_streak_boxes_at

    if present:
        state.last_seen_in_zone = now
        if new_inference:
            state.last_streak_boxes_at = boxes_at
            state.present_streak += 1
            if state.in_zone_since is None and state.present_streak >= 2:
                state.in_zone_since = now
    else:
        if new_inference:
            state.last_streak_boxes_at = boxes_at
            state.present_streak = 0
        # Disarm on wall time since last sighting, not inference cadence.
        if state.in_zone_since is not None and now - state.last_seen_in_zone > grace:
            state.in_zone_since = None

    if state.in_zone_since is None:
        return False

    held = now - state.in_zone_since
    if held >= persist_seconds and now - state.last_fire >= cooldown_seconds:
        log.info("CONFIRMED: dog in zone for %.1fs -> firing triggers", held)
        return True
    return False
