"""Reusable alert actions: snapshot encoding, Telegram sends, sound playback.

One shared implementation for both the fire triggers (triggers.py) and the bot
command handlers (bot/commands.py). Composition (what to send when) is the
caller's job.
"""

import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

import cv2

import config
from web import hub

log = logging.getLogger("actions")


# ── Snapshot ────────────────────────────────────────────────────────────────


def latest_jpeg(state):
    """Return state.latest_frame as JPEG bytes, or None when no frame exists yet."""
    frame = state.latest_frame if state else None
    if frame is None:
        return None
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_SNAPSHOT_QUALITY])
    return jpg.tobytes() if ok else None


# ── Telegram ────────────────────────────────────────────────────────────────


def _telegram_ready():
    if not config.ENABLE_TELEGRAM:
        return False
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram enabled but token/chat_id missing")
        return False
    return True


def _telegram_post(method, data, headers=None):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}"
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def _retry_delay(err):
    """Wait suggested by a flood-control response (Retry-After), bounded; else the default."""
    try:
        return min(float(err.headers.get("Retry-After", config.TELEGRAM_RETRY_DELAY)),
                   config.TELEGRAM_RETRY_MAX)
    except (TypeError, ValueError):
        return config.TELEGRAM_RETRY_DELAY


def _post_with_retry(method, data, headers=None):
    """POST with bounded retries for transient failures (timeouts, 5xx, flood control).

    Other client errors (4xx) are permanent — re-raised immediately so callers
    can fall back instead of thrashing the API.
    """
    for attempt in range(1, config.TELEGRAM_SEND_ATTEMPTS + 1):
        try:
            return _telegram_post(method, data, headers)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or attempt == config.TELEGRAM_SEND_ATTEMPTS:
                raise
            delay = _retry_delay(e) if e.code == 429 else config.TELEGRAM_RETRY_DELAY
            log.warning("Telegram %s got HTTP %s — retrying in %.0fs", method, e.code, delay)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == config.TELEGRAM_SEND_ATTEMPTS:
                raise
            delay = config.TELEGRAM_RETRY_DELAY
            log.warning("Telegram %s failed (%s) — retrying in %.0fs", method, e, delay)
        time.sleep(delay)


def telegram_send(text, chat_id=None):
    """Send a message to chat_id (default: the global chat) with HTML formatting."""
    if not _telegram_ready():
        return
    payload = {
        "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    data = urllib.parse.urlencode(payload).encode()
    try:
        status = _post_with_retry("sendMessage", data)
        if status == 200:
            log.info("Telegram sent: %s", text)
        else:
            log.warning("Telegram returned status %s", status)
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram send failed: %s", e)


def telegram_send_photo(jpg_bytes, caption=None, chat_id=None):
    """Send a JPEG photo (optional HTML caption) to chat_id (default: the global chat).

    If the photo is rejected outright, the caption still goes out as a plain
    message — a degraded alert beats a silently dropped one.
    """
    if not _telegram_ready():
        return
    fields = {
        "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
        "parse_mode": "HTML"
    }
    if caption:
        fields["caption"] = caption
    body, content_type = _multipart(fields, "photo", "snapshot.jpg", jpg_bytes)
    try:
        status = _post_with_retry("sendPhoto", body, {"Content-Type": content_type})
        if status == 200:
            log.info("Telegram photo sent (%d bytes): %s", len(jpg_bytes), caption)
        else:
            log.warning("Telegram returned status %s", status)
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram photo send failed: %s", e)
        if caption:
            log.info("Falling back to text-only alert")
            telegram_send(caption, chat_id=chat_id)


def _multipart(fields, file_field, filename, file_bytes):
    """Encode form fields plus one JPEG as multipart/form-data (stdlib has no helper)."""
    boundary = uuid.uuid4().hex
    lines = []
    for name, value in fields.items():
        lines += [f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", str(value)]
    lines += [f"--{boundary}",
              f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"',
              "Content-Type: image/jpeg", ""]
    body = "\r\n".join(lines).encode() + b"\r\n" + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


# ── Sound ───────────────────────────────────────────────────────────────────

_sound_procs: list = []  # spawned mpg123 processes, reaped when finished (no zombies)


def sound_alert(path=config.SOUND_PATH, camera=None):
    """Queue client-side playback and, if enabled, play the file on the server."""
    hub.set_sound_pending(camera)  # client-side playback (launcher polls /sound)
    if not config.ENABLE_SERVER_SOUND:
        return
    if not os.path.exists(path):
        log.warning("sound_alert: file not found: %s", path)
        return
    _sound_procs[:] = [p for p in _sound_procs if p.poll() is None]  # reap finished
    try:
        _sound_procs.append(subprocess.Popen(["mpg123", "-q", path]))
        log.info("sound_alert: playing %s", path)
    except FileNotFoundError:
        log.warning("sound_alert: mpg123 not installed; skipping server playback")
    except OSError as e:
        log.warning("sound_alert: playback failed: %s", e)
