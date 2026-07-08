"""Model inference micro-benchmark. Run inside the container by benchmark.sh.

Times each stage of a single detection (image prep -> neural net -> box
filtering) over real video frames, and prints the detected boxes for the first
10 frames so two runs can be compared for identical output.
"""
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, "/app")


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return round(int(line.split()[1]) / 1024.0, 1)


def load_frames(video, n):
    cap = cv2.VideoCapture(video)
    frames = []
    while len(frames) < n:
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        frames.append(frame)
    cap.release()
    return frames


def pctl(samples, p):
    return round(sorted(samples)[int(len(samples) * p)] * 1000, 2)


def main():
    model, video, n = sys.argv[1], sys.argv[2], int(sys.argv[3])

    t0 = time.perf_counter()
    from pipeline.onnx_backend import OnnxBackend
    backend = OnnxBackend(model)
    init_s = time.perf_counter() - t0
    rss_loaded = rss_mb()

    t0 = time.perf_counter()
    backend.detect(np.zeros((320, 320, 3), dtype=np.uint8))
    warmup_s = time.perf_counter() - t0

    frames = load_frames(video, n)
    pre, run, post = [], [], []
    for frame in frames:
        t0 = time.perf_counter()
        blob, ratio, (px, py) = backend._preprocess(frame)
        t1 = time.perf_counter()
        out = backend._sess.run(None, {backend._input.name: blob})[0]
        t2 = time.perf_counter()
        backend._postprocess(out, ratio, px, py, frame.shape[:2], 0.25)
        t3 = time.perf_counter()
        pre.append(t1 - t0)
        run.append(t2 - t1)
        post.append(t3 - t2)

    total = [a + b + c for a, b, c in zip(pre, run, post)]
    print(f"   Model load: {init_s:.2f} s, first inference: {warmup_s:.2f} s, "
          f"RAM after load: {rss_loaded:.0f} MB")
    print(f"   Per frame (p50 of {len(frames)}): image prep {pctl(pre, 0.5)} ms + "
          f"neural net {pctl(run, 0.5)} ms + box filter {pctl(post, 0.5)} ms "
          f"= {pctl(total, 0.5)} ms  (slowest 5%: {pctl(total, 0.95)} ms)")
    print("   Detections, first 10 frames (x1,y1,x2,y2@confidence — diff between runs):")
    for i, frame in enumerate(frames[:10]):
        row = "  ".join(f"{b[0]},{b[1]},{b[2]},{b[3]}@{b[4]:.3f}"
                        for b in backend.detect(frame, 0.25)) or "none"
        print(f"     frame {i}: {row}")


main()
