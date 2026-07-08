"""HTTP layer of the live debug web view (http://localhost:5000).

Routes read and write the shared camera hub (web/hub.py). /video and /state stay
as aliases for old clients: /video streams the first camera, /state returns the
aggregate plus legacy top-level fields while exactly one camera exists.

Served by Werkzeug's threaded dev server on purpose: MJPEG holds one thread per
client for the connection's life, which suits its thread-per-request model.
"""

import hmac
import math
import threading
import time

import flask

import config
from web import hub

app = flask.Flask(__name__)
_workers = None


# ── Auth ────────────────────────────────────────────────────────────────────
# One shared HTTP Basic credential gating the whole site (public Cloudflare
# tunnel). before_request runs ahead of every view, so new routes and static
# files are protected automatically.


def _credentials_ok(auth):
    if not auth:
        return False
    user_ok = hmac.compare_digest(auth.username or "", config.APP_USER)
    pass_ok = hmac.compare_digest(auth.password or "", config.APP_PASSWORD)
    return user_ok and pass_ok


@app.before_request
def _require_auth():
    if flask.request.path == "/healthz":  # leaks only freshness booleans
        return None
    if not _credentials_ok(flask.request.authorization):
        return flask.Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Dog Detector"'},
        )


# ── Routes ──────────────────────────────────────────────────────────────────


def _video_response(cam_id):
    return flask.Response(
        hub.mjpeg_frames(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/video/<cam_id>")
def video_cam(cam_id):
    if not hub.has_camera(cam_id):
        flask.abort(404)
    return _video_response(cam_id)


@app.route("/video")
def video():
    cam_id = hub.default_cam_id()
    if cam_id is None:
        flask.abort(404)
    return _video_response(cam_id)


@app.route("/sound")
def sound_endpoint():
    pending, camera = hub.pop_sound()
    return flask.jsonify({"pending": pending, "camera": camera})


@app.route("/healthz")
def healthz():
    now = time.time()
    cams = {cam_id: (now - at if at > 0 else None) for cam_id, at in hub.frame_stamps().items()}
    ok = any(age is not None and age < 10 for age in cams.values())
    return flask.jsonify({"ok": ok, "cameras": cams}), 200 if ok else 503


@app.route("/state")
def state_json():
    return flask.jsonify(hub.get_state())


@app.route("/state/<cam_id>")
def state_cam_json(cam_id):
    pub = hub.get_camera_state(cam_id)
    if pub is None:
        flask.abort(404)
    return flask.jsonify(pub)


def _parse_points(data):
    """Validate a posted zone: 3-32 finite x,y pairs, clamped to [0, 1]. Raise ValueError."""
    pts_raw = data["points"]
    if not isinstance(pts_raw, list) or not (3 <= len(pts_raw) <= 32):
        raise ValueError("points must be a list of 3-32 pairs")
    pts = []
    for p in pts_raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError("each point must be a 2-item [x, y]")
        x, y = float(p[0]), float(p[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("coordinates must be finite")
        pts.append((min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)))
    return pts


@app.route("/api/zone", methods=["POST"])
def update_zone():
    data = flask.request.json
    if not data or "points" not in data:
        return flask.jsonify({"error": "missing points"}), 400
    # Default to the sole camera (single-cam clients predate cam_id in the body).
    cam_id = data.get("cam_id") or hub.default_cam_id() or "cam_main"
    if not hub.has_camera(cam_id):
        return flask.jsonify({"error": f"unknown camera {cam_id!r}"}), 404
    try:
        pts = _parse_points(data)
    except (ValueError, TypeError) as e:
        return flask.jsonify({"error": str(e)}), 400
    hub.push_zone_update(cam_id, pts)
    return flask.jsonify({"status": "ok"})


@app.route("/api/pause/<cam_id>", methods=["POST"])
def pause_camera(cam_id):
    if _workers and cam_id in _workers:
        _workers[cam_id].state.paused = True
        return flask.jsonify({"status": "ok"})
    return flask.jsonify({"error": "not found"}), 404


@app.route("/api/resume/<cam_id>", methods=["POST"])
def resume_camera(cam_id):
    if _workers and cam_id in _workers:
        _workers[cam_id].state.paused = False
        return flask.jsonify({"status": "ok"})
    return flask.jsonify({"error": "not found"}), 404


@app.route("/sw.js")
def service_worker():
    # Minimal fetch listener required by Chrome to pass PWA install criteria.
    js = "self.addEventListener('fetch', function(e) {});"
    return flask.Response(js, mimetype="application/javascript")


@app.route("/")
def index():
    cameras = [
        {"id": cam_id, "name": name, "feed_url": f"/video/{cam_id}"}
        for cam_id, name in hub.camera_names()
    ]
    return flask.render_template("index.html", cameras=cameras)


# ── Startup ─────────────────────────────────────────────────────────────────


def start(workers=None, host=config.WEB_HOST, port=config.WEB_PORT):
    global _workers
    _workers = workers
    threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True),
        daemon=True,
    ).start()
