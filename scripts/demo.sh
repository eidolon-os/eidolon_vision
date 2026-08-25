#!/usr/bin/env bash
# One command, all three demo criteria. Nothing to configure, nothing to clean up.
#
#   scripts/demo.sh            run everything, stop the server at the end
#   scripts/demo.sh --keep     leave the server running so you can poke at it
#
# No Hub, no device, no network: the token is signed by a local key and facts go
# to an audit log instead of the Hub. Both are ports, not shims — see §07 of the
# plan for why faking those boundaries tests the layering rather than dodging it.

set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-18085}"
BASE="http://127.0.0.1:${PORT}"
KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

hr() { printf '\n\033[36m════ %s\033[0m\n' "$*"; }
say() { printf '\033[90m%s\033[0m\n' "$*"; }

mkdir -p var samples

hr "0/5  环境"
uv sync --extra dev --extra interpreter-ocr -q
say "  rapidocr + onnxruntime 就绪（mediapipe 未装 —— 正好演示降级）"

if [[ ! -f samples/note.jpg ]]; then
  say "  生成样本图…"
  uv run python scripts/make_samples.py
fi

# The server needs the public half of the demo key at startup.
PUBKEY="$(uv run python scripts/demo_look.py --image samples/note.jpg --print-key)"

hr "1/5  启动服务"
rm -f var/audit.jsonl
EIDOLON_VISION_HUB_BASE_URL="" \
EIDOLON_VISION_ENABLED_CAPABILITIES='["look_on_demand","presence_verify","fatigue"]' \
EIDOLON_VISION_ENABLE_CLOUD_VLM=true \
EIDOLON_VISION_PRESENCE_SOURCE=device \
EIDOLON_VISION_AUDIT_LOG_PATH=var/audit.jsonl \
EIDOLON_VISION_HUB_PUBLIC_KEY="$PUBKEY" \
  uv run uvicorn 'eidolon_vision.app.http:create_app' \
  --factory --port "$PORT" --host 127.0.0.1 > var/server.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > var/server.pid

cleanup() {
  if [[ "$KEEP" == "0" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    rm -f var/server.pid
  fi
}
trap cleanup EXIT

for _ in $(seq 1 60); do curl -sf "$BASE/healthz" >/dev/null && break; sleep 0.5; done
curl -s "$BASE/healthz" | uv run python -m json.tool
say "  注意 roles_bound 里没有 face_metrics —— mediapipe 缺失，那个角色不绑定，服务照常起"

hr "2/5  DEMO 1 · 按需之眼（本地 OCR，零出境）"
uv run python scripts/demo_look.py --image samples/note.jpg --question "这上面写的什么？" --repeat 5

hr "3/5  DEMO 1b · 主权边界（无文字图 → 只有云端能答 → 拒绝）"
uv run python scripts/demo_look.py --image samples/presence_a.jpg --question "这是什么？" --repeat 1
say "  服务返回 428：本地引擎答不了，而出境没被授权。这次拒绝也会进审计。"

hr "4/5  DEMO 2 · 角色间接（同一能力，两个 perceptor）"
say "  a) presence 由【设备】判定 —— burst 里一张图都没有"
uv run python scripts/demo_presence.py --mode device
say "  切换 EIDOLON_VISION_PRESENCE_SOURCE=host，重启，能力代码零改动…"
kill "$SERVER_PID" 2>/dev/null || true; sleep 1
EIDOLON_VISION_HUB_BASE_URL="" \
EIDOLON_VISION_ENABLED_CAPABILITIES='["look_on_demand","presence_verify","fatigue"]' \
EIDOLON_VISION_PRESENCE_SOURCE=host \
EIDOLON_VISION_AUDIT_LOG_PATH=var/audit.jsonl \
EIDOLON_VISION_HUB_PUBLIC_KEY="$PUBKEY" \
  uv run uvicorn 'eidolon_vision.app.http:create_app' \
  --factory --port "$PORT" --host 127.0.0.1 >> var/server.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > var/server.pid
for _ in $(seq 1 60); do curl -sf "$BASE/healthz" >/dev/null && break; sleep 0.5; done
say "  b) presence 由【宿主】判定 —— 帧差，需要真的上传两帧"
uv run python scripts/demo_presence.py --mode host
say "  fact 在同一轮触发，frames_in 从 0 变成 2。这就是全部区别。"

hr "5/5  DEMO 3 · 能力可删"
uv run python scripts/demo_removable.py

hr "审计日志（主权承诺，可读）"
curl -s "$BASE/v1/audit?limit=30" | uv run python scripts/show_audit.py

if [[ "$KEEP" == "1" ]]; then
  hr "服务仍在运行"
  cat <<EOF
  交互入口：
    ${BASE}/docs          Swagger UI，可以直接上传你自己的照片试 /v1/look
    ${BASE}/v1/audit      审计日志（JSON）
    ${BASE}/healthz       当前装配：能力、触发器、绑定的角色、引擎链

  用你自己的图：
    uv run python scripts/demo_look.py --image ~/Desktop/你的照片.jpg --question "这上面写的什么？"

  停止：
    kill \$(cat var/server.pid)
EOF
else
  hr "完成（服务已停；加 --keep 可保留）"
fi
