"""All tunables in one place. Override any with environment variables (see .env.example).

The zone matters most: a polygon in NORMALIZED coords (0..1) over the frame,
(0,0) top-left, (1,1) bottom-right.
"""

import logging
import math
import os

from storage import settings

# --- env parsers ------------------------------------------------------------

def _f(name, default):
    return float(os.environ.get(name, default))


def _i(name, default):
    return int(os.environ.get(name, default))


def _b(name, default):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


# --- video source -----------------------------------------------------------
# Webcam index (0, 1, ...) or a file path / RTSP URL.
_src = os.environ.get("VIDEO_SOURCE", "0")
VIDEO_SOURCE = int(_src) if _src.isdigit() else _src

DETECT_FPS = _f("DETECT_FPS", 3.0)   # YOLO inference rate; persistence is time-based
STREAM_FPS = _f("STREAM_FPS", 10.0)  # web JPEG push rate, independent of detection

# --- model ------------------------------------------------------------------
# .pt auto-downloads then exports to ONNX (x86) / NCNN (Pi) on first run.
MODEL = os.environ.get("MODEL", "yolo11n.pt")
CONF_THRESHOLD = _f("CONF_THRESHOLD", 0.35)
IMGSZ = _i("IMGSZ", 320)

# --- detection zone (normalized 0..1, flat x,y pairs defining a polygon) ---
def _parse_zone(raw):
    vals = [float(v) for v in raw.replace(" ", "").split(",")]
    if len(vals) % 2 != 0 or len(vals) < 6:
        raise ValueError(f"ZONE_POINTS must be at least 3 x,y pairs (got {len(vals)} values): {raw!r}")
    if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in vals):
        raise ValueError(f"ZONE_POINTS must be finite and in [0, 1]: {raw!r}")
    return [(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]

ZONE = _parse_zone(os.environ.get("ZONE_POINTS", "0.25,0.35, 0.85,0.35, 0.85,0.95, 0.25,0.95"))
# Web-edited zones (storage.zones) override this per camera in core.cameras.load_cameras().

# --- false-positive suppression ---------------------------------------------
PERSIST_SECONDS  = _f("PERSIST_SECONDS",  3.0)   # dog must stay in zone this long
COOLDOWN_SECONDS = _f("COOLDOWN_SECONDS", 30.0)  # min gap between alerts

# --- motion gate (Pi performance) -------------------------------------------
# Changed-pixel count (over a 64x64 zone crop) needed to run YOLO. 0 disables the
# gate; ~30 very sensitive; 100 default; 500 coarse; 4096 max (disables YOLO).
MOTION_THRESHOLD = _i("MOTION_THRESHOLD", 100)
# Run inference at least this often regardless of the gate (slow/stationary dog).
MOTION_HEARTBEAT_SECONDS = _f("MOTION_HEARTBEAT_SECONDS", 10.0)

# --- zone membership --------------------------------------------------------
# Fraction of a detection box that must fall inside the zone to count as "in zone".
ZONE_MIN_OVERLAP = _f("ZONE_MIN_OVERLAP", 0.6)

# --- web auth ---------------------------------------------------------------
# HTTP Basic Auth over the public Cloudflare tunnel. Both users share one
# credential. Defaults empty so an unconfigured deployment fails in validate().
APP_USER     = os.environ.get("APP_USER", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# --- triggers ---------------------------------------------------------------
# Server-side mpg123 playback is off by default (container has no audio device);
# client playback via the launcher's /sound poll is what works.
ENABLE_SERVER_SOUND = _b("ENABLE_SERVER_SOUND", False)
ENABLE_TELEGRAM  = _b("ENABLE_TELEGRAM", False)
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")



# --- internal constants (not env-tunable) -----------------------------------
SOUND_PATH            = "/data/sound.mp3"  # server-side playback file
WEB_HOST              = "0.0.0.0"
WEB_PORT              = 5000
JPEG_STREAM_QUALITY   = 70   # web MJPEG frames (smaller, fast)
JPEG_SNAPSHOT_QUALITY = 95   # Telegram /snapshot (sharper)
# Absence shorter than this is forgiven before resetting the persistence timer;
# also the floor for treating a detection box as stale.
ABSENCE_GRACE         = 2.0
MOTION_CROP           = 64   # zone crop downscaled to NxN before diffing
MOTION_DIFF_THRESHOLD = 20   # per-pixel intensity delta counted as "changed"
MOTION_BG_ALPHA       = 0.05 # EMA weight folding each frame into the motion background
NMS_IOU               = 0.45 # IoU threshold for non-max suppression (ONNX backend)
ONNX_NUM_THREADS      = 4    # ONNX Runtime intra-op threads; >4 adds sync cost, not speed, at this imgsz
# Dead-worker restart backoff: first retry after WORKER_BACKOFF, doubling up to
# WORKER_BACKOFF_CAP; reset once alive for WORKER_STABLE_SECONDS.
WORKER_BACKOFF        = 5.0
WORKER_BACKOFF_CAP    = 60.0
WORKER_STABLE_SECONDS = 120.0


def validate():
    """Fail fast on out-of-range config. Call once at startup, before opening anything."""
    errors = []
    if not APP_USER or not APP_PASSWORD:
        errors.append("APP_USER and APP_PASSWORD must be set (see .env.example)")
    elif APP_USER == "admin" and APP_PASSWORD == "admin":
        logging.getLogger("detector").warning(
            "APP_USER/APP_PASSWORD are still the 'admin/admin' placeholders — "
            "set real credentials in .env before exposing this publicly")
    if DETECT_FPS <= 0:
        errors.append(f"DETECT_FPS must be > 0 (got {DETECT_FPS})")
    if STREAM_FPS <= 0:
        errors.append(f"STREAM_FPS must be > 0 (got {STREAM_FPS})")
    if not 0.0 <= CONF_THRESHOLD <= 1.0:
        errors.append(f"CONF_THRESHOLD must be in [0, 1] (got {CONF_THRESHOLD})")
    if IMGSZ <= 0 or IMGSZ % 32 != 0:
        errors.append(f"IMGSZ must be a positive multiple of 32 (got {IMGSZ})")
    if PERSIST_SECONDS < 0:
        errors.append(f"PERSIST_SECONDS must be >= 0 (got {PERSIST_SECONDS})")
    if COOLDOWN_SECONDS < 0:
        errors.append(f"COOLDOWN_SECONDS must be >= 0 (got {COOLDOWN_SECONDS})")
    if MOTION_THRESHOLD < 0:
        errors.append(f"MOTION_THRESHOLD must be >= 0 (got {MOTION_THRESHOLD})")
    if MOTION_HEARTBEAT_SECONDS <= 0:
        errors.append(f"MOTION_HEARTBEAT_SECONDS must be > 0 (got {MOTION_HEARTBEAT_SECONDS})")
    if not 0.0 < ZONE_MIN_OVERLAP <= 1.0:
        errors.append(f"ZONE_MIN_OVERLAP must be in (0, 1] (got {ZONE_MIN_OVERLAP})")

    if ENABLE_TELEGRAM:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            errors.append("ENABLE_TELEGRAM is set but TELEGRAM_TOKEN/TELEGRAM_CHAT_ID is missing")
        else:
            try:
                int(TELEGRAM_CHAT_ID)
            except ValueError:
                errors.append(f"TELEGRAM_CHAT_ID must be numeric (got {TELEGRAM_CHAT_ID!r})")
    from core.cameras import load_cameras  # lazy: cameras imports config
    try:
        load_cameras()
    except ValueError as e:
        errors.append(str(e))
    if errors:
        raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(errors))
