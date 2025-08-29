#!/usr/bin/env bash
#
# fw-manager.sh (patched for multi-squash /logs issue)
#
# Commands:
#   install | update
#   extract <firmware>
#   help
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FMK_ROOT="${FMK_ROOT:-$PROJECT_ROOT/external/firmware_mod_kit}"
CARVE_V2="$PROJECT_ROOT/scripts/extract_multi_auto_v2.sh"
CARVE_V1="$PROJECT_ROOT/scripts/extract_multi_auto.sh"

STRICT_MULTI="${STRICT_MULTI:-0}"   # ถ้า =1 จะไม่พยายาม single/fallback (เพื่อ debug multi)
LOG_PREFIX="[FW-MGR]"

log(){ printf "%s %s\n" "$LOG_PREFIX" "$*" >&2; }
die(){ log "ERROR: $*"; exit 1; }

sanitize_firmware_path() {
  local orig="$1"
  [ -f "$orig" ] || die "Firmware not found: $orig"
  if [[ "$orig" =~ [[:space:]] ]]; then
    mkdir -p "$PROJECT_ROOT/input_sanitized"
    local base="$(basename "$orig")"
    local safe="$PROJECT_ROOT/input_sanitized/${base// /_}"
    if [ ! -f "$safe" ]; then
      cp -- "$orig" "$safe"
      log "Sanitized copy -> $safe"
    fi
    printf "%s" "$safe"
  else
    printf "%s" "$orig"
  fi
}

clone_or_update_fmk() {
  if [ -d "$FMK_ROOT/.git" ]; then
    log "Updating FMK..."
    git -C "$FMK_ROOT" pull --ff-only || log "FMK pull failed (continuing)"
  else
    log "Cloning FMK into $FMK_ROOT ..."
    mkdir -p "$(dirname "$FMK_ROOT")"
    git clone --depth=1 https://github.com/rampageX/firmware-mod-kit.git "$FMK_ROOT"
  fi
}

run_fmk_multi() {
  local fw="$1" ws_abs="$2"
  ( cd "$FMK_ROOT" && \
    log "RUN: $FMK_ROOT/extract-multisquashfs-firmware.sh $fw $ws_abs" && \
    ./extract-multisquashfs-firmware.sh "$fw" "$ws_abs" )
}

run_fmk_single() {
  local fw="$1" ws_abs="$2"
  ( cd "$FMK_ROOT" && \
    log "RUN: $FMK_ROOT/extract-firmware.sh $fw $ws_abs" && \
    ./extract-firmware.sh "$fw" "$ws_abs" )
}

detect_logs_bug() {
  # ถ้าในการรัน multi มันพยายามสร้าง /logs หรือ error message เดิม ให้ return 0
  local errlog="$1"
  grep -q "/logs/binwalk.log" "$errlog" && return 0 || return 1
}

fallback_extract() {
  local fw="$1" ws_abs="$2"
  if [ -x "$CARVE_V2" ]; then
    log "Fallback: carve v2 (include kernel by default)"
    "$CARVE_V2" "$fw" --out "${ws_abs}_carve" --include-kernel || return 1
    return 0
  elif [ -x "$CARVE_V1" ]; then
    log "Fallback: carve v1"
    "$CARVE_V1" "$fw" "${ws_abs}_carve" || return 1
    return 0
  fi
  log "No fallback scripts found."
  return 1
}

do_extract() {
  local fw="$1"
  local sanitized
  sanitized="$(sanitize_firmware_path "$fw")"
  local ws_rel="workspaces/ws_$(date +%Y%m%d_%H%M%S)"
  local ws_abs
  ws_abs="$(realpath -m "$PROJECT_ROOT/$ws_rel")"
  mkdir -p "$ws_abs"  # create output root early

  log "Attempt multi-squash via FMK -> $ws_abs"
  local multi_err
  multi_err="$(mktemp)"
  if run_fmk_multi "$sanitized" "$ws_abs" 2>&1 | tee "$multi_err"; then
    log "FMK multi success"
    rm -f "$multi_err"
    return 0
  else
    if detect_logs_bug "$multi_err"; then
      log "Detected /logs path bug in FMK multi script."
      log "Suggestion: open $FMK_ROOT/extract-multisquashfs-firmware.sh and ensure it constructs LOG path with output dir."
    fi
    if [ "$STRICT_MULTI" = "1" ]; then
      die "STRICT_MULTI=1 set; aborting after multi failure for debugging"
    fi
  fi
  rm -f "$multi_err"

  log "Multi failed, try single..."
  if run_fmk_single "$sanitized" "$ws_abs"; then
    log "FMK single success"
    return 0
  fi

  log "FMK extraction failed -> fallback path"
  if fallback_extract "$sanitized" "$ws_abs"; then
    log "Fallback carve completed."
    return 0
  fi

  die "All extraction methods failed."
}

usage() {
  cat <<EOF
Firmware Manager
Usage: $0 <command> [args]

Commands:
  install               Clone/Update FMK
  update                Same as install
  extract <firmware>    Extract with FMK + fallback
  help                  Show this help

Environment:
  FMK_ROOT        Override FMK path (current: $FMK_ROOT)
  STRICT_MULTI=1  Stop immediately if multi-squash fails (debug)
EOF
}

cmd="${1:-help}"
case "$cmd" in
  install|update)
    clone_or_update_fmk
    ;;
  extract)
    shift
    [ $# -ge 1 ] || die "extract requires <firmware>"
    clone_or_update_fmk
    do_extract "$1"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage; exit 1 ;;
esac