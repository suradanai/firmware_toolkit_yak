#!/usr/bin/env bash
#
# run-gui.sh
#
# Smart launcher สำหรับ GUI (PySide6) ของโครงการ Firmware Workbench
#
# คุณสมบัติ:
#  - ตรวจและสร้าง virtualenv อัตโนมัติ (หากไม่มี)
#  - ติดตั้ง dependencies จาก requirements.txt (ถ้าจำเป็น)
#  - ค้นหาไฟล์/โมดูล GUI อัตโนมัติ (heuristic) ถ้าไม่ระบุ
#  - รองรับการรันแบบ: โมดูล (-m) หรือไฟล์ (python path/to/gui.py)
#  - ส่ง argument เพิ่มเติมไปยังแอป GUI ได้
#  - สามารถสั่ง extract firmware ก่อนเปิด GUI (--extract)
#  - แสดงรายการ workspaces (--list-workspaces)
#  - อัปเดต FMK (--update-fmk)
#
# Usage (พื้นฐาน):
#   ./run-gui.sh
#
# Usage (ระบุ firmware ให้ extract ก่อน แล้วค่อยเปิด GUI):
#   ./run-gui.sh --extract input/firmware.bin
#
# Usage (ระบุโมดูล GUI เอง):
#   ./run-gui.sh --module firmware_workbench.gui
#
# Usage (ระบุไฟล์ GUI เอง):
#   ./run-gui.sh --file gui.py
#
# Advanced:
#   ./run-gui.sh --venv-dir .venv --python python3.12 --debug --workspace workspaces/auto_v2_2025XXXXXX
#
# Options:
#   --venv-dir DIR          ชื่อโฟลเดอร์ virtualenv (default: .venv)
#   --python PY             Python interpreter (default: python)
#   --no-create-venv        ไม่สร้าง venv ถ้าไม่มี (error หากไม่พบ)
#   --reinstall-reqs        ติดตั้ง requirements.txt ซ้ำ (บังคับ)
#   --module MOD            ใช้ python -m MOD ในการรัน (เช่น firmware_workbench.gui)
#   --file FILE             ใช้ไฟล์สคริปต์ GUI (เช่น gui.py)
#   --args "..."            ส่ง arguments ใส่ GUI main (เช่น "--workspace X --debug")
#   --workspace PATH        ส่งเป็น --workspace ให้ GUI (ถ้าโค้ดรองรับ)
#   --debug                 เพิ่ม --debug ให้ GUI (ถ้าโค้ดรองรับ)
#   --extract FW            เรียก ./fw-manager.sh extract FW ก่อนเปิด GUI
#   --include-kernel        ใช้กับ --extract ให้ fallback carve รวม kernel
#   --update-fmk            เรียก ./fw-manager.sh install ก่อน
#   --list-workspaces       แสดง 10 workspace ล่าสุดแล้วออก
#   --install-deps          บังคับติดตั้ง requirements (เหมือน --reinstall-reqs)
#   --skip-deps             ข้ามตรวจ dependencies (เชื่อว่าพร้อมแล้ว)
#   --env-only              เตรียมสภาพแวดล้อมแล้วไม่เปิด GUI
#   --dry-run               แสดงคำสั่งที่จะรันแต่ไม่ execute
#   --help                  แสดงข้อความช่วยเหลือ
#
# Return codes:
#   0 success
#   1 generic error / missing resource
#   2 no GUI entry found
#
set -euo pipefail

# ---------------- Configuration Defaults ----------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR=".venv"
PYTHON="python"
CREATE_VENV=1
REINSTALL_REQS=0
SKIP_DEPS=0
ENV_ONLY=0
DRY_RUN=0
INSTALL_DESKTOP=0

GUI_MODULE=""       # ถ้า set จะใช้ python -m
GUI_FILE=""         # ถ้า set จะใช้ python FILE
GUI_ARGS=""
WORKSPACE_ARG=""
DEBUG_ARG=0
DO_EXTRACT=0
EXTRACT_FW=""
INCLUDE_KERNEL=0
UPDATE_FMK=0
LIST_WS=0

FW_MANAGER="$PROJECT_ROOT/fw-manager.sh"
REQ_FILE="$PROJECT_ROOT/requirements.txt"

# ---------------- Helper Functions ----------------
log() { printf "[RUN-GUI] %s\n" "$*"; }
err() { printf "[ERROR] %s\n" "$*" >&2; exit 1; }

usage() {
  sed -n '1,120p' "$0" | grep -E '^#' | sed 's/^# \{0,1\}//'
  exit 0
}

install_desktop_entry() {
  local desktop_src="$PROJECT_ROOT/FirmwareWorkbench.desktop"
  local desktop_target="$HOME/.local/share/applications/FirmwareWorkbench.desktop"
  if [ ! -f "$desktop_src" ]; then
    log "Desktop file not found: $desktop_src"; return 1
  fi
  mkdir -p "$(dirname "$desktop_target")"
  cp "$desktop_src" "$desktop_target"
  chmod 644 "$desktop_target"
  # Ensure icon installed (block already later will also do) but do here for clarity
  local icon_src="$PROJECT_ROOT/icons/firmware_toolkit_yak.svg"
  local icon_dest="$HOME/.local/share/icons/hicolor/scalable/apps/firmware_toolkit_yak.svg"
  if [ -f "$icon_src" ]; then
    mkdir -p "$(dirname "$icon_dest")"; cp "$icon_src" "$icon_dest" 2>/dev/null || true
  fi
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
  log "Installed desktop entry -> appears in menu after refresh/login: $desktop_target"
}

run_cmd() {
  if [ $DRY_RUN -eq 1 ]; then
    echo "(dry-run) $*"
  else
    eval "$@"
  fi
}

detect_gui_entry() {
  # หากผู้ใช้กำหนดไว้แล้ว ไม่ต้องตรวจ
  if [ -n "$GUI_MODULE" ] || [ -n "$GUI_FILE" ]; then
    return 0
  fi

  # Heuristic: ลองหาไฟล์ที่มี QApplication หรือ QMainWindow
  local candidates
  # จำกัดความลึก 3 ระดับ เพื่อลด noise
  mapfile -t candidates < <(grep -RIl --include="*.py" -E "QApplication|QMainWindow" "$PROJECT_ROOT" 2>/dev/null | head -n 10 || true)

  for f in "${candidates[@]}"; do
    # ข้ามไฟล์ใน .venv / external
    if [[ "$f" == *"/$VENV_DIR/"* ]] || [[ "$f" == *"/external/"* ]]; then
      continue
    fi
    # ถ้ามี if __name__ == "__main__" ถือว่าเป็นไฟล์ runnable
    if grep -q '__main__' "$f"; then
      GUI_FILE="$f"
      log "Auto-detected GUI file: $GUI_FILE"
      return 0
    fi
  done

  # ถ้าไม่เจอไฟล์ ลองมองหาโมดูลที่อาจเป็นมาตรฐาน
  if [ -d "$PROJECT_ROOT/firmware_workbench" ]; then
    if [ -f "$PROJECT_ROOT/firmware_workbench/gui.py" ]; then
      GUI_MODULE="firmware_workbench.gui"
      log "Auto-detected GUI module: $GUI_MODULE"
      return 0
    fi
    if [ -f "$PROJECT_ROOT/firmware_workbench/main.py" ]; then
      GUI_MODULE="firmware_workbench.main"
      log "Auto-detected GUI module: $GUI_MODULE"
      return 0
    fi
  fi

  # Fallback: root-level app.py (current project style)
  if [ -f "$PROJECT_ROOT/app.py" ]; then
    if grep -q "QApplication" "$PROJECT_ROOT/app.py" 2>/dev/null && grep -q "__main__" "$PROJECT_ROOT/app.py" 2>/dev/null; then
      GUI_FILE="$PROJECT_ROOT/app.py"
      log "Fallback detected GUI file: $GUI_FILE"
      return 0
    fi
    # even without __main__, still allow as last resort
    if grep -q "QApplication" "$PROJECT_ROOT/app.py" 2>/dev/null; then
      GUI_FILE="$PROJECT_ROOT/app.py"
      log "Fallback (no __main__ guard) GUI file: $GUI_FILE"
      return 0
    fi
  fi

  return 2
}

prepare_venv() {
  if [ $CREATE_VENV -eq 0 ] && [ ! -d "$VENV_DIR" ]; then
    err "Virtualenv '$VENV_DIR' missing and --no-create-venv was given."
  fi
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtualenv: $VENV_DIR (python=$PYTHON)"
    run_cmd "$PYTHON -m venv \"$VENV_DIR\""
  else
    log "Using existing virtualenv: $VENV_DIR"
  fi
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
}

install_requirements() {
  if [ $SKIP_DEPS -eq 1 ]; then
    log "Skipping dependency installation (--skip-deps)"
    return
  fi
  if [ ! -f "$REQ_FILE" ]; then
    log "No requirements.txt found. Skipping base deps."
  else
    if [ $REINSTALL_REQS -eq 1 ]; then
      log "Reinstalling requirements (forced)..."
      run_cmd "pip install --upgrade pip"
      run_cmd "pip install -r \"$REQ_FILE\" --force-reinstall"
    else
      # ตรวจง่าย ๆ ว่า PySide6 มีไหม ถ้าไม่มีให้ติดตั้งทั้งชุด
      if python -c "import PySide6" 2>/dev/null; then
        log "PySide6 already present -> skip bulk install (use --reinstall-reqs to force)."
      else
        log "Installing requirements from $REQ_FILE ..."
        run_cmd "pip install --upgrade pip"
        run_cmd "pip install -r \"$REQ_FILE\""
      fi
    fi
  fi
}

do_update_fmk() {
  [ $UPDATE_FMK -eq 1 ] || return 0
  if [ ! -x "$FW_MANAGER" ]; then
    err "fw-manager.sh not found (expected at $FW_MANAGER)"
  fi
  log "Updating FMK via fw-manager.sh install ..."
  run_cmd "\"$FW_MANAGER\" install"
}

do_extract_firmware() {
  [ $DO_EXTRACT -eq 1 ] || return 0
  [ -n "$EXTRACT_FW" ] || err "--extract specified but no firmware path captured"
  if [ ! -x "$FW_MANAGER" ]; then
    err "fw-manager.sh missing - cannot extract"
  fi
  if [ ! -f "$EXTRACT_FW" ]; then
    err "Firmware file not found: $EXTRACT_FW"
  fi
  local cmd="\"$FW_MANAGER\" extract \"$EXTRACT_FW\""
  if [ $INCLUDE_KERNEL -eq 1 ]; then
    # fallback carve v2 จะ include kernel อยู่แล้วเมื่อเรียกผ่าน fw-manager (เราไม่ต้องเพิ่ม flag)
    log "Extraction requested (kernel will be included by fallback)."
  fi
  log "Extracting firmware before GUI start..."
  run_cmd "$cmd"
}

list_workspaces() {
  [ $LIST_WS -eq 1 ] || return 0
  log "Listing recent workspaces (max 10):"
  #  เรียงตามเวลาสร้าง (ls -t); max 10
  ls -1t "$PROJECT_ROOT/workspaces" 2>/dev/null | head -n 10 || true
  exit 0
}

build_gui_command() {
  local python_exec="$PROJECT_ROOT/$VENV_DIR/bin/python"
  [ -x "$python_exec" ] || python_exec="python"

  local args=""
  if [ -n "$WORKSPACE_ARG" ]; then
    args+=" --workspace \"$WORKSPACE_ARG\""
  fi
  if [ $DEBUG_ARG -eq 1 ]; then
    args+=" --debug"
  fi
  if [ -n "$GUI_ARGS" ]; then
    args+=" $GUI_ARGS"
  fi

  if [ -n "$GUI_MODULE" ]; then
    echo "\"$python_exec\" -m \"$GUI_MODULE\" $args"
  elif [ -n "$GUI_FILE" ]; then
    echo "\"$python_exec\" \"$GUI_FILE\" $args"
  else
    err "No GUI module or file set (internal error)."
  fi
}

# ---------------- Parse Arguments ----------------
while (( $# )); do
  case "$1" in
    --venv-dir) VENV_DIR="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --no-create-venv) CREATE_VENV=0; shift ;;
    --reinstall-reqs|--install-deps) REINSTALL_REQS=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --module) GUI_MODULE="$2"; shift 2 ;;
    --file) GUI_FILE="$2"; shift 2 ;;
    --args) GUI_ARGS="$2"; shift 2 ;;
    --workspace) WORKSPACE_ARG="$2"; shift 2 ;;
    --debug) DEBUG_ARG=1; shift ;;
    --extract) DO_EXTRACT=1; EXTRACT_FW="$2"; shift 2 ;;
    --include-kernel) INCLUDE_KERNEL=1; shift ;;
    --update-fmk) UPDATE_FMK=1; shift ;;
    --list-workspaces) LIST_WS=1; shift ;;
  --install-desktop) INSTALL_DESKTOP=1; shift ;;
    --env-only) ENV_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage ;;
    --) shift; break ;;
    *) err "Unknown option: $1" ;;
  esac
done

# ---------------- Main Flow ----------------
list_workspaces
if [ $INSTALL_DESKTOP -eq 1 ]; then
  install_desktop_entry || true
fi
prepare_venv
install_requirements
do_update_fmk
do_extract_firmware

if [ $ENV_ONLY -eq 1 ]; then
  log "--env-only specified: environment prepared; not launching GUI."
  exit 0
fi

if ! detect_gui_entry; then
  rc=$?
  if [ $rc -eq 2 ]; then
    err "ไม่พบ entry point GUI อัตโนมัติ (ลองใช้ --module หรือ --file)"
  else
    err "GUI detection failed (rc=$rc)"
  fi
fi

CMD="$(build_gui_command)"

log "Launching GUI..."
# Install icon to user icon theme if missing (so .desktop Icon=firmware_toolkit_yak works)
ICON_SRC="$PROJECT_ROOT/icons/firmware_toolkit_yak.svg"
ICON_DEST="$HOME/.local/share/icons/hicolor/scalable/apps/firmware_toolkit_yak.svg"
if [ -f "$ICON_SRC" ] && [ ! -f "$ICON_DEST" ]; then
  log "Installing user icon: $ICON_DEST"
  mkdir -p "$(dirname "$ICON_DEST")"
  cp "$ICON_SRC" "$ICON_DEST" || true
  # refresh icon cache if available
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
fi
if [ $DRY_RUN -eq 1 ]; then
  echo "(dry-run only) $CMD"
else
  eval "$CMD"
fi