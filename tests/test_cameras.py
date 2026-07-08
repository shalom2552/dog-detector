"""cameras.load_cameras: env synthesis, cameras.json parsing, hard validation."""

import json

import pytest

import config
from core.cameras import load_cameras


def _write(tmp_path, data):
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(data))
    return str(p)


VALID = {
    "defaults": {"detect_fps": 2.0, "persist_seconds": 4.0},
    "cameras": [
        {"id": "living_room", "name": "Living room", "source": "rtsp://u:p@ip:554/ch1",
         "zone": [[0.25, 0.35], [0.85, 0.35], [0.85, 0.95], [0.25, 0.95]],
         "persist_seconds": 5.0, "telegram_chat_id": "111111111"},
        {"id": "kitchen", "source": "1",
         "zone": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8]]},
    ],
}


# ── Synthesis (no cameras.json) ──────────────────────────────────────────────


def test_missing_file_synthesizes_env_camera(tmp_path):
    cams = load_cameras(str(tmp_path / "absent.json"))
    assert len(cams) == 1
    cam = cams[0]
    assert cam.id == "cam_main"
    assert cam.source == config.VIDEO_SOURCE
    assert cam.zone_points == tuple(tuple(p) for p in config.ZONE)
    assert cam.detect_fps == config.DETECT_FPS
    assert cam.conf_threshold == config.CONF_THRESHOLD
    assert cam.telegram_chat_id is None


# ── Valid file ───────────────────────────────────────────────────────────────


def test_valid_file_parses_both_cameras(tmp_path):
    cams = load_cameras(_write(tmp_path, VALID))
    assert [c.id for c in cams] == ["living_room", "kitchen"]
    living_room, kitchen = cams
    assert living_room.name == "Living room"
    assert living_room.source == "rtsp://u:p@ip:554/ch1"
    assert living_room.telegram_chat_id == "111111111"
    assert kitchen.name == "kitchen"          # name defaults to id
    assert kitchen.source == 1                # int-string becomes an index
    assert kitchen.telegram_chat_id is None


def test_defaults_chain_env_then_defaults_then_camera(tmp_path):
    living_room, kitchen = load_cameras(_write(tmp_path, VALID))
    assert kitchen.detect_fps == 2.0          # from defaults block
    assert kitchen.persist_seconds == 4.0     # from defaults block
    assert living_room.persist_seconds == 5.0       # per-camera override wins
    assert living_room.cooldown_seconds == config.COOLDOWN_SECONDS  # env fallback


def test_cameras_are_frozen(tmp_path):
    cam = load_cameras(_write(tmp_path, VALID))[0]
    with pytest.raises(Exception):
        cam.name = "other"


# ── Validation errors ────────────────────────────────────────────────────────


def _expect_error(tmp_path, data, needle):
    with pytest.raises(ValueError, match=needle):
        load_cameras(_write(tmp_path, data))


def test_invalid_json_rejected(tmp_path):
    p = tmp_path / "cameras.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_cameras(str(p))


def test_bad_id_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "Bad-Id!", "source": "0"}]},
                  r"id must match")


def test_duplicate_id_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "a", "source": "0"},
                                         {"id": "a", "source": "1"}]},
                  "duplicate camera id")


def test_missing_source_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "living_room"}]}, "'living_room'.*source is required")


def test_unknown_camera_key_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "living_room", "source": "0", "presist_seconds": 3}]},
                  "unknown key 'presist_seconds'")


def test_unknown_defaults_key_rejected(tmp_path):
    _expect_error(tmp_path, {"defaults": {"detect_fsp": 3}, "cameras": [{"id": "a", "source": "0"}]},
                  "unknown key 'detect_fsp'")


def test_unknown_top_level_key_rejected(tmp_path):
    _expect_error(tmp_path, {"camera": [], "cameras": [{"id": "a", "source": "0"}]},
                  "unknown top-level key 'camera'")


def test_bad_zone_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "a", "source": "0", "zone": [[0, 0], [1, 0]]}]},
                  "zone must be a list of 3-32")
    _expect_error(tmp_path, {"cameras": [{"id": "a", "source": "0",
                                          "zone": [[0, 0], [1, 0], [2, 1]]}]},
                  r"zone coordinates must be finite and in \[0, 1\]")


def test_out_of_range_tunable_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "a", "source": "0", "conf_threshold": 1.5}]},
                  "'a'.*conf_threshold is out of range")


def test_bad_chat_id_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": [{"id": "a", "source": "0", "telegram_chat_id": "abc"}]},
                  "telegram_chat_id must be numeric")


def test_empty_cameras_rejected(tmp_path):
    _expect_error(tmp_path, {"cameras": []}, "non-empty list")


def test_error_lists_every_offender(tmp_path):
    data = {"cameras": [{"id": "a", "source": "0", "conf_threshold": 2},
                        {"id": "b", "detect_fps": -1}]}
    with pytest.raises(ValueError) as exc:
        load_cameras(_write(tmp_path, data))
    text = str(exc.value)
    assert "'a'" in text and "'b'" in text
