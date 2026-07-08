"""Triggers fire when a dog is CONFIRMED in the zone.

Each trigger stays small and composes actions from actions.py.
"""

import concurrent.futures
import logging

from alerts import actions, i18n

log = logging.getLogger("triggers")

# Network sends run here, off the detection hot path. A single worker preserves
# ordering; the trigger cooldown keeps the queue from growing.
_net = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="trigger-net")


def console_alert(cam):
    log.info("🐶 DOG IN ZONE (console trigger) [%s]", cam.name)


def telegram_alert(cam, state=None):
    """Camera-labeled alert: snapshot photo with the alert text as caption (plain text if no frame).

    Routed to the camera's telegram_chat_id when set.
    """
    text = i18n.msg("dog_alert_cam", camera=cam.name)
    jpg = actions.latest_jpeg(state)
    if jpg is None:
        actions.telegram_send(text, chat_id=cam.telegram_chat_id)
    else:
        actions.telegram_send_photo(jpg, text, chat_id=cam.telegram_chat_id)


def startup_alert():
    # Off the main thread so an offline Telegram (10s timeout) can't delay startup.
    _net.submit(lambda: actions.telegram_send(i18n.msg("startup")))


def shutdown_alert():
    # Synchronous: runs in main()'s finally, where the daemon executor may not flush.
    actions.telegram_send(i18n.msg("shutdown"))


def fire_triggers(cam, state=None):
    console_alert(cam)
    actions.sound_alert(camera=cam.name)      # non-blocking (Popen)
    _net.submit(telegram_alert, cam, state)   # JPEG encode + network leave the hot path
