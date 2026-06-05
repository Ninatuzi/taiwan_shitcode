#!/usr/bin/env bash
# ============================================================
#  BMS FW Validation - Linux 啟動腳本（伺服器/生產模式）
#  作用：用 uvicorn 跑後端，並由後端託管已建置的前端 (dist)
#  存取：瀏覽器開 http://<伺服器IP>:7003
#  用法：  ANTHROPIC_API_KEY=你的key bash start.sh
#          或先 export ANTHROPIC_API_KEY=... 再 bash start.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-7003}"
HOST="${HOST:-0.0.0.0}"

# ---- 找 uvicorn：優先用當前已啟用的 venv，否則自動偵測常見 venv 目錄 ----
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/uvicorn" ]; then
  UVICORN="${VIRTUAL_ENV}/bin/uvicorn"
else
  UVICORN=""
  for d in venv-ai .venv venv taiwan_1 env; do
    if [ -x "$d/bin/uvicorn" ]; then UVICORN="$d/bin/uvicorn"; break; fi
  done
  if [ -z "$UVICORN" ] && command -v uvicorn >/dev/null 2>&1; then
    UVICORN="$(command -v uvicorn)"
  fi
fi
if [ -z "$UVICORN" ]; then
  echo "[ERROR] 找不到 uvicorn。請先建立並啟用虛擬環境，或執行： bash setup.sh"
  echo "        若已建好其他名稱的 venv，請先 source <venv>/bin/activate 再執行本腳本。"
  exit 1
fi
echo "        使用 uvicorn: $UVICORN"

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
exec "$UVICORN" backend.main:app --host "$HOST" --port "$PORT"
