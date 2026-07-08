"""Persist small runtime settings (e.g. /lang) to a writable volume. Best-effort:
a corrupt or read-only /data never crashes."""

from storage import read_json_dict, write_json_atomic

SETTINGS_FILE = "/data/settings.json"


def load():
    """Return the settings dict, or {} if absent/corrupt."""
    data = read_json_dict(SETTINGS_FILE)
    return data if data is not None else {}


def save(updates):
    """Merge updates into the settings file (atomic write)."""
    data = load()
    data.update(updates)
    write_json_atomic(SETTINGS_FILE, data, "settings")
