"""Telegram command bot package. Public entry point: start_bot()."""

import logging

import config

__all__ = ["start_bot"]


def start_bot(cameras):
    """Start the Telegram bot in a daemon thread. No-op if Telegram is disabled.

    Imports the python-telegram-bot stack (~25 MB RSS, ~120 ms) only when the
    bot is enabled, so disabled deployments never pay for it.
    """
    if not config.ENABLE_TELEGRAM:
        logging.getLogger("bot").debug("[bot] Telegram disabled — bot not started")
        return
    from alerts.bot.runtime import start_bot as _start_bot
    return _start_bot(cameras)
