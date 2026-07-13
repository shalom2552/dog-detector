"""Telegram command handlers and the command registry.

Add a command: write an async handler, then add a row to COMMAND_REGISTRY.
Handlers stay thin — log, act, reply; presentation lives in view.py, shared
state in context.py. Camera-scoped commands take an optional camera id (always
omittable with a single camera).
"""

import io
import logging
import os

from telegram import Update, InputFile
from telegram.ext import ContextTypes

import config
from alerts import actions, i18n
from pipeline import persistence
from storage import settings
from alerts.bot import context, view
from web import hub

log = logging.getLogger("bot")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _who(update: Update) -> str:
    u = update.effective_user
    return f"{u.full_name} (id={u.id})" if u else "unknown"


def _ids() -> str:
    return ", ".join(context.cameras)


async def _resolve_workers(update, ctx):
    """CameraWorkers for the command's optional id arg. No arg → every camera; unknown → []."""
    arg = ctx.args[0] if ctx.args else None
    if arg is None:
        return list(context.cameras.values())
    worker = context.cameras.get(arg)
    if worker is None:
        await update.message.reply_html(i18n.msg("unknown_camera", ids=_ids()))
        return []
    return [worker]


# ── Command handlers ────────────────────────────────────────────────────────


async def _cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /status from %s", _who(update))
    text = view.format_status(context.cameras, hub.get_state())
    log.info("[bot] /status reply sent")
    await update.message.reply_html(text)

async def _cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /help from %s", _who(update))
    help_lines = [
        "<b>📖 Available Commands</b>",
        "───────────────────"
    ]
    emojis = {
        "status": "📊",
        "help": "ℹ️",
        "pause": "⏸",
        "resume": "▶️",
        "snapshot": "📸",
        "sound": "🔊"
    }
    for name, _, desc in COMMAND_REGISTRY:
        emoji = emojis.get(name, "🔹")
        help_lines.append(f"{emoji} /{name} — {desc}")
    await update.message.reply_html("\n".join(help_lines))


async def _cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /pause %s from %s", ctx.args or "", _who(update))
    workers = await _resolve_workers(update, ctx)
    if not workers:
        return
    for worker in workers:
        worker.state.paused = True
        persistence.reset(worker.state)  # drop accumulation so resume starts fresh
    names = ", ".join([f"<i>{w.cfg.name}</i>" for w in workers])
    log.info("[bot] Detection paused: %s", [w.cfg.id for w in workers])
    await update.message.reply_html(f"⏸ <b>Detection paused</b> for: {names}")


async def _cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /resume %s from %s", ctx.args or "", _who(update))
    workers = await _resolve_workers(update, ctx)
    if not workers:
        return
    for worker in workers:
        worker.state.paused = False
    names = ", ".join([f"<i>{w.cfg.name}</i>" for w in workers])
    log.info("[bot] Detection resumed: %s", [w.cfg.id for w in workers])
    await update.message.reply_html(f"▶️ <b>Detection resumed</b> for: {names}")


async def _cmd_snapshot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /snapshot %s from %s", ctx.args or "", _who(update))
    for worker in await _resolve_workers(update, ctx):
        jpg_bytes = actions.latest_jpeg(worker.state)
        if jpg_bytes is None:
            log.warning("[bot] /snapshot: no frame available for %s", worker.cfg.id)
            await update.message.reply_html(f"⚠️ <b>No frame from {worker.cfg.name} yet.</b>")
            continue
        log.info("[bot] /snapshot: sending %d bytes for %s", len(jpg_bytes), worker.cfg.id)
        caption = f"📹 <b>{worker.cfg.name}</b>"
        if worker.state.paused:
            caption += " <i>(Paused ⏸)</i>"
        await update.message.reply_photo(
            InputFile(io.BytesIO(jpg_bytes), filename="snapshot.jpg"), caption=caption, parse_mode="HTML")


async def _cmd_sound(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("[bot] /sound from %s", _who(update))
    path = config.SOUND_PATH
    if not os.path.exists(path):
        log.warning("[bot] /sound: %s not found", path)
        await update.message.reply_html("❌ <b>Sound file not found on server</b>")
        return
    actions.sound_alert(path)
    await update.message.reply_html("🔊 <b>Playing alert sound on server...</b>")


# ── Registry ────────────────────────────────────────────────────────────────
# (name, handler, description)
COMMAND_REGISTRY = [
    ("status",   _cmd_status,   "Show status"),
    ("help",     _cmd_help,     "Show help"),
    ("pause",    _cmd_pause,    "Pause [camera]"),
    ("resume",   _cmd_resume,   "Resume [camera]"),
    ("snapshot", _cmd_snapshot, "Send frame [camera]"),
    ("sound",    _cmd_sound,    "Play server sound"),
]
