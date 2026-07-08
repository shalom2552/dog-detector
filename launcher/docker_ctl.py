"""Thin wrappers over `docker compose` plus a health check against the web view."""

import base64
import os
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser

from paths import DOCKER_DESKTOP, EDGE, NO_WINDOW, REPO_DIR


# ── Docker ──────────────────────────────────────────────────────────────────

def _run(args, timeout=120):
    try:
        r = subprocess.run(args, cwd=REPO_DIR, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)


def docker_engine_running():
    ok, _ = _run(["docker", "info"], timeout=15)
    return ok


def start_docker_desktop():
    if os.path.exists(DOCKER_DESKTOP):
        try:
            subprocess.Popen([DOCKER_DESKTOP], creationflags=NO_WINDOW)
        except Exception:
            pass
    for _ in range(45):
        if docker_engine_running():
            return True
        time.sleep(2)
    return False


def _compose_stream(args, on_line):
    """Run a compose command, streaming each output line to on_line; return success."""
    env = {**os.environ, "BUILDKIT_PROGRESS": "plain"}
    try:
        proc = subprocess.Popen(
            args, cwd=REPO_DIR, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=NO_WINDOW)
    except Exception as e:
        on_line(str(e))
        return False
    for line in proc.stdout:
        on_line(line.rstrip())
    proc.wait()
    return proc.returncode == 0


def compose_up(on_line):
    return _compose_stream(["docker", "compose", "up", "-d"], on_line)


# ── One-time model export ───────────────────────────────────────────────────

def _exported_model():
    """Host path of the exported model artifact, or None when MODEL isn't a .pt.

    Mirrors app/pipeline/model.py:_exported_target(); the container's
    /app/models is the ./models bind mount, so the artifact is visible here.
    """
    model = os.environ.get("MODEL", "yolo11n.pt")
    if not model.endswith(".pt"):
        return None
    try:
        imgsz = int(os.environ.get("IMGSZ", "320"))
    except ValueError:
        imgsz = 320
    stem = os.path.splitext(os.path.basename(model))[0]
    return os.path.join(REPO_DIR, "models", f"{stem}_{imgsz}.onnx")


def export_needed():
    path = _exported_model()
    return path is not None and not os.path.exists(path)


def compose_export(on_line):
    return _compose_stream(["docker", "compose", "run", "--build", "--rm", "exporter"], on_line)


def compose_down():
    return _run(["docker", "compose", "down"], timeout=60)


def container_running():
    # container_name is pinned in compose, so inspect it directly — one call.
    # A missing container just errors -> not running.
    ok, out = _run(["docker", "inspect", "-f", "{{.State.Running}}", "dog-detector"], timeout=15)
    return ok and out.strip() == "true"


# ── Web view health ─────────────────────────────────────────────────────────

def open_live_view(url):
    if os.path.exists(EDGE):
        subprocess.Popen([EDGE, f"--app={url}"], creationflags=NO_WINDOW)
    else:
        webbrowser.open(url)


def http_get(url, timeout=3):
    req = urllib.request.Request(url)
    user, pw = os.environ.get("APP_USER"), os.environ.get("APP_PASSWORD")
    if user and pw:  # web view is gated behind Basic Auth
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200, r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # 401 = wrong/missing APP_USER/APP_PASSWORD
        return False, e.code, ""
    except Exception:
        return False, None, ""
