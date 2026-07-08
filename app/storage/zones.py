"""Persist web-edited detection zones (/data/zones.json, keyed by camera id).

A persisted zone overrides the configured one at startup. A legacy single-camera
/data/zone.json is folded in as "cam_main" on first load. All IO is best-effort:
a corrupt or read-only /data never stops the detector.
"""

import json
import logging
import math
import os

from storage import read_json_dict, write_json_atomic

log = logging.getLogger("detector")

ZONES_FILE = "/data/zones.json"
LEGACY_ZONE_FILE = "/data/zone.json"


def _valid_points(raw):
    """Return normalized (x, y) tuples, or None if malformed."""
    try:
        pts = [(float(x), float(y)) for x, y in raw]
    except (TypeError, ValueError):
        return None
    if not (3 <= len(pts) <= 32) or not all(
        math.isfinite(v) and 0.0 <= v <= 1.0 for xy in pts for v in xy
    ):
        return None
    return pts


def _load_all():
    """Return the id -> points dict, migrating a legacy zone.json on first load."""
    data = read_json_dict(ZONES_FILE)
    if data is not None:
        return data
    if os.path.exists(LEGACY_ZONE_FILE):
        try:
            with open(LEGACY_ZONE_FILE) as f:
                pts = _valid_points(json.load(f))
        except Exception as e:  # noqa: BLE001
            log.warning("Ignoring corrupt %s: %s", LEGACY_ZONE_FILE, e)
            return {}
        if pts is None:
            log.warning("Ignoring corrupt %s: must be 3-32 finite pairs in [0, 1]",
                        LEGACY_ZONE_FILE)
            return {}
        data = {"cam_main": [[x, y] for x, y in pts]}
        log.info("Migrating legacy %s into %s as 'cam_main'", LEGACY_ZONE_FILE, ZONES_FILE)
        write_json_atomic(ZONES_FILE, data, "zones")
        return data
    return {}


def load(cam_id):
    """Return the persisted normalized points for cam_id, or None if absent/corrupt."""
    raw = _load_all().get(cam_id)
    if raw is None:
        return None
    pts = _valid_points(raw)
    if pts is None:
        log.warning("Ignoring corrupt zone for %r in %s", cam_id, ZONES_FILE)
    return pts


def save(cam_id, points):
    """Persist normalized points for cam_id, keeping every other camera's zone."""
    data = _load_all()
    data[cam_id] = [[x, y] for x, y in points]
    write_json_atomic(ZONES_FILE, data, "zones")
