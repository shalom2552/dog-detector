"""Camera configuration: one frozen CameraConfig per video source.

Cameras come from /data/cameras.json when present; without it a single camera is
synthesized from the VIDEO_SOURCE/ZONE_POINTS env config. Validation is hard and
fails fast, naming the offending camera and field.
"""

import json
import math
import os
import re
from dataclasses import dataclass, replace
from typing import Optional

import config
from storage import zones

CAMERAS_FILE = "/data/cameras.json"

_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")
# Overridable via the "defaults" block or per camera; anything else stays global (env).
_TUNABLE_KEYS = (
    "detect_fps", "conf_threshold", "persist_seconds",
    "cooldown_seconds", "motion_threshold", "zone_min_overlap",
)
_CAMERA_KEYS = set(_TUNABLE_KEYS) | {"id", "name", "source", "zone", "telegram_chat_id"}


@dataclass(frozen=True)
class CameraConfig:
    id: str
    name: str
    source: object            # int webcam index, file path, or URL
    zone_points: tuple        # normalized ((x, y), ...) pairs
    detect_fps: float
    conf_threshold: float
    persist_seconds: float
    cooldown_seconds: float
    motion_threshold: int
    zone_min_overlap: float
    telegram_chat_id: Optional[str] = None  # None = global TELEGRAM_CHAT_ID


# ── Field validators ─────────────────────────────────────────────────────────
# Each returns the normalized value or raises ValueError naming the field.


def _check_source(raw):
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str) or not raw:
        raise ValueError("source must be a non-empty string or integer index")
    return int(raw) if raw.isdigit() else raw


def _check_zone(raw):
    if not isinstance(raw, list) or not (3 <= len(raw) <= 32):
        raise ValueError("zone must be a list of 3-32 [x, y] pairs")
    pts = []
    for p in raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError("each zone point must be a 2-item [x, y]")
        x, y = float(p[0]), float(p[1])
        if not (math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("zone coordinates must be finite and in [0, 1]")
        pts.append((x, y))
    return tuple(pts)


def _check_chat_id(raw):
    try:
        int(str(raw))
    except ValueError:
        raise ValueError(f"telegram_chat_id must be numeric (got {raw!r})")
    return str(raw)


def _check_tunable(key, raw):
    """Validate a per-camera tunable; same ranges as config.validate()."""
    try:
        val = int(raw) if key == "motion_threshold" else float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number (got {raw!r})")
    ok = {
        "detect_fps":       val > 0,
        "conf_threshold":   0.0 <= val <= 1.0,
        "persist_seconds":  val >= 0,
        "cooldown_seconds": val >= 0,
        "motion_threshold": val >= 0,
        "zone_min_overlap": 0.0 < val <= 1.0,
    }[key]
    if not ok:
        raise ValueError(f"{key} is out of range (got {raw!r})")
    return val


# ── Loading ──────────────────────────────────────────────────────────────────


def _env_tunables():
    """Global env config as the base layer of the defaults chain."""
    return {
        "detect_fps":       config.DETECT_FPS,
        "conf_threshold":   config.CONF_THRESHOLD,
        "persist_seconds":  config.PERSIST_SECONDS,
        "cooldown_seconds": config.COOLDOWN_SECONDS,
        "motion_threshold": config.MOTION_THRESHOLD,
        "zone_min_overlap": config.ZONE_MIN_OVERLAP,
    }


def _synthesize():
    """Single camera from env config — the no-cameras.json compatibility path."""
    return CameraConfig(
        id="cam_main",
        name="Main Camera",
        source=config.VIDEO_SOURCE,
        zone_points=tuple(tuple(p) for p in config.ZONE),
        **_env_tunables(),
    )


def _parse_camera(entry, index, defaults, errors):
    """Return a CameraConfig for one cameras.json entry, or None (errors appended)."""
    if not isinstance(entry, dict):
        errors.append(f"cameras[{index}]: must be an object")
        return None
    cam_id = entry.get("id")
    label = repr(cam_id) if isinstance(cam_id, str) and cam_id else f"cameras[{index}]"
    if not (isinstance(cam_id, str) and _ID_RE.match(cam_id)):
        errors.append(f"{label}: id must match [a-z0-9_]{{1,32}}")
        return None
    for key in sorted(set(entry) - _CAMERA_KEYS):
        errors.append(f"{label}: unknown key {key!r}")

    fields = dict(defaults)
    ok = True
    try:
        if "source" not in entry:
            raise ValueError("source is required")
        fields["source"] = _check_source(entry["source"])
        fields["zone_points"] = (
            _check_zone(entry["zone"]) if "zone" in entry
            else tuple(tuple(p) for p in config.ZONE)
        )
        if entry.get("telegram_chat_id") is not None:
            fields["telegram_chat_id"] = _check_chat_id(entry["telegram_chat_id"])
        for key in _TUNABLE_KEYS:
            if key in entry:
                fields[key] = _check_tunable(key, entry[key])
    except ValueError as e:
        errors.append(f"{label}: {e}")
        ok = False

    name = entry.get("name", cam_id)
    if not isinstance(name, str) or not name:
        errors.append(f"{label}: name must be a non-empty string")
        ok = False
    if not ok:
        return None
    return CameraConfig(id=cam_id, name=name, **fields)


def _apply_saved_zones(cams):
    """Web-edited zones override configured ones — latest user intent wins."""
    return [
        replace(cam, zone_points=tuple(saved)) if (saved := zones.load(cam.id))
        else cam
        for cam in cams
    ]


def load_cameras(path=None):
    """Return the configured cameras, validated hard.

    No cameras.json → one camera synthesized from env config. A malformed file
    raises ValueError listing every offending camera id and field. Web-persisted
    zones override the configured zone per camera.
    """
    if path is None:  # late-bound so tests can point CAMERAS_FILE elsewhere
        path = CAMERAS_FILE
    if not os.path.exists(path):
        return _apply_saved_zones([_synthesize()])

    try:
        with open(path) as f:
            data = json.load(f)
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")

    errors = []
    for key in sorted(set(data) - {"defaults", "cameras"}):
        errors.append(f"unknown top-level key {key!r}")

    defaults = _env_tunables()
    defaults_raw = data.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        errors.append("defaults must be an object")
    else:
        for key, raw in defaults_raw.items():
            if key not in _TUNABLE_KEYS:
                errors.append(f"defaults: unknown key {key!r}")
                continue
            try:
                defaults[key] = _check_tunable(key, raw)
            except ValueError as e:
                errors.append(f"defaults: {e}")

    entries = data.get("cameras")
    if not isinstance(entries, list) or not entries:
        errors.append("cameras must be a non-empty list")
        entries = []

    cams, seen = [], set()
    for i, entry in enumerate(entries):
        cam = _parse_camera(entry, i, defaults, errors)
        if cam is None:
            continue
        if cam.id in seen:
            errors.append(f"{cam.id!r}: duplicate camera id")
            continue
        seen.add(cam.id)
        cams.append(cam)

    if errors:
        raise ValueError(f"Invalid {path}:\n  - " + "\n  - ".join(errors))
    return _apply_saved_zones(cams)
