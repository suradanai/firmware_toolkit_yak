#!/usr/bin/env bash
#
# firmware_setup.sh
#
# One-touch provisioning script for the firmware workbench.
#
# Functions:
#   - (Optional) Create / refresh Python virtualenv
#   - Install Python requirements + jefferson
#   - Install system packages (binwalk, unsquashfs, etc.)
#   - Copy firmware into ./input/ (sanitizing spaces)
#   - Update FMK
#   - Execute extraction (FMK → fallback carve v2)
#
# Usage:
#   ./firmware_setup.sh --firmware /absolute/path/to/fw.bin [options]
#
# Options:
#   --firmware <file>       (Required unless --no-extract) path to firmware
#   --venv-name <dir>       virtualenv directory (default .venv)
#   --python <exe>          python interpreter (default python)
#   --no-venv               skip creating/activating venv
#   --refresh-venv          delete venv first then recreate
#   --no-system             skip apt package installation
#   --no-fmk                skip FMK clone/update
#   --no-extract            skip extraction phase
#   --include-kernel        pass --include-kernel to carve v2 fallback
#   --pad-squash <bytes>    override SquashFS padding (default 65536)
#   --force                 overwrite existing input/firmware.bin
#   --help                  show this help
#
# Exit codes:
#   0 success
#   1 generic error
#   2 missing firmware
#
set -euo pipefail

PYTHON="python"
VENV_DIR=".venv"
DO_VENV=1
REFRESH_VENV=0
DO_SYSTEM=1
DO_FMK=1
DO_EXTRACT=1
FIRMWARE_SRC=""
FORCE=0
INCLUDE_KERNEL=0
PAD_SQUASH=65536

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_DIR="$PROJECT_ROOT/input"
FW_MANAGER="$PROJECT_ROOT/fw-manager.sh"
CARVE_V2="$PROJECT_ROOT/scripts/extract_multi_auto_v2.sh"

APT_PACKAGES=(binwalk squashfs-tools p7zip-full sleuthkit)
PIP_EXTRA_PACKAGES=(jefferson)

log(){ printf "[SETUP] %s\n" "$*"; }
err(){ printf "[ERROR] %s\n" "$*" >&2; exit 1; }

usage(){
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//'
  exit 0
}

have_cmd(){ command -v "$1" >/dev/null 2>&1; }

parse_args() {
  while (( $# )); do
    case "$1" in
      --firmware) FIRMWARE_SRC="$2"; shift 2 ;;
      --venv-name) VENV_DIR="$2"; shift 2 ;;
      --python) PYTHON="$2"; shift 2 ;;
      --no-venv) DO_VENV=0; shift ;;
      --refresh-venv) REFRESH_VENV=1; shift ;;
      --no-system) DO_SYSTEM=0; shift ;;
      --no-fmk) DO_FMK=0; shift ;;
      --no-extract) DO_EXTRACT=0; shift ;;
      --include-kernel) INCLUDE_KERNEL=1; shift ;;
      --pad-squash) PAD_SQUASH="$2"; shift 2 ;;
      --force) FORCE=1; shift ;;
      --help|-h) usage ;;
      --) shift; break ;;
      *) err "Unknown option: $1" ;;
    esac
  done
}

create_venv() {
  [ $DO_VENV -eq 1 ] || { log "Skip venv (--no-venv)"; return; }
  if [ $REFRESH_VENV -eq 1 ] && [ -d "$VENV_DIR" ]; then
    log "Removing existing venv $VENV_DIR"
    rm -rf "$VENV_DIR"
  fi
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating venv $VENV_DIR (python=$PYTHON)"
    "$PYTHON" -m venv "$VENV_DIR"
  else
    log "Using existing venv $VENV_DIR"
  fi
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  log "Python: $(python -V)"
}

install_python_reqs() {
  if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    log "pip install -r requirements.txt"
    pip install -r "$PROJECT_ROOT/requirements.txt"
  else
    log "No requirements.txt found – skipping base packages."
  fi
  for pkg in "${PIP_EXTRA_PACKAGES[@]}"; do
    python -c "import $pkg" 2>/dev/null || {
      log "Installing extra Python pkg: $pkg"
      pip install "$pkg"
    }
  done
}

install_system() {
  [ $DO_SYSTEM -eq 1 ] || { log "Skip apt install (--no-system)"; return; }
  have_cmd sudo || err "sudo not found; cannot install system packages."
  log "apt update"
  sudo apt update -y
  log "apt install: ${APT_PACKAGES[*]}"
  sudo apt install -y "${APT_PACKAGES[@]}"
}

stage_firmware() {
  [ $DO_EXTRACT -eq 1 ] || { log "Skip firmware staging (--no-extract)"; return; }
  [ -n "$FIRMWARE_SRC" ] || err "Provide --firmware path"
  [ -f "$FIRMWARE_SRC" ] || err "Firmware not found: $FIRMWARE_SRC"
  mkdir -p "$INPUT_DIR"
  local base="$(basename "$FIRMWARE_SRC")"
  local dest="$INPUT_DIR/${base// /_}"
  if [ -f "$dest" ] && [ $FORCE -ne 1 ]; then
    log "Firmware already exists at $dest (use --force to overwrite)"
  else
    cp -f -- "$FIRMWARE_SRC" "$dest"
    log "Firmware copied -> $dest"
  fi
  echo "$dest"
}

update_fmk() {
  [ $DO_FMK -eq 1 ] || { log "Skip FMK (--no-fmk)"; return; }
  [ -x "$FW_MANAGER" ] || err "fw-manager.sh not found or not executable"
  "$FW_MANAGER" install || log "FMK install returned non-zero (ignored)"
}

run_extract() {
  [ $DO_EXTRACT -eq 1 ] || { log "Extraction disabled"; return; }
  local firmware="$1"
  local extra=()
  if [ $INCLUDE_KERNEL -eq 1 ]; then
    extra+=(--include-kernel)
  fi
  # fw-manager fallback will use v2 if present already, so we just call it:
  if [ -x "$FW_MANAGER" ]; then
    log "Running fw-manager extract ..."
    "$FW_MANAGER" extract "$firmware" || log "fw-manager extract had non-zero exit"
  else
    log "fw-manager missing; direct call v2"
    [ -x "$CARVE_V2" ] || err "carve v2 script missing"
    "$CARVE_V2" "$firmware" --pad-squash "$PAD_SQUASH" "${extra[@]}"
  fi
}

summary() {
  echo
  log "==== SUMMARY ===="
  log "Firmware source: $FIRMWARE_SRC"
  log "Venv dir:        $VENV_DIR (active? ${VIRTUAL_ENV:+yes}${VIRTUAL_ENV:-no})"
  log "System pkgs:     $DO_SYSTEM"
  log "FMK updated:     $DO_FMK"
  log "Extraction run:  $DO_EXTRACT"
  log "Include kernel:  $INCLUDE_KERNEL"
  log "Squash pad:      $PAD_SQUASH"
  log "Input dir:       $INPUT_DIR"
  log "Workspaces:      $(ls -1 "$PROJECT_ROOT/workspaces" 2>/dev/null | wc -l || true) entries"
  log "================="
}

main() {
  parse_args "$@"
  create_venv
  install_python_reqs
  install_system
  local firmware_local=""
  if [ $DO_EXTRACT -eq 1 ]; then
    firmware_local="$(stage_firmware)"
  fi
  update_fmk
  if [ $DO_EXTRACT -eq 1 ]; then
    run_extract "$firmware_local"
  fi
  summary
}

main "$@"