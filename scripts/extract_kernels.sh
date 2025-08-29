#!/usr/bin/env bash
#
# extract_kernels.sh
#
# Extract uImage kernel segments from firmware given known offsets (or auto via binwalk).
#
# Usage:
#   scripts/extract_kernels.sh --firmware input/firmware.bin \
#       [--offset 0x60000] [--offset 0x9E0000] ...
#   scripts/extract_kernels.sh --firmware input/firmware.bin --auto
#
# Options:
#   --firmware <file>    (required)
#   --offset 0xHEX       uImage header offset (repeatable)
#   --auto               Use binwalk to detect "uImage header"
#   --out-dir <dir>      Output directory (default: kernels_<timestamp>)
#   --dump-payload       Also dump raw LZMA payload (skip 0x40 header)
#
# Requirements:
#   - binwalk (for --auto)
#
set -euo pipefail

FW=""
OUTDIR=""
AUTO=0
DUMP_PAYLOAD=0
declare -a OFFSETS

usage() {
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//' | sed -n '1,60p'
  echo
  exit 0
}

log(){ printf "[KERNEL] %s\n" "$*"; }
err(){ printf "[ERROR] %s\n" "$*" >&2; exit 1; }

while (( $# )); do
  case "$1" in
    --firmware) FW="$2"; shift 2 ;;
    --offset) OFFSETS+=("$2"); shift 2 ;;
    --auto) AUTO=1; shift ;;
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --dump-payload) DUMP_PAYLOAD=1; shift ;;
    -h|--help) usage ;;
    *) err "Unknown argument: $1" ;;
  esac
done

[ -n "$FW" ] || err "--firmware required"
[ -f "$FW" ] || err "Firmware not found: $FW"
[ -n "$OUTDIR" ] || OUTDIR="kernels_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

if [ $AUTO -eq 1 ]; then
  command -v binwalk >/dev/null 2>&1 || err "binwalk required for --auto"
  log "Auto-detecting uImage headers..."
  while IFS= read -r line; do
    [[ $line =~ ^[[:space:]]*([0-9]+)[[:space:]]+0x ]] || continue
    off="${BASH_REMATCH[1]}"
    OFFSETS+=("$off")
  done < <(binwalk "$FW" | grep "uImage header" || true)
fi

[ ${#OFFSETS[@]} -gt 0 ] || err "No offsets specified/found."

log "Offsets: ${OFFSETS[*]}"

# Sort unique
mapfile -t OFFSETS < <(printf "%s\n" "${OFFSETS[@]}" | awk '!seen[$0]++' | sort -n)

for off in "${OFFSETS[@]}"; do
  printf "[KERNEL] Carving uImage at offset %d (0x%X)\n" "$off" "$off"
  # Heuristic: carve until next offset or 2MB
  next_size=$((2*1024*1024))
  # If there is a next offset:
  next_off=""
  for x in "${OFFSETS[@]}"; do
    if [ "$x" -gt "$off" ]; then
      next_off=$x
      break
    fi
  done
  if [ -n "$next_off" ]; then
    length=$((next_off - off))
    [ $length -le 0 ] && length=$next_size
  else
    # carve to end (cap at 2MB heuristic if huge)
    fsize=$(stat -c%s "$FW")
    length=$((fsize - off))
    [ $length -gt $next_size ] && length=$next_size
  fi
  out="$OUTDIR/kernel_0x$(printf %X "$off").uImage"
  dd if="$FW" of="$out" bs=1 skip="$off" count="$length" status=none
  file "$out" || true
  if [ $DUMP_PAYLOAD -eq 1 ]; then
    pay="$OUTDIR/kernel_0x$(printf %X "$off")_payload.lzma"
    dd if="$out" of="$pay" bs=1 skip=$((0x40)) status=none
    echo "[KERNEL] Payload dumped: $pay"
  fi
done

log "Done. Output in $OUTDIR"