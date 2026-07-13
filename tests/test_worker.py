"""CameraWorker._maybe_infer: motion-gate bypass while chasing a candidate."""

import types

import config
from core import worker as worker_mod
from core.state import DetectionState

NOW = 1000.0


class FakeInference:
    def __init__(self):
        self.submitted = []

    def submit(self, cam_id, frame, zone, conf_threshold):
        self.submitted.append(cam_id)


def _worker(state):
    w = worker_mod.CameraWorker.__new__(worker_mod.CameraWorker)
    w.cfg = types.SimpleNamespace(id="cam", detect_fps=10.0, conf_threshold=0.3,
                                  motion_threshold=100)
    w.state = state
    w._inference = FakeInference()
    w._zone = types.SimpleNamespace(bbox=(0, 0, 10, 10))
    return w


def _no_motion(monkeypatch):
    monkeypatch.setattr(worker_mod, "motion_detected", lambda *a: (False, None))


def test_streak_bypasses_motion_gate(monkeypatch):
    """An accumulating candidate keeps inference on at detect_fps, gate closed or not."""
    _no_motion(monkeypatch)
    w = _worker(DetectionState(present_streak=1, last_infer=NOW - 0.5))
    w._maybe_infer(frame=None, now=NOW)
    assert w._inference.submitted == ["cam"]


def test_recent_sighting_bypasses_motion_gate(monkeypatch):
    """A sighting within grace keeps inference on so one miss doesn't stall the chase."""
    _no_motion(monkeypatch)
    w = _worker(DetectionState(last_seen_in_zone=NOW - config.ABSENCE_GRACE / 2,
                               last_infer=NOW - 0.5))
    w._maybe_infer(frame=None, now=NOW)
    assert w._inference.submitted == ["cam"]


def test_armed_bypasses_motion_gate(monkeypatch):
    _no_motion(monkeypatch)
    w = _worker(DetectionState(in_zone_since=NOW - 1.0, last_infer=NOW - 0.5))
    w._maybe_infer(frame=None, now=NOW)
    assert w._inference.submitted == ["cam"]


def test_idle_without_motion_waits_for_heartbeat(monkeypatch):
    """No candidate, no motion, heartbeat not due → no inference."""
    _no_motion(monkeypatch)
    w = _worker(DetectionState(last_seen_in_zone=NOW - config.ABSENCE_GRACE * 5,
                               last_infer=NOW - 0.5))
    w._maybe_infer(frame=None, now=NOW)
    assert w._inference.submitted == []


def test_heartbeat_forces_inference(monkeypatch):
    _no_motion(monkeypatch)
    w = _worker(DetectionState(last_infer=NOW - config.MOTION_HEARTBEAT_SECONDS - 0.1))
    w._maybe_infer(frame=None, now=NOW)
    assert w._inference.submitted == ["cam"]
