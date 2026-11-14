# eidolon_vision

Host **visual cortex** for the desktop-companion vision organ. It distills gated
image bursts from ATK / StackChan into `sense.*` facts — it does **not** stream
video and it is **not** the conversational agent. Pixels are processed in memory
and discarded; only bounded scalar facts leave.

Design source of truth: `docs/todo/桌面共处/桌面共处-场景与多设备联动方案.md` (§11).
Wire contracts (`sense.*`) live in `eidolon_sdk.biz.sense` — this service imports
them, it does not redefine them.

## What it is / isn't

- **CPU-only.** The workload is gated bursts (fatigue every few minutes, scene
  events occasionally, look on demand), not a video stream — so no GPU.
- **Two faces, one service:**
  - *async fact face* — `POST /v1/burst`: device pushes JPEG frames → detect →
    aggregate → emit `sense.fatigue` / `sense.event` to the Hub.
  - *sync VLM face* — `POST /v1/look`: single image + question → litellm →
    text (the Explain backend for ⑥ 桌面之眼).
- **v1 models:** MediaPipe Face Landmarker (fatigue). **No YOLO** — MediaPipe's
  object detector covers ④ scene when it ships; YOLO stays a later pluggable
  backend behind `detect/base.py`.

## Layout

```
eidolon_vision/
  app/        FastAPI transport (burst / look / healthz) + settings
  core/       auth (verify Hub-signed scoped token), pipeline, shared types
  detect/     Detector port + MediaPipe face landmarker (stateless)
  aggregate/  Aggregator port + fatigue window (the only state; ephemeral)
  emit/       post sense.* facts to the Hub fact-ingress
  vlm/        on-demand look via litellm
```

## Data flow (image bytes never traverse the Hub control plane)

```
Hub issues scoped upload token ──► device POST burst (frames+token) ──► eidolon_vision
   verify token (offline) → decode → route-by-trigger → Detector → Aggregator
   → emit sense.* to Hub fact-ingress (Hub re-validates binding/epoch, projects, gates)
```

## Dev

```
uv sync                      # NB: pulls mediapipe/opencv (heavy, CPU)
uv run pytest                # pure-logic tests (aggregator, auth) need no models
uv run python -m eidolon_vision.app        # serves 127.0.0.1:18085
# or override: EIDOLON_VISION_PORT=... uv run python -m eidolon_vision.app
```

`config/default.yaml` documents settings; override via `EIDOLON_VISION_*` env
vars. The `hub_public_key` (PEM) and the face model asset are injected at deploy
and are git-ignored — never commit them.

## Calibration

Only thresholds are open (M3): mouth/eye aspect-ratio cutoffs, window, cooldown
in `aggregate/fatigue.py::FatigueConfig`. The tech stack is fixed.

## License

Copyright © 2026 Li Jinsong.

This project is available under the
[PolyForm Noncommercial License 1.0.0](LICENSE) for permitted noncommercial
use. Commercial use requires a separate written license; contact
[lijinsong@aimanthor.com](mailto:lijinsong@aimanthor.com).

See [LICENSING.md](LICENSING.md) and [NOTICE](NOTICE) for scope, exceptions,
and required notices.

## Face identity (2026-11-14)

A third shape of work beside the fact path and the answer path: compare one
still with the faces the Owner enrolled. Vision reports evidence; it never
decides who someone is and never stores a template.

- `POST /v1/faces/embed`: one reference photo in; a 128-number feature out, or
  the reason the photo cannot be used (`no_face`, `multiple_faces`,
  `face_too_small`, `low_confidence`). Called by Admin when the Owner turns
  recognition on for a Person.
- `POST /v1/faces/match`: one still plus the templates the caller is entitled to
  compare against; per face, a score and band (`strong` / `weak` / `none`) for
  each enrolled person. No feature is returned. Called by Channel for
  `vision.who`.

Both routes take the Host service token (`EIDOLON_VISION_SERVICE_TOKEN`), not a
device upload token, and answer 503 until that token and
`EIDOLON_VISION_FACE_IDENTITY_MODEL_DIR` are set. The model package (YuNet +
SFace from the OpenCV zoo, with `manifest.json` and `face-policy.json`) is owned
by `eidolon_models` under `face_recognition/sface_yunet_opencv_zoo/<revision>/`;
checksums are verified at start and nothing is downloaded. Code:
`runtime/faces.py` (rules, no model needed), `adapters/faces/opencv_zoo.py`,
`app/faces_http.py`. The audit row for a comparison holds counts only.
