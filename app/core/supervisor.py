"""Supervisor: build shared services once, run one thread per CameraWorker, keep them alive.

A dead worker (e.g. the reader raising during reconnect) is restarted with
exponential backoff (5s, x2, capped at 60s), carrying its DetectionState so pause
state and cooldowns survive. SIGTERM/Ctrl-C stops every worker, releases readers,
and sends the shutdown alert.
"""

import logging
import threading
import time

import config
from alerts import bot
from alerts.triggers import shutdown_alert, startup_alert
from core.cameras import load_cameras
from pipeline.inference import InferenceWorker
from pipeline.model import load_model
from web import hub, server
from core.worker import CameraWorker

log = logging.getLogger("detector")


class Supervisor:
    """Own the shared services and one thread per camera; restart dead workers."""

    def __init__(self):
        self.workers: dict = {}    # cam_id -> CameraWorker (live registry, shared with the bot)
        self._threads: dict = {}   # cam_id -> Thread
        self._delay: dict = {}     # cam_id -> next restart backoff (seconds)
        self._retry_at: dict = {}  # cam_id -> monotonic time before which we won't restart
        self._spawned_at: dict = {}  # cam_id -> monotonic time of the last (re)spawn
        self._inference = None

    # ── Worker lifecycle ─────────────────────────────────────────────────────

    def _spawn(self, cam_id):
        thread = threading.Thread(
            target=self.workers[cam_id].run, name=f"cam-{cam_id}", daemon=True
        )
        self._spawned_at[cam_id] = time.monotonic()
        self._threads[cam_id] = thread
        thread.start()

    def _restart(self, cam_id, now):
        """Rebuild a dead worker (fresh reader, same config + state); double the backoff."""
        del self._retry_at[cam_id]
        self._delay[cam_id] = min(
            self._delay.get(cam_id, config.WORKER_BACKOFF) * 2, config.WORKER_BACKOFF_CAP
        )
        old = self.workers[cam_id]
        log.warning("[%s] restarting worker", cam_id)
        try:
            self.workers[cam_id] = CameraWorker(old.cfg, self._inference, state=old.state)
        except Exception:
            log.exception("[%s] worker rebuild failed — retrying in %.0fs",
                          cam_id, self._delay[cam_id])
            self._retry_at[cam_id] = now + self._delay[cam_id]
            return
        self._spawn(cam_id)

    def _monitor(self):
        """Watch worker threads until interrupted; restart any that die, with backoff."""
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            for cam_id, thread in list(self._threads.items()):
                if thread.is_alive():
                    # A worker that stayed up long enough earns a fresh backoff.
                    if now - self._spawned_at[cam_id] >= config.WORKER_STABLE_SECONDS:
                        self._delay[cam_id] = config.WORKER_BACKOFF
                    continue
                if cam_id not in self._retry_at:
                    delay = self._delay.get(cam_id, config.WORKER_BACKOFF)
                    log.warning("[%s] worker died — restarting in %.0fs", cam_id, delay)
                    self.workers[cam_id].stop()  # release the reader right away
                    self._retry_at[cam_id] = now + delay
                elif now >= self._retry_at[cam_id]:
                    self._restart(cam_id, now)

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self):
        """Validate, build shared services, run every camera until interrupted."""
        config.validate()
        cams = load_cameras()

        hub.configure(cams)
        server.start(workers=self.workers)
        log.info("Web view available at http://localhost:5000")
        if not config.ENABLE_SERVER_SOUND:
            log.info("Server-side sound disabled (ENABLE_SERVER_SOUND); using client playback via /sound")

        backend = load_model()
        self._inference = InferenceWorker(backend)
        for cam in cams:
            self.workers[cam.id] = CameraWorker(cam, self._inference)
            log.info("Camera %s (%s). Zone (normalized) = %s | detect %.1f fps | persist %.1fs | conf >= %.2f",
                     cam.id, cam.name, cam.zone_points,
                     cam.detect_fps, cam.persist_seconds, cam.conf_threshold)
        bot.start_bot(self.workers)

        startup_alert()
        for cam_id in self.workers:
            self._spawn(cam_id)
        try:
            self._monitor()
        finally:
            # SIGTERM (SystemExit) / Ctrl-C land here: stop loops, release readers.
            for worker in self.workers.values():
                worker.stop()
            shutdown_alert()
