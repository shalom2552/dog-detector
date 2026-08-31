"""Threaded video capture with auto-reconnect.

read() returns a private copy of the latest frame, or None when none is fresh
(source not started, or dropped). The copy keeps the capture buffer immutable for
callers that annotate in place; the freshness check stops a dropped stream from
being served as live.
"""

import logging
import threading
import time

import cv2

log = logging.getLogger("camera")


class FrameReader:
    """Background capture with reconnect and frame-freshness tracking."""

    def __init__(self, src, reopen_delay=2.0, reopen_cap=30.0, drop_after=30):
        self._src = src
        self._reopen_delay = reopen_delay   # first reopen wait; doubles while the source stays down
        self._reopen_cap = reopen_cap       # ceiling for the reopen backoff
        self._drop_after = drop_after       # consecutive read failures before reopen
        log.info("Opening video source: %r", src)
        self._cap = self._open(src)

        import os
        self._is_file = isinstance(src, str) and not src.startswith("rtsp://") and os.path.isfile(src)
        self._delay = 0.0
        if self._is_file and self._cap:
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            self._delay = 1.0 / fps if (fps and fps > 0) else 0.033

        self._frame = None
        self._frame_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    @staticmethod
    def _open(src):
        # FFMPEG backend for RTSP; pair with OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp
        # (see .env.example) to avoid UDP frame corruption.
        try:
            if isinstance(src, str) and src.startswith("rtsp://"):
                cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            else:
                cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                return None
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # drain latency; harmless where unsupported
            return cap
        except Exception:  # noqa: BLE001 — a bad source must read as "closed", not crash
            log.exception("Failed to open video source %r", src)
            return None

    def _drop_capture(self):
        """Release and forget the capture handle so the loop reopens it."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    def _loop(self):
        fail = 0
        backoff = self._reopen_delay
        while not self._stop.is_set():
            try:
                if self._cap is None or not self._cap.isOpened():
                    time.sleep(backoff)
                    backoff = min(backoff * 2, self._reopen_cap)
                    log.warning("Reopening video source %r", self._src)
                    self._cap = self._open(self._src)
                    if self._cap and self._is_file:
                        fps = self._cap.get(cv2.CAP_PROP_FPS)
                        self._delay = 1.0 / fps if (fps and fps > 0) else 0.033
                    continue

                ok, frame = self._cap.read()
                if self._stop.is_set():
                    break
                if not ok:
                    if self._is_file and self._cap:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    fail += 1
                    if fail >= self._drop_after:
                        log.warning("Source %r stopped delivering — reconnecting", self._src)
                        self._drop_capture()
                        fail = 0
                    else:
                        time.sleep(0.01)
                    continue

                fail = 0
                backoff = self._reopen_delay  # a healthy read earns a fresh backoff
                if self._is_file and self._delay > 0:
                    time.sleep(self._delay)

                with self._lock:
                    self._frame = frame
                    self._frame_at = time.monotonic()
            except Exception:
                # cv2 can raise on corrupt streams; drop the handle and reconnect
                # rather than letting the capture thread die.
                log.exception("Capture error on %r — reconnecting", self._src)
                self._drop_capture()
                fail = 0

    def read(self, max_age=2.0):
        """Return a private copy of the latest frame, or None if stale/absent."""
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_at > max_age:
                return None
            return self._frame.copy()

    def release(self):
        self._stop.set()
        self._thread.join(timeout=3)
        self._drop_capture()
