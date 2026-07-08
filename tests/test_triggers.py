"""triggers.fire_triggers / telegram_alert: no-crash regression + per-camera routing.

Guards the multi-camera contract between triggers.py and actions.py: fire_triggers
must accept (cam, state) and every action it composes must accept the camera /
chat_id it is handed. A missing keyword here silently swallows every alert (the
worker's per-iteration guard logs it and moves on), so exercise the real call.
"""

import urllib.parse
from types import SimpleNamespace

import config
from alerts import actions, triggers


def _cam(chat_id=None):
    return SimpleNamespace(id="living_room", name="Living room", telegram_chat_id=chat_id)


def _state(frame=None):
    return SimpleNamespace(latest_frame=frame)


def test_fire_triggers_accepts_cam_and_state_without_raising(monkeypatch):
    """Regression: fire_triggers(cam, state) must run every action, not TypeError."""
    monkeypatch.setattr(config, "ENABLE_TELEGRAM", False)
    monkeypatch.setattr(config, "ENABLE_SERVER_SOUND", False)
    # Run the queued telegram_alert inline so its actions are exercised too.
    monkeypatch.setattr(triggers._net, "submit", lambda fn, *a: fn(*a))
    triggers.fire_triggers(_cam(chat_id="123"), _state())  # must not raise


def test_alert_routes_to_per_camera_chat(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_TELEGRAM", True)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "100")
    sent = {}
    monkeypatch.setattr(actions, "_telegram_post",
                        lambda method, data, headers=None: sent.update(data=data) or 200)
    triggers.telegram_alert(_cam(chat_id="999"), _state())  # no frame -> sendMessage
    q = urllib.parse.parse_qs(sent["data"].decode())
    assert q["chat_id"] == ["999"]
    assert "Living room" in q["text"][0]


def test_alert_falls_back_to_global_chat(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_TELEGRAM", True)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "100")
    sent = {}
    monkeypatch.setattr(actions, "_telegram_post",
                        lambda method, data, headers=None: sent.update(data=data) or 200)
    triggers.telegram_alert(_cam(chat_id=None), _state())
    q = urllib.parse.parse_qs(sent["data"].decode())
    assert q["chat_id"] == ["100"]


def test_sound_alert_forwards_camera(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_SERVER_SOUND", False)
    seen = {}
    monkeypatch.setattr(actions.hub, "set_sound_pending", lambda camera=None: seen.update(camera=camera))
    actions.sound_alert(camera="Living room")
    assert seen["camera"] == "Living room"
