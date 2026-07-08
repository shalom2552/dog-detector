"""Zone geometry: build the pixel polygon from normalized points and test box membership."""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger("zone")


@dataclass
class Zone:
    poly: np.ndarray          # int32 polygon points
    bbox: tuple               # (x, y, w, h) bounding rect
    mask: np.ndarray          # uint8 H×W, 255 inside the polygon
    min_overlap: float        # fraction of a box that must lie inside to count

    def contains_box(self, box):
        """True if at least `min_overlap` of the box lies inside the polygon."""
        x1, y1, x2, y2 = box
        h, w = self.mask.shape
        x1, x2 = min(max(int(x1), 0), w), min(max(int(x2), 0), w)
        y1, y2 = min(max(int(y1), 0), h), min(max(int(y2), 0), h)
        area = (x2 - x1) * (y2 - y1)
        if area <= 0:
            return False
        inside = cv2.countNonZero(self.mask[y1:y2, x1:x2])
        return inside / area >= self.min_overlap


def build_zone(frame, points, min_overlap):
    """Return a Zone scaled to the frame's pixel size; `points` are normalized (x, y) in [0, 1]."""
    h, w = frame.shape[:2]
    log.info("Built zone. Frame size: %dx%d", w, h)
    poly = np.array(
        [(min(max(int(x * w), 0), w - 1), min(max(int(y * h), 0), h - 1)) for x, y in points],
        dtype=np.int32,
    )
    bbox = cv2.boundingRect(poly)
    if bbox[2] < 2 or bbox[3] < 2:
        raise ValueError(
            f"Zone bounding box is degenerate ({bbox[2]}x{bbox[3]}px); check the zone points"
        )
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    return Zone(poly=poly, bbox=bbox, mask=mask, min_overlap=min_overlap)
