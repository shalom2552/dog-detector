"""Shared bot state, injected once at startup.

`cameras` is the live id -> CameraWorker registry, set by runtime.start_bot()
before polling. It lives here (not runtime) to avoid an import cycle. Always
reach it as `context.cameras` so runtime's assignment (and supervisor worker
restarts) stay visible.
"""

cameras = None  # live id -> CameraWorker registry; None until start_bot() injects it
