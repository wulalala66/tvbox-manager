#!/usr/bin/env bash
# TVBox Manager 一键启动（后端 8000 + 前端构建产物托管）
cd "$(dirname "$0")"

# 构建前端（如无 dist）
if [ ! -f frontend/dist/index.html ]; then
  echo "[*] 构建前端..."
  (cd frontend && npx vite build) || exit 1
fi

echo "[*] 启动后端 http://127.0.0.1:8000 （含前端托管）"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --app-dir backend --log-level warning
