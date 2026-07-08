"""InferenceWorker: the shared background inference thread."""

import logging
import threading
import time
from collections import deque

log = logging.getLogger("detector")


class InferenceWorker:
    """Runs the shared backend in one background thread over per-camera frame slots.

    submit() keeps only a camera's latest frame; the drain loop services queued
    cameras in submit order (each queued at most once → fair round-robin). One
    backend, one thread: N cameras cost at most 1x model CPU.

    Result boxes per camera: (x1, y1, x2, y2, conf, in_zone), monotonic-timestamped
    so callers can discard stale detections.
    """

    def __init__(self, backend, autostart=True):
        self._backend = backend
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._slots: dict = {}      # cam_id -> (frame, zone, conf_threshold), latest only
        self._queue: deque = deque()  # cam_ids with a pending slot, oldest first
        self._results: dict = {}    # cam_id -> (boxes, boxes_at)
        if autostart:  # tests drive _service_next() directly
            threading.Thread(target=self._loop, name="inference", daemon=True).start()

    def submit(self, cam_id, frame, zone, conf_threshold):
        """Queue a frame for inference, dropping any unprocessed frame from this camera."""
        with self._lock:
            if cam_id not in self._slots:
                self._queue.append(cam_id)
            self._slots[cam_id] = (frame.copy(), zone, conf_threshold)
        self._ready.set()

    def current_boxes(self, cam_id):
        """Return (boxes, monotonic_timestamp) of the camera's latest result, without blocking."""
        with self._lock:
            boxes, boxes_at = self._results.get(cam_id, ([], 0.0))
            return list(boxes), boxes_at

    def _set_boxes(self, cam_id, boxes):
        with self._lock:
            self._results[cam_id] = (boxes, time.monotonic())

    def _service_next(self):
        """Run inference for the longest-waiting camera. Return False when idle."""
        with self._lock:
            if not self._queue:
                return False
            cam_id = self._queue.popleft()
            frame, zone, conf_threshold = self._slots.pop(cam_id)
        try:
            boxes = []
            for x1, y1, x2, y2, conf in self._backend.detect(frame, conf_threshold):
                in_zone = zone.contains_box((x1, y1, x2, y2))
                if in_zone:
                    log.debug("[%s] dog in zone  conf=%.2f  box=%s", cam_id, conf, (x1, y1, x2, y2))
                boxes.append((x1, y1, x2, y2, conf, in_zone))
            self._set_boxes(cam_id, boxes)
        except Exception:
            log.exception("[%s] Inference error — skipping frame", cam_id)
            self._set_boxes(cam_id, [])  # don't let a stale result latch presence
        return True

    def _loop(self):
        while True:
            self._ready.wait()
            self._ready.clear()
            while self._service_next():
                pass
