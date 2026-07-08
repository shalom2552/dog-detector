"""Native ONNX Runtime inference so the runtime process never imports torch.

Runs the ultralytics-exported YOLO11 ONNX model directly: letterbox → blob →
session → un-letterbox → NMS, returning dog-class boxes in original-frame pixels.
"""

import ast
import logging

import cv2
import numpy as np
import onnxruntime as ort

import config

log = logging.getLogger("detector")


class OnnxBackend:
    def __init__(self, path):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = config.ONNX_NUM_THREADS
        # Idle spin-wait burns whole cores between runs at low detect rates.
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        # Arena hoards freed activation buffers; plain malloc keeps RSS flat at same speed.
        opts.enable_cpu_mem_arena = False
        self._sess = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        self._input = self._sess.get_inputs()[0]
        self._h, self._w = self._input.shape[2], self._input.shape[3]  # NCHW, fixed imgsz
        names = ast.literal_eval(self._sess.get_modelmeta().custom_metadata_map["names"])
        self._cid = next((i for i, n in names.items() if n == "dog"), None)
        if self._cid is None:
            raise RuntimeError("Model has no 'dog' class; refusing to run. Check model.names.")

    def detect(self, frame_bgr, conf_threshold=None):
        """Return [(x1, y1, x2, y2, conf)] for dogs, in original-frame pixel coords."""
        if conf_threshold is None:
            conf_threshold = config.CONF_THRESHOLD
        blob, ratio, (pad_x, pad_y) = self._preprocess(frame_bgr)
        out = self._sess.run(None, {self._input.name: blob})[0]  # (1, 84, N)
        return self._postprocess(out, ratio, pad_x, pad_y, frame_bgr.shape[:2], conf_threshold)

    def _preprocess(self, frame):
        h0, w0 = frame.shape[:2]
        ratio = min(self._w / w0, self._h / h0)
        nw, nh = round(w0 * ratio), round(h0 * ratio)
        pad_x, pad_y = (self._w - nw) // 2, (self._h - nh) // 2
        resized = cv2.resize(frame, (nw, nh))
        padded = np.full((self._h, self._w, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (self._w, self._h), swapRB=True, crop=False)
        return blob, ratio, (pad_x, pad_y)

    def _postprocess(self, out, ratio, pad_x, pad_y, orig_hw, conf_threshold):
        preds = out[0].transpose()  # (N, 84): 4 xywh + 80 class scores
        scores = preds[:, 4 + self._cid]
        keep = scores >= conf_threshold
        preds, scores = preds[keep], scores[keep]
        if len(preds) == 0:
            return []
        cx, cy, bw, bh = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
        rects = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], axis=1)  # letterboxed x,y,w,h
        idxs = cv2.dnn.NMSBoxes(rects.tolist(), scores.tolist(), conf_threshold, config.NMS_IOU)
        H, W = orig_hw
        result = []
        for i in np.array(idxs).flatten():
            x, y, w, h = rects[i]
            x1 = int(min(max((x - pad_x) / ratio, 0), W - 1))
            y1 = int(min(max((y - pad_y) / ratio, 0), H - 1))
            x2 = int(min(max((x + w - pad_x) / ratio, 0), W - 1))
            y2 = int(min(max((y + h - pad_y) / ratio, 0), H - 1))
            result.append((x1, y1, x2, y2, float(scores[i])))
        return result
