"""persistence.confirmed: inference-gated two-hit arming, absence grace, cooldown."""

import config
from pipeline import persistence
from core.state import DetectionState

BASE = 1000.0  # start well past monotonic 0 so the initial cooldown check passes


def _fresh_state():
    return DetectionState()


def _call(present, state, now, boxes_at):
    return persistence.confirmed(present, boxes_at, state, now,
                                 config.PERSIST_SECONDS, config.COOLDOWN_SECONDS,
                                 config.ABSENCE_GRACE)


# ── Streak gating ────────────────────────────────────────────────────────────


def test_same_inference_repeated_never_arms():
    """A single positive inference repeated over many ticks must not arm the timer."""
    s = _fresh_state()
    boxes_at = BASE
    for i in range(8):
        assert _call(True, s, BASE + i * 0.1, boxes_at) is False
    assert s.in_zone_since is None
    assert s.present_streak == 1


def test_two_distinct_inferences_arm_backdated():
    """Two distinct positive inferences arm the timer, backdated to the first sighting."""
    s = _fresh_state()
    assert _call(True, s, BASE, boxes_at=BASE + 0.0) is False   # streak 1
    assert _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1) is False  # streak 2 → armed
    assert s.in_zone_since == BASE


def test_single_blip_never_arms():
    """Non-consecutive positives (each a distinct inference) must not arm."""
    s = _fresh_state()
    seq = [(True, BASE + 0.0), (False, BASE + 0.1), (False, BASE + 0.2),
           (False, BASE + 0.3), (True, BASE + 0.4), (False, BASE + 0.5)]
    for i, (present, boxes_at) in enumerate(seq):
        assert _call(present, s, BASE + i * 0.1, boxes_at) is False
    assert s.in_zone_since is None


# ── Timer behaviour ──────────────────────────────────────────────────────────


def test_two_consecutive_arms_then_fires_after_persist():
    s = _fresh_state()
    assert _call(True, s, BASE, boxes_at=BASE + 0.0) is False       # streak 1
    assert _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1) is False  # streak 2 → armed
    assert s.in_zone_since is not None
    # Timer is backdated to the first sighting, so persist counts from BASE.
    fire_at = BASE + config.PERSIST_SECONDS + 0.01
    assert _call(True, s, fire_at, boxes_at=BASE + 0.2) is True


def test_brief_absence_within_grace_keeps_timer():
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)
    _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1)  # armed
    armed_at = s.in_zone_since
    _call(False, s, BASE + 0.2, boxes_at=BASE + 0.2)  # blink < grace
    assert s.in_zone_since == armed_at


def test_absence_past_grace_disarms():
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)
    _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1)  # armed
    _call(False, s, BASE + 0.1 + config.ABSENCE_GRACE + 0.5, boxes_at=BASE + 0.2)
    assert s.in_zone_since is None


def test_stale_boxes_do_not_disarm_streak_between_inferences():
    """Ticks that re-read the same stale boxes_at must not reset the streak."""
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)  # streak 1
    # Simulate 5 ticks of False from stale boxes before next inference
    for i in range(1, 6):
        _call(False, s, BASE + i * 0.1, boxes_at=BASE + 0.0)  # same boxes_at → no reset
    assert s.present_streak == 1
    # New positive inference arms
    assert _call(True, s, BASE + 0.6, boxes_at=BASE + 0.6) is False  # streak 2 → armed
    assert s.in_zone_since is not None


def test_stale_streak_past_grace_starts_fresh_accumulation():
    """A positive long after the last sighting must not combine with a stale
    streak into a backdated arm (which would fire instantly off one detection)."""
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)  # streak 1, then the dog vanishes unseen
    late = BASE + 60.0
    assert _call(True, s, late, boxes_at=late) is False  # fresh streak of 1, not armed
    assert s.in_zone_since is None
    assert s.present_streak == 1
    assert s.streak_started_at == late
    # The confirming positive arrives promptly → armed, backdated only to `late`.
    assert _call(True, s, late + 0.1, boxes_at=late + 0.1) is False
    assert s.in_zone_since == late


def test_reset_drops_accumulation():
    """reset() (used by /pause) clears the timer and the streak."""
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)
    _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1)  # armed
    persistence.reset(s)
    assert s.in_zone_since is None
    assert s.present_streak == 0
    assert s.streak_started_at == 0.0
    # A lone positive after reset must not re-arm off pre-reset history.
    assert _call(True, s, BASE + 0.2, boxes_at=BASE + 0.2) is False
    assert s.in_zone_since is None


def test_cooldown_blocks_refire():
    s = _fresh_state()
    _call(True, s, BASE, boxes_at=BASE + 0.0)
    _call(True, s, BASE + 0.1, boxes_at=BASE + 0.1)
    fire_at = BASE + 0.1 + config.PERSIST_SECONDS + 0.01
    assert _call(True, s, fire_at, boxes_at=BASE + 0.2) is True
    s.last_fire = fire_at  # main.py records this on fire
    assert _call(True, s, fire_at + 0.1, boxes_at=BASE + 0.3) is False
