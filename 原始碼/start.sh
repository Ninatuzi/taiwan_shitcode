#!/usr/bin/env bash
# ============================================================
#  BMS FW Validation - Linux 啟動腳本（伺服器/生產模式）
#  作用：用 uvicorn 跑後端，並由後端託管已建置的前端 (dist)
#  存取：瀏覽器開 http://<伺服器IP>:8000
#  用法：  ANTHROPIC_API_KEY=你的key bash start.sh
#          或先 export ANTHROPIC_API_KEY=... 再 bash start.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# ---- 檢查 venv ----
if [ ! -x "venv-ai/bin/uvicorn" ]; then
  echo "[ERROR] 找不到 venv-ai，請先執行： bash setup.sh"
  exit 1
fi

# ---- 載入同目錄 .env（若存在）----
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# ---- 檢查金鑰 ----
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "[WARN] 未設定 ANTHROPIC_API_KEY，生成功能會失敗。"
  echo "       請 export ANTHROPIC_API_KEY=你的key，或在本目錄建立 .env 寫入該變數。"
fi

# ---- 檢查前端是否已建置 ----
if [ ! -f "frontend/dist/index.html" ]; then
  echo "[WARN] 找不到 frontend/dist，前端尚未建置。請先： cd frontend && pnpm build"
  echo "       （或重跑 bash setup.sh）"
fi

echo "啟動後端： http://${HOST}:${PORT}  （遠端請用 http://<伺服器IP>:${PORT} 存取）"
exec ./venv-ai/bin/uvicorn backend.main:app --host "$HOST" --port "$PORT"
