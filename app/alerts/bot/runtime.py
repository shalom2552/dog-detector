"""Telegram bot runtime: build the PTB application and run polling in a daemon thread.

Polling is supervised: a fatal error (network outage at startup, a crashed event
loop, a bad upstream response) tears the application down and rebuilds it from
scratch after an exponential backoff, so the bot always comes back once Telegram
is reachable again.
"""

import logging
import threading
import time
import traceback

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, filters

import config
from alerts.bot import context
from alerts.bot.commands import COMMAND_REGISTRY

log = logging.getLogger("bot")


async def _post_init(app):
    # Menu registration is cosmetic — never let a transient failure here kill polling.
    try:
        await app.bot.set_my_commands([
            BotCommand(name, desc) for name, _, desc in COMMAND_REGISTRY
        ])
        log.info("[bot] Bot commands registered: %s", [n for n, _, _ in COMMAND_REGISTRY])
    except Exception as e:  # noqa: BLE001
        log.warning("[bot] Command registration failed (menu only, commands still work): %s", e)


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("[bot] Unhandled exception in handler: %s", ctx.error)
    if ctx.error is not None:
        log.error("[bot] %s", "".join(traceback.format_exception(ctx.error)))


def _poll():
    """Build a fresh application and poll until it stops (raises on fatal errors)."""
    chat_filter = filters.Chat(chat_id=int(config.TELEGRAM_CHAT_ID))
    log.info("[bot] Chat filter set to chat_id=%s", config.TELEGRAM_CHAT_ID)
    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(_post_init)
        .build()
    )
    for name, handler, _ in COMMAND_REGISTRY:
        app.add_handler(CommandHandler(name, handler, filters=chat_filter))
        log.debug("[bot] Registered handler: /%s", name)
    app.add_error_handler(_error_handler)
    log.info("[bot] Starting polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


def _run():
    """Supervise polling forever: rebuild loop + application after any crash, with backoff."""
    import asyncio
    delay = config.WORKER_BACKOFF
    while True:
        started = time.monotonic()
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            _poll()
            return  # run_polling returned: explicit stop, don't respawn
        except Exception:
            log.exception("[bot] Polling crashed — restarting in %.0fs", delay)
        if time.monotonic() - started >= config.WORKER_STABLE_SECONDS:
            delay = config.WORKER_BACKOFF  # a stable run earns a fresh backoff
        time.sleep(delay)
        delay = min(delay * 2, config.WORKER_BACKOFF_CAP)


def start_bot(cameras):
    """Start the Telegram bot in a daemon thread. No-op if Telegram is disabled.

    `cameras` is the live id -> CameraWorker registry (the supervisor's dict, so
    worker restarts stay visible to command handlers).
    """
    if not config.ENABLE_TELEGRAM:
        log.debug("[bot] Telegram disabled — bot not started")
        return
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("[bot] Bot not started: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing")
        return
    context.cameras = cameras
    threading.Thread(target=_run, name="telegram-bot", daemon=True).start()
    log.info("[bot] Telegram bot polling started")
