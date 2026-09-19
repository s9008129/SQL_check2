#!/usr/bin/env bash
# SQLCheck AI — Mac local development (no Docker / no local model required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # .env is intentionally a simple KEY=VALUE file in this project.
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export SQLCHECK_LLM_PROVIDER="${SQLCHECK_LLM_PROVIDER:-ollama_cloud}"
export SQLCHECK_ARCHIVE_DIR="${SQLCHECK_ARCHIVE_DIR:-data/sql_archive}"
export SQLCHECK_ARCHIVE_ENABLED="${SQLCHECK_ARCHIVE_ENABLED:-true}"

if [[ "$SQLCHECK_LLM_PROVIDER" == "ollama_cloud" && -z "${OLLAMA_API_KEY:-}" ]]; then
  cat <<'EOF'
Ollama Cloud API Key 尚未設定。

請先：
  cp .env.mac.example .env
然後編輯 .env，填入：
  OLLAMA_API_KEY=你的金鑰

API Key 可在 https://ollama.com/settings/keys 建立。
.env 已被 Git 忽略，不會 commit 到 Repo。
EOF
  exit 2
fi

if [[ "$SQLCHECK_LLM_PROVIDER" == "gemini" && -z "${GEMINI_API_KEY:-}" ]]; then
  cat <<'EOF'
Gemini API Key 尚未設定。
請在 .env 設定 GEMINI_API_KEY。
EOF
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "找不到 uv。請先安裝 uv 後再執行。" >&2
  exit 2
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "找不到 npm / Node.js。請先安裝 Node.js 22+。" >&2
  exit 2
fi

echo "[1/4] 同步 Python 依賴..."
(
  cd "$BACKEND"
  uv sync --group dev
)

echo "[2/4] 同步前端依賴..."
(
  cd "$FRONTEND"
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
)

mkdir -p "$ROOT/data/sql_archive"

cleanup() {
  status=$?
  trap - INT TERM EXIT
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$status"
}
trap cleanup INT TERM EXIT

echo "[3/4] 啟動 FastAPI :8000（provider=${SQLCHECK_LLM_PROVIDER}）..."
(
  cd "$BACKEND"
  uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

echo "[4/4] 啟動 Vite :5173..."
(
  cd "$FRONTEND"
  npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

cat <<EOF

SQLCheck Mac 開發環境已啟動
  網頁:   http://127.0.0.1:5173
  API:    http://127.0.0.1:8000/api/health
  LLM:    $SQLCHECK_LLM_PROVIDER
  Archive: $ROOT/data/sql_archive

按 Ctrl+C 結束。
EOF

wait "$BACKEND_PID" "$FRONTEND_PID"
