"""Presentation helpers: duration formatting and the /status text. Pure functions."""

import time


def hms(secs: int) -> str:
    """Whole-second duration → human string (Xs / Xm Ys / Xh Ym)."""
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def ago(ts: float) -> str:
    """Relative time string, timezone-independent."""
    diff = time.time() - ts
    if diff < 1:
        return f"{diff:.1f}s ago"
    return f"{hms(int(diff))} ago"


def _camera_block(worker, cam_snap) -> str:
    """One camera's status lines from its worker state + /state snapshot entry."""
    state = worker.state
    mono = time.monotonic()

    name = worker.cfg.name
    status_str = "Active 🟢" if not state.paused else "Paused ⏸"

    frame_age = cam_snap.get("frame_age")
    if frame_age is not None and frame_age < 3:
        header_info = status_str
    else:
        feed_str = f"⚠️ No signal ({int(frame_age)}s ago)" if frame_age is not None else "⚠️ No signal"
        header_info = f"{status_str} | {feed_str}"

    if cam_snap.get("dog_in_zone"):
        if state.in_zone_since:
            dur = hms(int(mono - state.in_zone_since))
            presence_str = f"<b>Dog IN zone</b> (for {dur}) 🐶"
        else:
            presence_str = "<b>Dog IN zone</b> 🐶"
    else:
        presence_str = "No dog detected 📭"

    last_fire = state.last_fire_wall
    alert_str = f"{ago(last_fire)}" if last_fire > 0 else "never ⏰"

    return (
        f"<b>📹 {name}</b>\n"
        f"├─ <b>ID:</b> <code>{worker.cfg.id}</code>\n"
        f"├─ <b>Status:</b> {header_info}\n"
        f"├─ <b>Presence:</b> {presence_str}\n"
        f"└─ <b>Last Alert:</b> {alert_str}"
    )


def format_status(cameras, snap) -> str:
    """Build the /status reply: one block per camera."""
    cam_snaps = snap.get("cameras", {})
    blocks = [
        _camera_block(worker, cam_snaps.get(cam_id, {}))
        for cam_id, worker in cameras.items()
    ]
    return "\n\n".join(blocks)
