"""Frame annotation: draw the zone outline and detection boxes in place."""

import cv2


def draw_zone(frame, zone):
    cv2.polylines(frame, [zone], isClosed=True, color=(0, 255, 0), thickness=2)


def draw_detections(frame, boxes):
    """Draw every box; return True if any is inside the zone."""
    present = False
    for x1, y1, x2, y2, _conf, in_zone in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        present = present or in_zone
    return present
