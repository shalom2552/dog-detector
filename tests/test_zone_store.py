"""storage.zones: per-camera persistence over one zones.json + legacy migration."""

import json

import pytest

from storage import zones

TRIANGLE = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]


@pytest.fixture(autouse=True)
def _tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ZONES_FILE", str(tmp_path / "zones.json"))
    monkeypatch.setattr(zones, "LEGACY_ZONE_FILE", str(tmp_path / "zone.json"))


def test_load_absent_returns_none():
    assert zones.load("cam_main") is None


def test_save_then_load_roundtrips():
    zones.save("living_room", TRIANGLE)
    assert zones.load("living_room") == TRIANGLE
    assert zones.load("kitchen") is None


def test_save_keeps_other_cameras():
    zones.save("living_room", TRIANGLE)
    other = [(0.2, 0.2), (0.8, 0.2), (0.5, 0.8)]
    zones.save("kitchen", other)
    assert zones.load("living_room") == TRIANGLE
    assert zones.load("kitchen") == other


def test_legacy_zone_json_migrates_to_cam_main():
    with open(zones.LEGACY_ZONE_FILE, "w") as f:
        json.dump([[x, y] for x, y in TRIANGLE], f)
    assert zones.load("cam_main") == TRIANGLE
    # Migration wrote zones.json, which now takes precedence.
    with open(zones.ZONES_FILE) as f:
        assert json.load(f) == {"cam_main": [[x, y] for x, y in TRIANGLE]}


def test_corrupt_zones_file_is_ignored():
    with open(zones.ZONES_FILE, "w") as f:
        f.write("{corrupt")
    assert zones.load("cam_main") is None


def test_corrupt_entry_is_ignored():
    with open(zones.ZONES_FILE, "w") as f:
        json.dump({"cam_main": [[5.0, 5.0], [1, 0], [0, 1]]}, f)  # out of range
    assert zones.load("cam_main") is None
