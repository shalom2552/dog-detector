"""Best-effort JSON persistence on /data: shared read + atomic-write helpers."""

import json
import logging
import os
import tempfile

log = logging.getLogger("detector")


def read_json_dict(path):
    """Dict from path; None if absent, {} if corrupt (logged) or not a dict."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        log.warning("Ignoring corrupt %s: %s", path, e)
        return {}


def write_json_atomic(path, data, what):
    """Atomically persist data as JSON (temp file + os.replace); log-and-continue on failure."""
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not persist %s to %s: %s", what, path, e)
