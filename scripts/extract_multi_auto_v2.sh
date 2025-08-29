#!/usr/bin/env bash
#
# Advanced multi-filesystem firmware carving & extraction (v2)
# Features:
#   - SquashFS size-aware carving using binwalk reported compressed size + adjustable padding
#   - Single unified JFFS2 partition (first JFFS2 offset -> EOF)
#   - Optional legacy fragment mode (--multi-jffs2)
#   - Optional uImage kernel carving (--include-kernel)
#   - Overlap avoidance, summary table, reproducible segments
#
# Usage:
#   scripts/extract_multi_auto_v2.sh <firmware.bin> [--out DIR]
#       [--pad-squash BYTES] [--no-pad] [--include-kernel]
#       [--multi-jffs2] [--force-overwrite]
#
# Exit codes:
#   0 success
#   1 argument error
#   2 firmware not found
#   3 binwalk missing
#   4 no signatures
#
set -euo pipefail

FW=""
OUTDIR=""
INCLUDE_KERNEL=0
MULTI_JFFS2=0
PAD_SQUASH=$((64*1024))
NO_PAD=0
FORCE=0

usage() {
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//' | sed -n '1,70p'
  echo
  echo "Short Usage: $0 firmware.bin [--include-kernel] [--out outdir]"
  exit 0
}

info(){ printf "[*] %s\n" "$*"; }
warn(){ printf "[WARN] %s\n" "$*" >&2; }
err(){ printf "[ERR] %s\n" "$*" >&2; exit 1; }

while (( $# )); do
  case "$1" in
    -h|--help) usage ;;
    --out) OUTDIR="$2"; shift 2 ;;
    --pad-squash) PAD_SQUASH="$2"; shift 2 ;;
    --no-pad) NO_PAD=1; shift ;;
    --include-kernel) INCLUDE_KERNEL=1; shift ;;
    --multi-jffs2) MULTI_JFFS2=1; shift ;;
    --force-overwrite) FORCE=1; shift ;;
    --) shift; break ;;
    -* ) err "Unknown option: $1" ;;
    * )
      if [ -z "$FW" ]; then
        FW="$1"
      else
        err "Extra argument: $1"
      fi
      shift
      ;;
  esac
done

[ -n "$FW" ] || err "Firmware path required."
[ -f "$FW" ] || { printf "[ERR] firmware not found: %s\n" "$FW"; exit 2; }
command -v binwalk >/dev/null || { printf "[ERR] binwalk missing\n"; exit 3; }

[ -n "${OUTDIR:-}" ] || OUTDIR="workspaces/auto_v2_$(date +%Y%m%d_%H%M%S)"
if [ -d "$OUTDIR" ] && [ $FORCE -ne 1 ]; then
  err "Output dir exists: $OUTDIR (use --force-overwrite)"
fi
mkdir -p "$OUTDIR"

SCAN="$OUTDIR/binwalk_scan.txt"
SUMMARY="$OUTDIR/summary_segments.txt"

info "Scanning firmware ..."
binwalk "$FW" > "$SCAN"
SIZE=$(stat -c%s "$FW")
info "Firmware size: $SIZE bytes"

declare -a RAW_OFFSETS RAW_TYPES RAW_LINES
grep -E "Squashfs filesystem|JFFS2 filesystem|uImage header" "$SCAN" 2>/dev/null | \
while IFS= read -r line; do
  [[ $line =~ ^[[:space:]]*([0-9]+)[[:space:]]+0x[0-9A-Fa-f]+[[:space:]]+(.+) ]] || continue
  off=${BASH_REMATCH[1]}
  desc="${BASH_REMATCH[2]}"
  t=""
  [[ $desc == Squashfs\ filesystem* ]] && t="squashfs"
  [[ $desc == JFFS2\ filesystem* ]] && t="jffs2"
  if [[ $desc == uImage\ header* ]] && [ $INCLUDE_KERNEL -eq 1 ]; then
    t="uimage"
  fi
  [ -n "$t" ] && RAW_OFFSETS+=("$off") && RAW_TYPES+=("$t") && RAW_LINES+=("$line")
done

COUNT=${#RAW_OFFSETS[@]}
[ $COUNT -gt 0 ] || { printf "[ERR] no signatures found\n"; exit 4; }
info "Raw recognized signatures: $COUNT"

# Segment arrays
declare -a SEG_TYPE SEG_OFFSET SEG_LENGTH SEG_EXTRA

push_segment(){
  local typ=$1 off=$2 len=$3 extra=$4
  [ "$len" -le 0 ] && return
  SEG_TYPE+=("$typ")
  SEG_OFFSET+=("$off")
  SEG_LENGTH+=("$len")
  SEG_EXTRA+=("$extra")
}

next_region_offset(){
  local idx=$1 base=${RAW_OFFSETS[$idx]}
  local n=$SIZE j
  for ((j=idx+1;j<COUNT;j++)); do
    local o=${RAW_OFFSETS[$j]}
    if [ "$o" -gt "$base" ]; then
      n=$o; break
    fi
  done
  echo "$n"
}

FIRST_JFFS2=-1
if [ $MULTI_JFFS2 -ne 1 ]; then
  for ((i=0;i<COUNT;i++)); do
    if [ "${RAW_TYPES[$i]}" = "jffs2" ]; then
      FIRST_JFFS2=${RAW_OFFSETS[$i]}
      break
    fi
  done
fi

for ((i=0;i<COUNT;i++)); do
  off=${RAW_OFFSETS[$i]}
  typ=${RAW_TYPES[$i]}
  line=${RAW_LINES[$i]}
  case "$typ" in
    squashfs)
      rep=""
      [[ $line =~ size:\ ([0-9]+)\ bytes ]] && rep=${BASH_REMATCH[1]}
      next_off=$(next_region_offset "$i")
      max_len=$((next_off-off))
      [ $max_len -le 0 ] && continue
      if [ -n "$rep" ]; then
        pad=0
        [ $NO_PAD -ne 1 ] && pad=$PAD_SQUASH
        want=$((rep+pad))
        [ $want -gt $max_len ] && want=$max_len
        push_segment squashfs "$off" "$want" "reported=$rep pad=$pad max=$max_len"
      else
        push_segment squashfs "$off" "$max_len" "reported=NA fallback"
      fi
      ;;
    jffs2)
      if [ $MULTI_JFFS2 -eq 1 ]; then
        next_off=$(next_region_offset "$i")
        len=$((next_off-off))
        push_segment jffs2_fragment "$off" "$len" "legacy"
      else
        [ "$off" -eq "$FIRST_JFFS2" ] && push_segment jffs2_full "$off" $((SIZE-off)) "combined"
      fi
      ;;
    uimage)
      next_off=$(next_region_offset "$i")
      len=$((next_off-off))
      push_segment uimage "$off" "$len" "raw_region"
      ;;
  esac
done

# Sort by offset
for ((i=0;i<${#SEG_TYPE[@]}-1;i++)); do
  for ((j=i+1;j<${#SEG_TYPE[@]};j++)); do
    if [ "${SEG_OFFSET[$j]}" -lt "${SEG_OFFSET[$i]}" ]; then
      for arr in SEG_TYPE SEG_OFFSET SEG_LENGTH SEG_EXTRA; do
        eval "tmp=\${$arr[$i]}; $arr[$i]=\${$arr[$j]}; $arr[$j]=\$tmp"
      done
    fi
  done
done

# Remove overlaps
declare -a F_TYPE F_OFFSET F_LENGTH F_EXTRA
last_end=-1
for ((i=0;i<${#SEG_TYPE[@]};i++)); do
  s=${SEG_OFFSET[$i]} l=${SEG_LENGTH[$i]} e=$((s+l))
  if [ $s -lt $last_end ]; then
    warn "Dropping overlapping segment ${SEG_TYPE[$i]} @ $s"
    continue
  fi
  F_TYPE+=("${SEG_TYPE[$i]}")
  F_OFFSET+=("$s")
  F_LENGTH+=("$l")
  F_EXTRA+=("${SEG_EXTRA[$i]}")
  last_end=$e
done

{
  printf "%-4s %-10s %-10s %-10s %-10s %s\n" IDX TYPE OFFSET LENGTH END EXTRA
  for ((i=0;i<${#F_TYPE[@]};i++)); do
    o=${F_OFFSET[$i]} l=${F_LENGTH[$i]} e=$((o+l))
    printf "%-4s %-10s 0x%08X 0x%08X 0x%08X %s\n" "$i" "${F_TYPE[$i]}" "$o" "$l" "$e" "${F_EXTRA[$i]}"
  done
} | tee "$SUMMARY"

for ((i=0;i<${#F_TYPE[@]};i++)); do
  typ=${F_TYPE[$i]}
  off=${F_OFFSET[$i]}
  len=${F_LENGTH[$i]}
  printf "\n[*] Carving segment %d: type=%s offset=0x%X length=%d (0x%X)\n" "$i" "$typ" "$off" "$len" "$len"
  case "$typ" in
    squashfs)
      out="$OUTDIR/rootfs_${i}.sqsh"
      dd if="$FW" of="$out" bs=1 skip="$off" count="$len" status=none
      if command -v unsquashfs >/dev/null 2>&1; then
        unsquashfs -d "$OUTDIR/rootfs_${i}" "$out" >/dev/null 2>&1 && \
          echo "    -> unsquashfs OK" || echo "    -> unsquashfs FAILED"
      else
        echo "    -> unsquashfs not installed"
      fi
      ;;
    jffs2_full)
      out="$OUTDIR/jffs2_full.bin"
      dd if="$FW" of="$out" bs=1 skip="$off" count="$len" status=none
      if command -v jefferson >/dev/null 2>&1; then
        jefferson -d "$OUTDIR/jffs2_full" "$out" >/dev/null 2>&1 && \
          echo "    -> jefferson OK" || echo "    -> jefferson FAILED"
      else
        echo "    -> jefferson not installed"
      fi
      ;;
    jffs2_fragment)
      out="$OUTDIR/jffs2_${i}.bin"
      dd if="$FW" of="$out" bs=1 skip="$off" count="$len" status=none
      command -v jefferson >/dev/null 2>&1 && \
        jefferson -d "$OUTDIR/jffs2_${i}" "$out" >/dev/null 2>&1 && \
        echo "    -> jefferson OK" || echo "    -> jefferson FAIL/jefferson missing"
      ;;
    uimage)
      out="$OUTDIR/kernel_${i}.uImage"
      dd if="$FW" of="$out" bs=1 skip="$off" count="$len" status=none
      echo "    -> uImage carved"
      ;;
  esac
done

echo
info "Done. Output directory: $OUTDIR"
info "Summary: $SUMMARY"
echo "[*] Inspect example:"
echo "    ls -1 $OUTDIR/rootfs_* 2>/dev/null | head"