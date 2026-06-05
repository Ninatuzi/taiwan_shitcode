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

# ---- 顯示本地模型設定（可用環境變數覆蓋）----
echo "本地模型： ${LLM_MODEL:-DeepSeek_32B_f16} @ ${LLM_BASE_URL:-http://10.0.6.89:8080/v1}"
echo "（如需更換：export LLM_BASE_URL=... / LLM_MODEL=... 再啟動）"

# ---- 檢查前端是否已建置 ----
if [ ! -f "frontend/dist/index.html" ]; then
  echo "[WARN] 找不到 frontend/dist，前端尚未建置。請先： cd frontend && pnpm build"
  echo "       （或重跑 bash setup.sh）"
fi

echo "啟動後端： http://${HOST}:${PORT}  （遠端請用 http://<伺服器IP>:${PORT} 存取）"
exec ./venv-ai/bin/uvicorn backend.main:app --host "$HOST" --port "$PORT"
