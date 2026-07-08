"""Motion gate: cheap diff over the zone crop to decide whether to run YOLO."""

import cv2
import numpy as np

import config


def motion_detected(frame, motion_bg, bbox, threshold):
    """Return (detected, new_bg): a downscaled gray zone crop diffed against an EMA background.

    `threshold` is the changed-pixel count above which motion is reported. The EMA
    lets a scene that drifted far from the reference still read as motion.
    """
    x, y, w, h = bbox
    crop = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(crop, (config.MOTION_CROP, config.MOTION_CROP)).astype(np.float32)
    if motion_bg is None:
        return True, gray
    diff = cv2.absdiff(gray, motion_bg)
    changed = cv2.countNonZero((diff >= config.MOTION_DIFF_THRESHOLD).astype(np.uint8))
    new_bg = (1 - config.MOTION_BG_ALPHA) * motion_bg + config.MOTION_BG_ALPHA * gray
    return changed >= threshold, new_bg
