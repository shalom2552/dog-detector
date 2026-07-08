# Multi-arch: x86_64 (laptop) + arm64 (Pi 5). Pinned patch tag for reproducible builds.

# ── exporter stage ────────────────────────────────────────────────────────────
# Full toolchain (ultralytics + CPU torch). Used once via the `exporter` compose
# service to export a .pt to ONNX (x86) / NCNN (ARM). Never shipped as runtime.
FROM python:3.11.11-slim-bookworm AS exporter

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-export.txt ./
RUN pip install --no-cache-dir --root-user-action=ignore \
        -r requirements.txt -r requirements-export.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu

COPY app/ /app/
RUN useradd --uid 1000 --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["python", "-c", "from pipeline.model import export_model; export_model()"]

# ── runtime stage ─────────────────────────────────────────────────────────────
# Slim: onnxruntime + opencv + flask + telegram. No torch/ultralytics.
FROM python:3.11.11-slim-bookworm AS runtime

# glib for opencv-python-headless (no libGL needed — headless has no GUI),
# mpg123 for optional server-side sound (ENABLE_SERVER_SOUND).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 mpg123 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY app/ /app/

# Run non-root. uid/gid 1000 matches the default host user so the bind-mounted
# ./models stays writable for the one-time model export.
RUN useradd --uid 1000 --create-home appuser && chown -R appuser:appuser /app
USER appuser

# ~40 threads x per-thread glibc arenas otherwise hoard freed pages as RSS.
ENV MALLOC_ARENA_MAX=2

EXPOSE 5000

# Process-up != stream-alive. /healthz reports frame freshness and is exempt
# from Basic Auth, so it 503s (urlopen raises) when the pipeline stalls.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)" || exit 1

CMD ["python", "main.py"]
