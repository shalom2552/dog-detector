"""web routes + hub state: aggregate /state shape, /healthz, zone routing."""

import base64
from types import SimpleNamespace

import numpy as np
import pytest

import config
from web import hub, server

AUTH = {"Authorization": "Basic " + base64.b64encode(b"u:p").decode()}


def _frame():
    return np.zeros((10, 10, 3), dtype=np.uint8)


def _configure(*cams):
    hub.configure([SimpleNamespace(id=i, name=n) for i, n in cams])


@pytest.fixture(autouse=True)
def _auth_and_clean(monkeypatch):
    monkeypatch.setattr(config, "APP_USER", "u")
    monkeypatch.setattr(config, "APP_PASSWORD", "p")
    yield
    with hub._lock:
        hub._registry.clear()
        hub._cams.clear()
        hub._pending_zones.clear()


@pytest.fixture()
def client():
    return server.app.test_client()


def test_auth_gates_everything_but_healthz(client):
    _configure(("cam_main", "Main Camera"))
    assert client.get("/state").status_code == 401
    assert client.get("/healthz").status_code in (200, 503)


def test_single_camera_state_keeps_legacy_top_level_fields(client):
    _configure(("cam_main", "Main Camera"))
    hub.update("cam_main", _frame(), dog_in_zone=False, paused=False, last_trigger=None)
    s = client.get("/state", headers=AUTH).get_json()
    assert set(s["cameras"]) == {"cam_main"}
    assert s["cameras"]["cam_main"]["name"] == "Main Camera"
    assert s["dog_in_zone"] is False          # legacy merge while one camera exists
    assert s["frame_age"] is not None
    assert "boot_time" in s
    assert "frame_raw" not in s["cameras"]["cam_main"]


def test_multi_camera_state_has_no_legacy_merge(client):
    _configure(("living_room", "Living room"), ("kitchen", "Kitchen"))
    hub.update("living_room", _frame(), dog_in_zone=True, last_trigger=None)
    s = client.get("/state", headers=AUTH).get_json()
    assert set(s["cameras"]) == {"living_room", "kitchen"}
    assert "dog_in_zone" not in s
    assert s["cameras"]["kitchen"]["frame_age"] is None  # no frame yet


def test_per_camera_state_route(client):
    _configure(("living_room", "Living room"))
    hub.update("living_room", _frame(), dog_in_zone=False)
    assert client.get("/state/living_room", headers=AUTH).get_json()["name"] == "Living room"
    assert client.get("/state/nope", headers=AUTH).status_code == 404


def test_video_unknown_camera_404s(client):
    _configure(("living_room", "Living room"))
    assert client.get("/video/nope", headers=AUTH).status_code == 404


def test_healthz_ok_if_any_camera_fresh(client):
    _configure(("living_room", "Living room"), ("kitchen", "Kitchen"))
    r = client.get("/healthz")
    assert r.status_code == 503               # nothing fresh yet
    hub.update("living_room", _frame())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["cameras"]["kitchen"] is None


def test_zone_updates_route_to_the_right_camera(client):
    _configure(("living_room", "Living room"), ("kitchen", "Kitchen"))
    r = client.post("/api/zone", headers=AUTH,
                    json={"points": [[0, 0], [1, 0], [1, 1]], "cam_id": "kitchen"})
    assert r.status_code == 200
    assert hub.pop_zone_update("living_room") is None
    assert hub.pop_zone_update("kitchen") == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert hub.pop_zone_update("kitchen") is None  # popped once


def test_zone_without_cam_id_defaults_to_sole_camera(client):
    _configure(("living_room", "Living room"))
    r = client.post("/api/zone", headers=AUTH, json={"points": [[0, 0], [1, 0], [1, 1]]})
    assert r.status_code == 200
    assert hub.pop_zone_update("living_room") is not None


def test_zone_unknown_camera_404s(client):
    _configure(("living_room", "Living room"))
    r = client.post("/api/zone", headers=AUTH,
                    json={"points": [[0, 0], [1, 0], [1, 1]], "cam_id": "bogus"})
    assert r.status_code == 404


def test_index_renders_a_tile_per_camera(client):
    _configure(("living_room", "Living room"), ("kitchen", "Kitchen"))
    html = client.get("/", headers=AUTH).get_data(as_text=True)
    assert "/video/living_room" in html and "/video/kitchen" in html
    assert "Living room" in html and "Kitchen" in html
    assert 'data-cam-id="living_room"' in html
