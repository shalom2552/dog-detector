"""Self-healing guarantees: Telegram send retries/fallback, guarded trigger queue,
and bot polling supervision.

These paths only matter when dependencies misbehave, so each test simulates the
failure (5xx, flood control, permanent 4xx, a crashing poll loop) and asserts the
service degrades gracefully instead of dropping alerts or dying.
"""

import email.message
import io
import urllib.error
from types import SimpleNamespace

import pytest

import config
from alerts import actions, triggers


def _http_error(code, headers=None):
    hdrs = email.message.Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError("url", code, "err", hdrs, io.BytesIO())


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_RETRY_DELAY", 0.0)
    monkeypatch.setattr(actions.time, "sleep", lambda s: None)


# ── _post_with_retry ─────────────────────────────────────────────────────────


def test_retries_transient_5xx_then_succeeds(monkeypatch):
    calls = []
    def post(method, data, headers=None):
        calls.append(method)
        if len(calls) < 3:
            raise _http_error(502)
        return 200
    monkeypatch.setattr(actions, "_telegram_post", post)
    assert actions._post_with_retry("sendMessage", b"") == 200
    assert len(calls) == 3


def test_retries_flood_control_with_retry_after(monkeypatch):
    calls = []
    def post(method, data, headers=None):
        calls.append(method)
        if len(calls) == 1:
            raise _http_error(429, {"Retry-After": "0"})
        return 200
    monkeypatch.setattr(actions, "_telegram_post", post)
    assert actions._post_with_retry("sendMessage", b"") == 200
    assert len(calls) == 2


def test_permanent_4xx_raises_without_retry(monkeypatch):
    calls = []
    def post(method, data, headers=None):
        calls.append(method)
        raise _http_error(400)
    monkeypatch.setattr(actions, "_telegram_post", post)
    with pytest.raises(urllib.error.HTTPError):
        actions._post_with_retry("sendPhoto", b"")
    assert len(calls) == 1


def test_retries_network_errors_then_gives_up(monkeypatch):
    calls = []
    def post(method, data, headers=None):
        calls.append(method)
        raise urllib.error.URLError("connection reset")
    monkeypatch.setattr(actions, "_telegram_post", post)
    with pytest.raises(urllib.error.URLError):
        actions._post_with_retry("sendMessage", b"")
    assert len(calls) == config.TELEGRAM_SEND_ATTEMPTS


# ── telegram_send_photo fallback ─────────────────────────────────────────────


def test_photo_rejection_falls_back_to_text(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_TELEGRAM", True)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "100")
    sent = []
    def post(method, data, headers=None):
        if method == "sendPhoto":
            raise _http_error(400)
        sent.append(method)
        return 200
    monkeypatch.setattr(actions, "_telegram_post", post)
    actions.telegram_send_photo(b"jpg", caption="alert")  # must not raise
    assert sent == ["sendMessage"]


def test_send_failure_never_raises(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_TELEGRAM", True)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "100")
    def post(method, data, headers=None):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(actions, "_telegram_post", post)
    actions.telegram_send("hello")  # must not raise


# ── trigger queue guard ──────────────────────────────────────────────────────


def test_submit_swallows_and_logs_action_errors(monkeypatch):
    monkeypatch.setattr(triggers._net, "submit", lambda fn, *a: fn(*a))
    def explode():
        raise RuntimeError("boom")
    triggers._submit(explode)  # must not raise, must not kill the executor


# ── bot polling supervision ──────────────────────────────────────────────────


def test_bot_run_restarts_crashed_polling(monkeypatch):
    from alerts.bot import runtime
    monkeypatch.setattr(config, "WORKER_BACKOFF", 0.0)
    monkeypatch.setattr(config, "WORKER_BACKOFF_CAP", 0.0)
    monkeypatch.setattr(runtime.time, "sleep", lambda s: None)
    attempts = []
    def poll():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("polling crashed")
    monkeypatch.setattr(runtime, "_poll", poll)
    runtime._run()  # returns only after a clean poll exit
    assert len(attempts) == 3
