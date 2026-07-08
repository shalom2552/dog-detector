"""motion_detected: background-EMA gate on synthetic frames."""

import numpy as np

import config
from pipeline.motion import motion_detected

BBOX = (0, 0, 64, 64)


def _frame(value):
    return np.full((64, 64, 3), value, dtype=np.uint8)


THRESHOLD = 100  # matches the MOTION_THRESHOLD default


def test_first_call_seeds_background_and_reports_motion():
    detected, bg = motion_detected(_frame(0), None, BBOX, THRESHOLD)
    assert detected is True
    assert bg.shape == (config.MOTION_CROP, config.MOTION_CROP)


def test_static_scene_reports_no_motion():
    _, bg = motion_detected(_frame(0), None, BBOX, THRESHOLD)
    detected, _ = motion_detected(_frame(0), bg, BBOX, THRESHOLD)
    assert detected is False


def test_large_change_reports_motion():
    _, bg = motion_detected(_frame(0), None, BBOX, THRESHOLD)
    detected, _ = motion_detected(_frame(255), bg, BBOX, THRESHOLD)
    assert detected is True


def test_threshold_is_per_call():
    # A full-frame change trips a low threshold but not an impossible one.
    _, bg = motion_detected(_frame(0), None, BBOX, THRESHOLD)
    detected, _ = motion_detected(_frame(255), bg, BBOX, 30)
    assert detected is True
    detected, _ = motion_detected(_frame(255), bg, BBOX, 5000)  # > 64*64 pixels
    assert detected is False


def test_background_tracks_toward_new_frame():
    _, bg = motion_detected(_frame(0), None, BBOX, THRESHOLD)   # bg ≈ 0
    _, bg2 = motion_detected(_frame(100), bg, BBOX, THRESHOLD)  # EMA folds in 100
    assert np.allclose(bg2, config.MOTION_BG_ALPHA * 100.0, atol=1e-3)
