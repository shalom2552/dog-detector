"""Model artifact management: one-time .pt export and runtime backend loading.

The runtime process loads an exported ONNX model and never imports torch;
exporting a .pt (export_model) is a separate one-time step in the exporter image.
"""

import glob
import logging
import os
import shutil

import numpy as np

import config

log = logging.getLogger("detector")


def _exported_target():
    """Return (artifact_path, fmt) for the configured .pt, or (MODEL, None) if MODEL isn't a .pt."""
    path = config.MODEL
    if not path.endswith(".pt"):
        return path, None
    return f"{path[:-3]}_{config.IMGSZ}.onnx", "onnx"


def export_model():
    """One-time export of the configured .pt to this platform's format (needs ultralytics)."""
    src = config.MODEL
    out, fmt = _exported_target()
    if fmt is None or os.path.exists(out):
        return out
    for stale in glob.glob(f"{src[:-3]}_*"):
        if stale.endswith(".onnx") or stale.endswith("_ncnn_model"):
            shutil.rmtree(stale) if os.path.isdir(stale) else os.remove(stale)
    log.info("Exporting %s to %s imgsz=%d (one-time)...", src, fmt.upper(), config.IMGSZ)
    from ultralytics import YOLO
    actual = str(YOLO(src, task="detect").export(format=fmt, imgsz=config.IMGSZ))
    if actual != out:
        shutil.move(actual, out)
    return out


def load_model():
    """Load the exported backend and warm it up. Raise if the .pt hasn't been exported yet."""
    out, _ = _exported_target()
    if not os.path.exists(out):
        raise RuntimeError(
            f"No exported model at {out}. Run the one-time export container first:\n"
            f"    docker compose run --rm exporter"
        )
    log.info("Loading model backend: %s", out)
    from pipeline.onnx_backend import OnnxBackend
    backend = OnnxBackend(out)
    backend.detect(np.zeros((320, 320, 3), dtype=np.uint8))  # warmup: first call is slow
    return backend
