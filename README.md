# Dog detector

Monitors a video feed (webcam, RTSP camera, or a video file) and runs YOLO
detection inside a polygon zone drawn on the frame. When a dog holds the zone
past a configurable threshold, it fires triggers: a Telegram alert with a
snapshot, an alarm sound, and any custom action you plug in.

The full stack runs in Docker and serves a live web view for drawing zones and
watching detections. The UI is protected by HTTP Basic Auth, so it can be
exposed remotely through a [Cloudflare tunnel](#remote-access-cloudflare-tunnel).
A small desktop launcher provides one-click start/stop for non-technical users.

## Features

- Runs entirely in Docker; the runtime image is torch-free and light enough for a Raspberry Pi
- Multi-camera support, each with its own zone, tile in the web UI, and alerts
- Draw the detection zone in the browser; edits persist across restarts
- Telegram alerts with snapshots, plus a command bot (`/status`, `/snapshot`, `/pause`, ...)
- Motion gating: YOLO only runs when something actually changed in the zone
- Persistence and cooldown logic so a dog walking past doesn't spam you
- Desktop launcher (single `.exe`) for running it on a Windows PC

---

## Prerequisites

- Docker + Docker Compose v2 (`docker compose`)
- A video source: laptop webcam, RTSP/CSI camera, or a test video file

---

## Quick start

```bash
cp .env.example .env                      # fill in your values, compose requires this file
docker compose run --rm exporter          # one-time: export the model to ONNX/NCNN (~20 s)
docker compose up --build
```

Open **http://localhost:5000** for the live view (default login is in `.env`:
`APP_USER` / `APP_PASSWORD`).

The runtime image is torch-free (~200-300 MB RAM, <750 MB image). Exporting a
`.pt` needs torch/ultralytics, so it runs once in a separate `exporter`
container; the exported weights persist in `./models/`. Re-run the exporter
only when you change `MODEL` or `IMGSZ`.

### Demo run

No camera needed: drop any video with a dog into `data/`, set
`VIDEO_SOURCE=/data/test.mp4` in `.env`, start it, and draw a zone over where
the dog walks.

**USB webcam (Linux/Pi):** set `VIDEO_SOURCE=0` and uncomment the `devices:`
block in `docker-compose.yml`. Mac/Windows can't pass webcams into Docker; use
RTSP or a video file.

**Plug and play:** build the launcher once (`launcher/build.bat` on Windows,
`launcher/build.sh` elsewhere) and start everything from `Dog Detector.exe`;
it boots Docker, runs the detector, and opens the live view. See
[launcher/SETUP.md](launcher/SETUP.md).

---

## Configuration

All config lives in `.env`. Full reference in `.env.example`.

| Variable | Default | What it does |
|---|---|---|
| `VIDEO_SOURCE` | `0` | Webcam index, RTSP URL, or file path |
| `ZONE_POINTS` | rectangle | Polygon in normalized `x,y` pairs. Easier: draw it in the web view (edits persist, see below) |
| `ZONE_MIN_OVERLAP` | `0.6` | Fraction of a detection box that must be inside the zone to count (0-1] |
| `MODEL` | `yolo11n.pt` | Model weights, see [models](#models) |
| `CONF_THRESHOLD` | `0.35` | Minimum detection confidence (0-1) |
| `PERSIST_SECONDS` | `3.0` | Dog must hold the zone this long before triggering |
| `COOLDOWN_SECONDS` | `30.0` | Minimum gap between consecutive triggers |
| `DETECT_FPS` | `3.0` | Inference rate (motion gate reduces actual YOLO calls further) |
| `STREAM_FPS` | `10.0` | Web UI refresh rate, independent of inference |
| `IMGSZ` | `320` | Inference resolution in pixels |
| `MOTION_THRESHOLD` | `100` | Pixels changed in zone crop before YOLO runs (0 = always, 4096 = never) |
| `MOTION_HEARTBEAT_SECONDS` | `10.0` | Force inference at least this often so a stationary dog is still caught |
| `ENABLE_SERVER_SOUND` | `false` | Play sound in the container (needs a mapped audio device); the launcher plays client-side regardless |
| `ENABLE_TELEGRAM` | `false` | Send Telegram alerts and enable the bot |

> Keep `MODEL` pointed at `/models/...` so exported weights land in the
> persisted `./models` volume. A bare `yolo11n.pt` re-downloads on every rebuild.

> **Zone edits persist.** Drawing a zone in the web view saves it to
> `/data/zones.json` (keyed by camera id; a legacy `/data/zone.json` is migrated
> automatically), which overrides the configured zone on restart. Delete that file
> to revert. The `/lang` bot command persists the same way (`/data/settings.json`).

### Alert sound

The trigger sound is `data/sound.mp3`. A default one ships with the repo; to
use your own, drop any MP3 there and keep the name `sound.mp3`.

---

## Multiple cameras

One camera needs no extra config. For several, create **`data/cameras.json`**
(see `data/cameras.json.example`):

```json
{
  "defaults": {
    "detect_fps": 3.0,
    "conf_threshold": 0.35,
    "persist_seconds": 3.0,
    "cooldown_seconds": 30.0,
    "motion_threshold": 100,
    "zone_min_overlap": 0.6
  },
  "cameras": [
    {
      "id": "living_room",
      "name": "Living room",
      "source": "rtsp://user:CHANGE_ME@192.168.1.10:554/Streaming/Channels/102",
      "zone": [[0.25, 0.35], [0.85, 0.35], [0.85, 0.95], [0.25, 0.95]],
      "persist_seconds": 5.0,
      "telegram_chat_id": "111111111"
    },
    {
      "id": "kitchen",
      "name": "Kitchen",
      "source": "rtsp://user:CHANGE_ME@192.168.1.11:554/Streaming/Channels/102",
      "zone": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]
    }
  ]
}
```

- `id` and `source` required; other fields fall back to `defaults`/`.env`.
  Gitignored, so RTSP credentials stay out of git.
- Each camera gets its own tile, zone, and alerts (optional `telegram_chat_id`
  per camera). Routes: `/video/<id>`, `/state/<id>`.
- One shared model serviced round-robin. Decoding is the real limit, so point
  `source` at a low-res sub-stream. Expect ~3-6 cameras on a laptop, 1-2 on a Pi.
- A dead camera restarts with backoff; others keep running.

---

## Performance vs. accuracy

All trade-offs are one env-var changes, no code edits needed.

| Goal | Change | Trade-off |
|---|---|---|
| Less CPU / cooler Pi | `DETECT_FPS=1` | Slower reaction (~1 s lag) |
| Faster reaction | `DETECT_FPS=10` | More CPU |
| Catch distant/small dogs | `IMGSZ=640` | ~4x slower inference |
| Reduce false positives | `CONF_THRESHOLD=0.5` | May miss low-confidence detections |
| Require longer presence | `PERSIST_SECONDS=10` | Slower to alert |
| Smoother web stream | `STREAM_FPS=30` | More JPEG encoding CPU |
| Gate less aggressively | `MOTION_THRESHOLD=30` | YOLO runs on camera noise |
| Gate more aggressively | `MOTION_THRESHOLD=500` | May miss a slow-moving dog (heartbeat still catches it) |
| Catch a stiller dog sooner | `MOTION_HEARTBEAT_SECONDS=5` | More idle inference / CPU |
| Fewer edge false-negatives | `ZONE_MIN_OVERLAP=0.15` | A dog merely near the zone may trigger |
| Stricter zone membership | `ZONE_MIN_OVERLAP=0.6` | Dog must be well inside the zone |

**Recommended Pi 4 settings:** `DETECT_FPS=1`, `IMGSZ=320`, `MOTION_THRESHOLD=100`
**Recommended Pi 5 settings:** `DETECT_FPS=3`, `IMGSZ=320`, `MOTION_THRESHOLD=100`

---

## Models

| Model | Speed | Accuracy |
|---|---|---|
| `yolo11n.pt` | ★★★ fastest | ★★☆ |
| `yolo11s.pt` | ★★☆ | ★★★ |
| `yolo11m.pt` | ★☆☆ | ★★★+ |

Run `docker compose run --rm exporter` once after setting `MODEL`/`IMGSZ`: it
exports the `.pt` to **NCNN on Pi** (ARM) or **ONNX on laptop** (x86) into
`./models/`. The runtime container then loads that artifact with no torch. It
refuses to start (with instructions) if the export hasn't been run yet.

---

## Telegram alerts & bot commands

1. Message **@BotFather**, send `/newbot`, copy the token
2. Get your chat ID: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. In `.env`: set `ENABLE_TELEGRAM=true`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`

Once running, the bot also listens for commands from your chat:

| Command | What it does |
|---|---|
| `/status` | Detection state per camera and last alert time |
| `/help` | List all available commands |
| `/pause [camera]` / `/resume [camera]` | Pause/resume alerting (all cameras when no id given) |
| `/snapshot [camera]` | Send the current frame (id optional with a single camera) |

Add custom commands in `app/alerts/bot/commands.py`: one async function plus one line in `COMMAND_REGISTRY`.

---

## Desktop launcher

`launcher/` builds a single `Dog Detector.exe` with a start/stop GUI: it boots
Docker if needed, starts the detector, opens the live view, and plays alert
sounds on the PC itself. Meant for handing the project to someone who just
wants a desktop shortcut. See [launcher/SETUP.md](launcher/SETUP.md).

---

## Remote access (Cloudflare tunnel)

The web UI only listens on `localhost:5000`. To check on it from outside your
network, expose it through a Cloudflare tunnel; basic auth
(`APP_USER`/`APP_PASSWORD` in `.env`) keeps the page gated. Set a strong
password before exposing anything.

For a quick throwaway URL, [install `cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and run:

```bash
cloudflared tunnel --url http://localhost:5000
```

It prints a random `*.trycloudflare.com` URL that works for as long as the
process runs. For a permanent URL on your own domain, create a named tunnel in
the Cloudflare Zero Trust dashboard and point its public hostname at
`http://localhost:5000`.

---

## Raspberry Pi deploy

1. Copy `.env.example` to `.env`, set `VIDEO_SOURCE` to your camera
2. `docker compose run --rm exporter` for the one-time NCNN export (needs network once for the `ncnn` package)
3. `docker compose up --build`

USB webcam: uncomment the `devices:` block in `docker-compose.yml`. CSI or
RTSP cameras need no host devices.
Servo: implement `press_button()` in `app/alerts/triggers.py` and uncomment it in `fire_triggers()`.

---

## Project layout

```
app/
  main.py            entry point: logging + Supervisor().run()
  config.py          all tunables + internal constants, one place
  core/
    supervisor.py    shared services + one thread per camera, restart w/ backoff
    worker.py        CameraWorker: capture -> motion -> inference -> persist -> triggers
    cameras.py       CameraConfig + cameras.json loader (env synthesis fallback)
    state.py         per-camera runtime state (timing, paused flag, latest frame)
  pipeline/
    capture.py       FrameReader: drains the video source in a background thread
    motion.py        motion gate, cheap diff to decide whether to run YOLO
    zone.py          polygon zone geometry: build + point-in-zone
    inference.py     model loading + async inference worker
    persistence.py   per-frame presence -> confirmed trigger (persist/cooldown)
    overlay.py       draws the zone outline + detection boxes
  storage/           persisted zone edits + bot settings (/data JSON files)
  alerts/
    i18n.py          localized message strings (en/he) for triggers + bot
    triggers.py      outbound Telegram alerts + sound + servo stub
    bot/             Telegram command bot: /status, /help, add your own
  web/
    server.py        Flask MJPEG web view + zone editor API, behind basic auth
    templates/       web UI
launcher/            desktop GUI launcher, builds to a single .exe
tests/               pytest suite
scripts/             inference benchmarks
models/              weights (persisted via Docker volume)
data/                sound alerts + cameras.json; drop test videos here
.env.example         full variable reference with defaults
```

---

## License

Released under the [MIT License](LICENSE).
