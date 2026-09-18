#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi
source .venv/bin/activate

pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo ".env 파일이 없습니다. .env.example을 복사해 API 키를 설정하세요." >&2
fi

uvicorn src.app:app --reload --port 8000
