"""InferenceWorker slot/drain logic with a stub backend (no onnxruntime needed)."""

import numpy as np

from pipeline.inference import InferenceWorker


class StubBackend:
    """Records calls; returns a canned box list or raises."""

    def __init__(self, result=None, raise_error=False):
        self.result = result or []
        self.raise_error = raise_error
        self.calls = []

    def detect(self, frame, conf_threshold=None):
        self.calls.append((frame, conf_threshold))
        if self.raise_error:
            raise RuntimeError("backend exploded")
        return self.result


class StubZone:
    def __init__(self, inside=True):
        self.inside = inside

    def contains_box(self, box):
        return self.inside


def _frame(value=0):
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _worker(backend):
    return InferenceWorker(backend, autostart=False)


def test_submit_service_and_read_back():
    backend = StubBackend(result=[(1, 2, 3, 4, 0.9)])
    w = _worker(backend)
    w.submit("living_room", _frame(), StubZone(inside=True), 0.35)
    assert w._service_next() is True
    boxes, boxes_at = w.current_boxes("living_room")
    assert boxes == [(1, 2, 3, 4, 0.9, True)]
    assert boxes_at > 0
    assert backend.calls[0][1] == 0.35  # per-camera conf threshold reaches the backend


def test_unknown_camera_returns_empty():
    w = _worker(StubBackend())
    assert w.current_boxes("nope") == ([], 0.0)


def test_drop_latest_per_camera():
    backend = StubBackend()
    w = _worker(backend)
    w.submit("living_room", _frame(1), StubZone(), 0.35)
    w.submit("living_room", _frame(2), StubZone(), 0.35)  # replaces the queued frame
    assert w._service_next() is True
    assert w._service_next() is False               # only one slot was pending
    assert len(backend.calls) == 1
    assert backend.calls[0][0][0, 0, 0] == 2        # the latest frame won


def test_round_robin_services_submit_order():
    backend = StubBackend()
    w = _worker(backend)
    w.submit("a", _frame(10), StubZone(), 0.3)
    w.submit("b", _frame(20), StubZone(), 0.4)
    w.submit("a", _frame(11), StubZone(), 0.3)      # updates a's slot, keeps its turn
    assert w._service_next() is True                # a (latest frame)
    assert w._service_next() is True                # b
    assert w._service_next() is False
    assert [f[0, 0, 0] for f, _ in backend.calls] == [11, 20]


def test_results_are_per_camera():
    backend = StubBackend(result=[(0, 0, 1, 1, 0.5)])
    w = _worker(backend)
    w.submit("a", _frame(), StubZone(inside=True), 0.3)
    w.submit("b", _frame(), StubZone(inside=False), 0.3)
    w._service_next()
    w._service_next()
    assert w.current_boxes("a")[0] == [(0, 0, 1, 1, 0.5, True)]
    assert w.current_boxes("b")[0] == [(0, 0, 1, 1, 0.5, False)]


def test_backend_error_clears_that_cameras_boxes():
    backend = StubBackend(result=[(0, 0, 1, 1, 0.5)])
    w = _worker(backend)
    w.submit("a", _frame(), StubZone(), 0.3)
    w._service_next()
    assert w.current_boxes("a")[0] != []
    backend.raise_error = True
    w.submit("a", _frame(), StubZone(), 0.3)
    assert w._service_next() is True                # error consumed, not raised
    boxes, boxes_at = w.current_boxes("a")
    assert boxes == []                              # stale result can't latch presence
    assert boxes_at > 0
