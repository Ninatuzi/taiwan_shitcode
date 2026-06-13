#!/usr/bin/env bash
# ============================================================
#  BMS FW Validation - Linux 一鍵環境建置 (setup_env.bat 的 Linux 版)
#  作用：建立 Python venv、安裝後端套件、安裝並建置前端
#  用法：  bash setup.sh
# ============================================================
set -euo pipefail

# 切換到本腳本所在目錄（即「原始碼」目錄），確保相對路徑正確
cd "$(dirname "$0")"

echo "============================================"
echo " BMS FW Validation - 環境建置 (Linux)"
echo "============================================"

# ---- 1. 找 Python 3.10+ ----
PYEXE=""
for v in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$v" >/dev/null 2>&1; then
    if "$v" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1; then
      PYEXE="$v"; break
    fi
  fi
done
if [ -z "$PYEXE" ]; then
  echo "[ERROR] 找不到 Python 3.10+，請先安裝（apt install python3 python3-venv，或用 pyenv）。"
  exit 1
fi
echo "        使用 Python: $PYEXE ($("$PYEXE" --version))"

# ---- 2. 建立虛擬環境 ----
echo "[1/4] 建立虛擬環境 venv-ai ..."
if [ -x "venv-ai/bin/python" ]; then
  echo "        venv-ai 已存在，略過。"
else
  "$PYEXE" -m venv venv-ai
fi

# ---- 3. 安裝後端套件（用 Linux 精簡版需求檔）----
echo "[2/4] 安裝 Python 套件 (requirements-linux.txt) ..."
./venv-ai/bin/python -m pip install --upgrade pip
./venv-ai/bin/python -m pip install -r requirements-linux.txt

# ---- 4. 檢查 Node / pnpm ----
echo "[3/4] 檢查 Node.js / pnpm ..."
if ! command -v pnpm >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] 找不到 Node.js / npm，請先安裝 Node.js（https://nodejs.org/）後重跑。"
    exit 1
  fi
  echo "        未發現 pnpm，透過 npm 安裝中 ..."
  npm install -g pnpm
fi

# ---- 5. 安裝並建置前端 ----
echo "[4/4] 安裝前端套件並建置 (pnpm install && pnpm build) ..."
( cd frontend && pnpm install && pnpm build )

echo
echo "============================================"
echo " 環境建置完成！"
echo " 下一步：設定金鑰後執行 ./start.sh"
echo "   export ANTHROPIC_API_KEY=你的key"
echo "   bash start.sh"
echo "============================================"
