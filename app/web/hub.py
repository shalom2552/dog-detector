"""Per-camera frame/state hub shared by the camera workers and the web server.

Each CameraWorker calls update(cam_id, frame, **kwargs) every frame; metadata
kwargs surface in that camera's state entry. configure() registers cameras once
at startup. All access is lock-guarded; JPEGs are encoded only while a /video
viewer is attached.
"""

import threading
import time

import cv2

import config

_lock = threading.Lock()
_cond = threading.Condition(_lock)  # signals every /video client on any new JPEG
_boot_time = time.time()
_INTERNAL_KEYS = {"frame_jpg", "frame_raw", "viewers"}
_registry: dict = {}       # cam_id -> display name, insertion-ordered (configure())
_cams: dict = {}           # cam_id -> per-camera state dict
_pending_zones: dict = {}  # cam_id -> web-submitted normalized points

_sound_lock = threading.Lock()
_sound_pending = False
_sound_camera = None


def _new_entry():
    return {
        "frame_jpg": None,
        "frame_raw": None,
        "frame_at": 0.0,
        "viewers": 0,          # active /video streams; 0 = skip encoding
        "dog_in_zone": False,
        "last_trigger": None,
    }


def configure(cameras):
    """Register the cameras (objects with .id and .name) before serving."""
    with _lock:
        _registry.clear()
        for cam in cameras:
            _registry[cam.id] = cam.name
            _cams.setdefault(cam.id, _new_entry())


def has_camera(cam_id):
    with _lock:
        return cam_id in _registry


def default_cam_id():
    """First registered camera — target of the legacy unparameterized routes."""
    with _lock:
        return next(iter(_registry), None)


def camera_names():
    """[(cam_id, display name), ...] in registration order."""
    with _lock:
        return list(_registry.items())


# ── Sound flag (launcher polls /sound) ──────────────────────────────────────


def set_sound_pending(camera=None):
    global _sound_pending, _sound_camera
    with _sound_lock:
        _sound_pending = True
        _sound_camera = camera


def pop_sound():
    """Return-and-clear (pending, camera)."""
    global _sound_pending, _sound_camera
    with _sound_lock:
        pending, camera = _sound_pending, _sound_camera
        _sound_pending, _sound_camera = False, None
    return pending, camera


# ── State snapshots ──────────────────────────────────────────────────────────


def _public(entry, now):
    """One camera's public state; ages computed server-side (clients never see raw timestamps)."""
    out = {k: v for k, v in entry.items() if k not in _INTERNAL_KEYS}
    out["frame_age"] = now - out["frame_at"] if out["frame_at"] > 0 else None
    out["last_trigger_age"] = now - out["last_trigger"] if out.get("last_trigger") else None
    return out


def get_state():
    """Aggregate snapshot: {cameras: {id: {...}}, boot_time}.

    While exactly one camera exists, its fields are merged top-level too, so
    pre-multi-camera clients keep working.
    """
    with _lock:
        snapshot = {cam_id: dict(entry) for cam_id, entry in _cams.items()}
        names = dict(_registry)
    now = time.time()
    cams_out = {}
    for cam_id, entry in snapshot.items():
        pub = _public(entry, now)
        pub["name"] = names.get(cam_id, cam_id)
        cams_out[cam_id] = pub
    out = {
        "cameras": cams_out,
        "boot_time": _boot_time,
        "imgsz": config.IMGSZ,
        "stream_fps": config.STREAM_FPS,
    }
    if len(cams_out) == 1:
        for k, v in next(iter(cams_out.values())).items():
            out.setdefault(k, v)
    return out


def get_camera_state(cam_id):
    """One camera's public state dict (with name), or None if unknown."""
    with _lock:
        if cam_id not in _registry:
            return None
        entry = dict(_cams[cam_id])
        name = _registry[cam_id]
    pub = _public(entry, time.time())
    pub["name"] = name
    return pub


def frame_stamps():
    """{cam_id: frame_at} snapshot for freshness checks (/healthz)."""
    with _lock:
        return {cam_id: entry["frame_at"] for cam_id, entry in _cams.items()}


# ── Zone updates (web UI -> worker) ─────────────────────────────────────────


def push_zone_update(cam_id, points):
    with _lock:
        _pending_zones[cam_id] = points


def pop_zone_update(cam_id):
    """Atomically return-and-clear web-submitted zone points for cam_id, or None."""
    with _lock:
        return _pending_zones.pop(cam_id, None)


# ── Frames ──────────────────────────────────────────────────────────────────


def _encode_locked(entry):
    _, jpg = cv2.imencode(
        ".jpg", entry["frame_raw"], [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_STREAM_QUALITY]
    )
    entry["frame_jpg"] = jpg.tobytes()


def update(cam_id, frame_bgr, **kwargs):
    """Store a camera's latest frame + metadata; encode a JPEG only while someone watches."""
    with _cond:
        entry = _cams.setdefault(cam_id, _new_entry())
        entry["frame_raw"] = frame_bgr
        entry["frame_at"] = time.time()
        entry.update(kwargs)
        if entry["viewers"] > 0:
            _encode_locked(entry)
            _cond.notify_all()


def mjpeg_frames(cam_id):
    """Yield multipart JPEG chunks for cam_id as new frames arrive (blocks between frames)."""
    with _cond:
        entry = _cams[cam_id]
        entry["viewers"] += 1
        if entry["frame_raw"] is not None:  # encode now so a new viewer isn't blank
            _encode_locked(entry)
    try:
        last = None
        while True:
            with _cond:
                while entry["frame_jpg"] is last:
                    _cond.wait(timeout=1)
                jpg = entry["frame_jpg"]
                last = jpg
            if jpg is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
    finally:
        with _cond:
            entry["viewers"] -= 1
