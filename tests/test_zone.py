"""Zone.contains_box: box-overlap membership against a rendered mask."""

import cv2
import numpy as np

from pipeline.zone import Zone


def _triangle_zone(min_overlap=0.3):
    # Lower-left triangle: inside where x + y <= 100, on a 101x101 mask.
    poly = np.array([(0, 0), (100, 0), (0, 100)], dtype=np.int32)
    mask = np.zeros((101, 101), dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    return Zone(poly=poly, bbox=cv2.boundingRect(poly), mask=mask, min_overlap=min_overlap)


def test_box_fully_inside_is_true():
    assert _triangle_zone().contains_box((5, 5, 45, 45)) is True


def test_box_small_overlap_is_false():
    # ~6% of this box lies inside the triangle — below the 0.3 default.
    assert _triangle_zone().contains_box((40, 40, 100, 100)) is False


def test_min_overlap_is_per_zone():
    # The same box passes a permissive zone and fails a strict one.
    assert _triangle_zone(min_overlap=0.05).contains_box((40, 40, 100, 100)) is True
    assert _triangle_zone(min_overlap=0.3).contains_box((40, 40, 100, 100)) is False


def test_box_fully_outside_is_false():
    assert _triangle_zone().contains_box((60, 60, 100, 100)) is False


def test_empty_box_is_false():
    assert _triangle_zone().contains_box((30, 30, 30, 30)) is False


def test_box_clipped_to_frame_bounds():
    # Negative / oversized coords must clip, not raise.
    assert _triangle_zone().contains_box((-50, -50, 45, 45)) is True
