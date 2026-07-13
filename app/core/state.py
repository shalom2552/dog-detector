"""Runtime detection state — timing, persistence tracking, per-loop mutable data.

Interval timers use time.monotonic so the detector is immune to wall-clock steps
(e.g. NTP correcting an RTC-less Pi at boot). Wall-clock stamps are kept
separately and used only for human-facing display.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectionState:
    motion_bg: Optional[object] = None     # EMA background reference for the motion gate
    in_zone_since: Optional[float] = None  # monotonic: dog first appeared in zone
    last_seen_in_zone: float = 0.0         # monotonic: last positive detection
    present_streak: int = 0                # consecutive fresh positive inferences (arming)
    streak_started_at: float = 0.0         # monotonic: first sighting of the current streak
    last_streak_boxes_at: float = 0.0      # boxes_at of the inference that last touched the streak
    last_fire: float = 0.0                 # monotonic: last trigger firing (cooldown logic)
    last_fire_wall: float = 0.0            # wall clock: last trigger firing (display only)
    last_detect: float = 0.0               # monotonic: last inference gate check
    last_infer: float = 0.0                # monotonic: last actual inference submission
    latest_frame: Optional[object] = None  # most recent annotated frame (for /snapshot)
    paused: bool = False                   # when True, suppress trigger firing
