"""CameraWorker: one camera's full pipeline — capture → motion → inference → persistence → triggers → web.

Owns the FrameReader and the zone (built lazily from the first frame, rebuilt on
a web-submitted polygon). run() drives the loop until stop(); each iteration is
guarded so a bad frame can't kill the worker. Inference is delegated to the
shared InferenceWorker.
"""

import dataclasses
import logging
import os
import threading
import time

import config
from alerts.triggers import fire_triggers
from core.state import DetectionState
from pipeline import persistence
from pipeline.capture import FrameReader
from pipeline.motion import motion_detected
from pipeline.overlay import draw_detections, draw_zone
from pipeline.zone import build_zone
from storage import zones
from web import hub

log = logging.getLogger("detector")


class CameraWorker:
    """Run one camera's detection loop against the shared inference service."""

    def __init__(self, cfg, inference, state=None):
        self.cfg = cfg
        self.state = state or DetectionState()
        self._inference = inference
        self._reader = FrameReader(cfg.source)
        self._zone = None
        self._stop = threading.Event()

    # ── Per-frame pipeline phases ───────────────────────────────────────────

    def _maybe_infer(self, frame, now):
        """Gate inference at detect_fps; submit on motion, while chasing a candidate, or per heartbeat.

        Chasing — armed, a streak accumulating, or a sighting within grace —
        bypasses the motion gate so the confirming inference arrives at
        detect_fps instead of waiting out a heartbeat on a dog that stopped
        moving. It self-extinguishes: one negative result ends the streak and
        grace expires shortly after.
        """
        state = self.state
        if now - state.last_detect < 1.0 / self.cfg.detect_fps:
            return
        state.last_detect = now
        chasing = (state.in_zone_since is not None
                   or state.present_streak > 0
                   or (state.last_seen_in_zone > 0
                       and now - state.last_seen_in_zone <= config.ABSENCE_GRACE))
        if chasing or now - state.last_infer >= config.MOTION_HEARTBEAT_SECONDS:
            run = True
        else:
            run, state.motion_bg = motion_detected(
                frame, state.motion_bg, self._zone.bbox, self.cfg.motion_threshold
            )
        if run:
            self._inference.submit(self.cfg.id, frame, self._zone, self.cfg.conf_threshold)
            state.last_infer = now

    def _detect_present(self, frame, now, stale_box_secs):
        """Draw fresh boxes; return (present, boxes_at) so callers can gate on new inferences.

        Stale results are neither drawn nor counted: without motion no new
        inference replaces them, so a departed dog's boxes would otherwise
        linger on screen until the heartbeat run clears them.
        """
        boxes, boxes_at = self._inference.current_boxes(self.cfg.id)
        fresh = boxes_at > 0 and now - boxes_at <= stale_box_secs
        present = fresh and draw_detections(frame, boxes)
        return present, boxes_at

    def _maybe_fire(self, present, boxes_at, now):
        """Trigger and record timestamps once presence is confirmed."""
        if persistence.confirmed(present, boxes_at, self.state, now,
                                 self.cfg.persist_seconds, self.cfg.cooldown_seconds,
                                 config.ABSENCE_GRACE):
            fire_triggers(self.cfg, self.state)
            self.state.last_fire = now
            self.state.last_fire_wall = time.time()

    def _update_web_state(self, frame, present):
        """Push the latest frame and camera config to the web stream state."""
        hub.update(
            self.cfg.id,
            frame,
            dog_in_zone=present,
            last_trigger=self.state.last_fire_wall if self.state.last_fire_wall > 0 else None,
            paused=self.state.paused,
            model=os.path.basename(config.MODEL),
            detect_fps=self.cfg.detect_fps,
            zone_min_overlap=self.cfg.zone_min_overlap,
            conf_threshold=self.cfg.conf_threshold,
            persist_seconds=self.cfg.persist_seconds,
            cooldown_seconds=self.cfg.cooldown_seconds,
            motion_threshold=self.cfg.motion_threshold,
        )

    def _check_web_zone_updates(self):
        """Adopt a web-submitted polygon: persist it and force a zone rebuild."""
        new_points = hub.pop_zone_update(self.cfg.id)
        if new_points is not None:
            self.cfg = dataclasses.replace(self.cfg, zone_points=tuple(new_points))
            zones.save(self.cfg.id, new_points)
            log.info("[%s] Web UI submitted new polygon zone", self.cfg.id)
            self._zone = None

    # ── Loop ────────────────────────────────────────────────────────────────

    def run(self):
        """Drive capture → detect → fire → render every frame until stop()."""
        stale_box_secs = persistence.stale_box_seconds(self.cfg.detect_fps, config.ABSENCE_GRACE)
        next_tick = time.monotonic()
        while not self._stop.is_set():
            # read() returns a private copy (safe to draw on) and rejects frames
            # older than max_age, so resuming from a pause never replays stale frames.
            frame = self._reader.read()
            if frame is None:
                time.sleep(0.05)
                continue

            try:
                self._check_web_zone_updates()

                if self._zone is None:
                    self._zone = build_zone(frame, self.cfg.zone_points, self.cfg.zone_min_overlap)
                    self.state.motion_bg = None  # stale reference belongs to the old bbox

                now = time.monotonic()
                # Paused means "don't alert", not "go blind": keep the feed and zone live.
                if self.state.paused:
                    present = False
                else:
                    self._maybe_infer(frame, now)
                    present, boxes_at = self._detect_present(frame, now, stale_box_secs)
                    self._maybe_fire(present, boxes_at, now)

                draw_zone(frame, self._zone.poly)
                self.state.latest_frame = frame

                self._update_web_state(frame, present)
            except Exception:
                log.exception("[%s] pipeline iteration failed", self.cfg.id)
                time.sleep(1.0)

            # Pace by deadline so per-iteration work doesn't drag effective FPS below target.
            next_tick = max(next_tick + 1.0 / config.STREAM_FPS, time.monotonic())
            time.sleep(max(0.0, next_tick - time.monotonic()))

    def stop(self):
        """Stop the loop and release the video source."""
        self._stop.set()
        self._reader.release()
