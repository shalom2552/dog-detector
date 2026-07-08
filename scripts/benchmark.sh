#!/bin/sh
# Full performance benchmark for dog-detector. Everything runs inside Docker.
#
#   ./scripts/benchmark.sh
#
# Builds the image, runs the test suite, measures startup time, memory, CPU
# and per-frame model latency, and explains every number it prints.
# Safe to run alongside a deployed instance: uses its own container name/port,
# Telegram disabled, test videos as the camera sources.
set -e
cd "$(dirname "$0")/.."

NAME=dog-detector-bench
PORT=5099
URL="http://127.0.0.1:$PORT"

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# ── Build ────────────────────────────────────────────────────────────────────
say "Building Docker image (docker compose build)"
docker compose build 2>&1 | tail -1

# ── Tests ────────────────────────────────────────────────────────────────────
say "Running test suite inside the container"
note "(/data is deliberately NOT mounted: a real data/zones.json would override"
note " the default zone and break one config test)"
docker run --rm -v "$PWD/app:/app" -v "$PWD/tests:/tests" \
    -e APP_USER=bench -e APP_PASSWORD=bench dog-detector:latest \
    sh -c "pip install -q --no-cache-dir pytest >/dev/null 2>&1; cd / && python -m pytest /tests -q" \
    | tail -1

# ── Model latency ────────────────────────────────────────────────────────────
say "Model inference latency (60 frames of data/test.mp4)"
MODEL_FILE=$(ls models/*.onnx 2>/dev/null | head -1)
if [ -z "$MODEL_FILE" ]; then
    note "No exported .onnx in models/ — run: docker compose run --rm exporter"
    exit 1
fi
# models/yolo11n_480.onnx -> the app wants MODEL=/models/yolo11n.pt IMGSZ=480
BASE=$(basename "$MODEL_FILE" .onnx)   # yolo11n_480
IMGSZ=${BASE##*_}
PT="/models/${BASE%_*}.pt"
note "Model: $MODEL_FILE"
docker run --rm -v "$PWD/app:/app" -v "$PWD/models:/models" -v "$PWD/data:/data" \
    -v "$PWD/scripts:/scripts:ro" dog-detector:latest \
    python /scripts/bench_inference.py "/$MODEL_FILE" /data/test.mp4 60

# ── App startup ──────────────────────────────────────────────────────────────
say "Cold start (docker run -> /healthz answers 200 = pipeline delivering frames)"
cleanup
START=$(date +%s.%N)
docker run -d --name "$NAME" --memory 512m -p "$PORT:5000" \
    -v "$PWD/app:/app" -v "$PWD/models:/models" -v "$PWD/data:/data" \
    -e APP_USER=bench -e APP_PASSWORD=bench -e ENABLE_TELEGRAM=false \
    -e VIDEO_SOURCE=/data/test.mp4 -e MODEL="$PT" -e IMGSZ="$IMGSZ" \
    dog-detector:latest >/dev/null
for _ in $(seq 1 300); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' "$URL/healthz" 2>/dev/null || echo 000)
    [ "$CODE" = 200 ] && break
    sleep 0.1
done
END=$(date +%s.%N)
if [ "$CODE" != 200 ]; then
    note "App never became healthy — logs:"; docker logs --tail 20 "$NAME"; exit 1
fi
awk -v a="$START" -v b="$END" 'BEGIN{printf "   Cold start: %.2f s\n", b-a}'

# ── RAM / CPU sampling ───────────────────────────────────────────────────────
sample() {  # sample <seconds> <label> — average docker stats over a window
    SECS=$1; LABEL=$2
    CPU_SUM=0; RSS_SUM=0; RSS_MAX=0; N=0
    T_END=$(($(date +%s) + SECS))
    while [ "$(date +%s)" -lt "$T_END" ]; do
        LINE=$(docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' "$NAME")
        RSS=$(echo "$LINE" | awk '{v=$1; if (v ~ /GiB/) {gsub(/GiB/,"",v); v*=1024} else {gsub(/MiB/,"",v)}; print v}')
        CPU=$(echo "$LINE" | awk '{print $NF}' | tr -d '%')
        RSS_SUM=$(awk -v a="$RSS_SUM" -v b="$RSS" 'BEGIN{print a+b}')
        CPU_SUM=$(awk -v a="$CPU_SUM" -v b="$CPU" 'BEGIN{print a+b}')
        RSS_MAX=$(awk -v a="$RSS" -v b="$RSS_MAX" 'BEGIN{print (a>b)?a:b}')
        N=$((N+1))
    done
    awk -v r="$RSS_SUM" -v m="$RSS_MAX" -v c="$CPU_SUM" -v n="$N" -v l="$LABEL" \
        'BEGIN{printf "   %s: memory %.0f MB (max %.0f MB), CPU %.0f%% of one core\n", l, r/n, m, c/n}'
}

say "Steady state, nobody watching the stream (30 s average)"
note "Memory = whole container (Python + model + video decoding buffers)."
note "CPU can exceed 100% — that means more than one core busy."
sleep 5
sample 30 "Idle"

say "One viewer watching the MJPEG stream + UI polling /state (30 s average)"
note "Adds JPEG encoding per frame, so CPU rises a little; memory should not."
curl -s -u bench:bench "$URL/video" -o /dev/null &
VIEWER=$!
( while true; do curl -s -u bench:bench "$URL/state" -o /dev/null; sleep 1; done ) &
POLLER=$!
sleep 3
sample 30 "Watching"
kill $VIEWER $POLLER 2>/dev/null || true

say "Web endpoint latency (/state, 20 requests)"
for _ in $(seq 1 20); do
    curl -s -u bench:bench -o /dev/null -w '%{time_total}\n' "$URL/state"
done | sort -n | awk '{a[NR]=$1} END{printf "   typical %.1f ms, worst %.1f ms\n", a[int(NR/2)]*1000, a[NR]*1000}'

say "Peak memory since container start (kernel cgroup counter)"
PEAK=$(docker exec "$NAME" cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo 0)
awk -v p="$PEAK" 'BEGIN{printf "   Peak: %.0f MB (container is killed at its mem_limit — headroom matters)\n", p/1048576}'

say "Done"
note "Container removed. Compare runs by saving this output to a file."
