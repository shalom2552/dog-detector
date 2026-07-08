"""Localized strings for alerts and the Telegram bot."""

MESSAGES = {
    # triggers
    "dog_alert_cam":    "🔴 <b>Dog detected in the zone!</b>\n📹 Camera: <i>{camera}</i>",
    "startup":          "🟢 <b>Dog detector is running</b>",
    "shutdown":         "🔴 <b>Dog detector stopped</b>",
    # bot
    "unknown_camera":   "❌ <b>Unknown camera</b>\nAvailable options: <code>{ids}</code>",
}


def msg(key, **fmt):
    """Return key's message.

    Keyword args fill {placeholders} (e.g. camera=... for dog_alert_cam).
    """
    text = MESSAGES[key]
    return text.format(**fmt) if fmt else text
