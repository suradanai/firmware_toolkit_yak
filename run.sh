#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  echo "ไม่พบ venv: .venv (รัน ./fw-manager.sh install ก่อน)" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$SCRIPT_DIR/.venv/bin/activate"
exec python app.py "$@"
