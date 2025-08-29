#!/usr/bin/env bash
#
# repack_rootfs.sh
#
# Purpose:
#   Rebuild a modified SquashFS rootfs and inject it back into the original firmware image
#   at a known offset (in-place modification).
#
# Workflow:
#   1. You extracted rootfs (e.g., rootfs_1 directory) from original image
#   2. You modified its contents
#   3. Provide:
#       --rootfs-dir <dir>        (the modified rootfs directory)
#       --orig-fw <file>          (original firmware file)
#       --offset 0xOFFSET         (hex offset where original rootfs started)
#       --partition-size 0xSIZE   (optional: size boundary/padding to preserve layout)
#       --out-fw <file>           (output modified firmware, default: <orig>_mod.bin)
#
# Example:
#   ./scripts/repack_rootfs.sh \
#       --rootfs-dir workspaces/auto_v2_20250828_123000/rootfs_1 \
#       --orig-fw input/firmware.bin \
#       --offset 0x240000 \
#       --partition-size 0x3D0000 \
#       --out-fw firmware_mod.bin
#
# Notes:
#   - Requires mksquashfs (from squashfs-tools)
#   - Compression auto: xz (adjust via --comp)
#   - If new squashfs > partition-size (with padding) -> abort
#
set -euo pipefail

ROOTFS_DIR=""
ORIG_FW=""
OUT_FW=""
OFFSET_HEX=""
PART_SIZE_HEX=""
COMP="xz"
BLOCKSIZE=131072
PAD_ALIGN=0           # Optional absolute final size enforcement (overrides PART_SIZE_HEX)
FORCE=0

usage() {
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//' | sed -n '1,80p'
  echo
  echo "Short usage: $0 --rootfs-dir DIR --orig-fw fw.bin --offset 0xOFFSET [--partition-size 0xSIZE]"
  exit 0
}

log(){ printf "[REPACK] %s\n" "$*"; }
err(){ printf "[ERROR] %s\n" "$*" >&2; exit 1; }

# Parse args
while (( $# )); do
  case "$1" in
    --rootfs-dir) ROOTFS_DIR="$2"; shift 2 ;;
    --orig-fw) ORIG_FW="$2"; shift 2 ;;
    --out-fw) OUT_FW="$2"; shift 2 ;;
    --offset) OFFSET_HEX="$2"; shift 2 ;;
    --partition-size) PART_SIZE_HEX="$2"; shift 2 ;;
    --comp) COMP="$2"; shift 2 ;;
    --blocksize) BLOCKSIZE="$2"; shift 2 ;;
    --pad-align) PAD_ALIGN="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage ;;
    *) err "Unknown option: $1" ;;
  esac
done

[ -n "$ROOTFS_DIR" ] || err "--rootfs-dir required"
[ -d "$ROOTFS_DIR" ] || err "rootfs dir not found: $ROOTFS_DIR"
[ -n "$ORIG_FW" ] || err "--orig-fw required"
[ -f "$ORIG_FW" ] || err "orig fw not found: $ORIG_FW"
[ -n "$OFFSET_HEX" ] || err "--offset required (hex e.g. 0x240000)"

command -v mksquashfs >/dev/null 2>&1 || err "mksquashfs not in PATH (sudo apt install squashfs-tools)"

OFFSET_DEC=$((OFFSET_HEX))
if [ -n "$PART_SIZE_HEX" ]; then
  PART_SIZE_DEC=$((PART_SIZE_HEX))
else
  PART_SIZE_DEC=0
fi

if [ -z "$OUT_FW" ]; then
  OUT_FW="${ORIG_FW%.bin}_mod.bin"
fi

if [ -f "$OUT_FW" ] && [ $FORCE -ne 1 ]; then
  err "Output file $OUT_FW exists (use --force to overwrite)"
fi

log "Creating working squashfs..."
TMP_SQFS=$(mktemp -u /tmp/repack_XXXXXX.sqsh)

mksquashfs "$ROOTFS_DIR" "$TMP_SQFS" -comp "$COMP" -b "$BLOCKSIZE" -noappend >/dev/null

NEW_SIZE=$(stat -c%s "$TMP_SQFS")
log "New SquashFS size: $NEW_SIZE bytes"

if [ $PART_SIZE_DEC -gt 0 ]; then
  if [ $NEW_SIZE -gt $PART_SIZE_DEC ]; then
    err "New squashfs ($NEW_SIZE) exceeds partition-size ($PART_SIZE_DEC)"
  fi
fi

FINAL_SQ="$TMP_SQFS"

if [ $PART_SIZE_DEC -gt 0 ]; then
  PAD=$((PART_SIZE_DEC - NEW_SIZE))
  if [ $PAD -gt 0 ]; then
    log "Padding to partition-size ($PART_SIZE_DEC) leftover=$PAD"
    dd if=/dev/zero bs=1 count="$PAD" >> "$TMP_SQFS" 2>/dev/null
  fi
fi

if [ $PAD_ALIGN -gt 0 ]; then
  CUR=$(stat -c%s "$TMP_SQFS")
  if [ $CUR -gt $PAD_ALIGN ]; then
    err "Current size ($CUR) > pad-align ($PAD_ALIGN)"
  fi
  PAD2=$((PAD_ALIGN - CUR))
  if [ $PAD2 -gt 0 ]; then
    log "Padding to fixed size $PAD_ALIGN (adding $PAD2 bytes)"
    dd if=/dev/zero bs=1 count="$PAD2" >> "$TMP_SQFS" 2>/dev/null
  fi
fi

cp -f -- "$ORIG_FW" "$OUT_FW"

log "Writing new squashfs at offset 0x$(printf %X "$OFFSET_DEC")"
dd if="$TMP_SQFS" of="$OUT_FW" bs=1 seek="$OFFSET_DEC" conv=notrunc status=none

log "Done. Output firmware: $OUT_FW"
sha256sum "$OUT_FW" | sed 's/^/[REPACK] SHA256 /'

# Optional leftover check
if [ $PART_SIZE_DEC -gt 0 ]; then
  log "Partition boundary check OK (size <= partition-size)."
fi