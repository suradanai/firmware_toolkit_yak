#!/usr/bin/env bash
#
# generate_patch.sh
#
# Create a unified diff patch between an original extracted rootfs directory
# and a modified copy. Produces a .patch file suitable for review or applying
# via 'patch -p1' (with correct relative paths).
#
# Usage:
#   scripts/generate_patch.sh --original path/to/rootfs_orig \
#                             --modified path/to/rootfs_mod \
#                             --out patch_name.patch
#
# Tips:
#   - If you modified files inline (no separate original), you can re-extract to rootfs_orig.
#
set -euo pipefail

ORIG=""
MOD=""
OUT="rootfs_changes.patch"
STRIP_PREFIX=""

usage() {
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//' | sed -n '1,60p'
  echo
  exit 0
}

err(){ echo "[ERROR] $*" >&2; exit 1; }
log(){ echo "[PATCH] $*"; }

while (( $# )); do
  case "$1" in
    --original) ORIG="$2"; shift 2 ;;
    --modified) MOD="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --strip-prefix) STRIP_PREFIX="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) err "Unknown option: $1" ;;
  esac
done

[ -n "$ORIG" ] || err "--original required"
[ -n "$MOD" ] || err "--modified required"
[ -d "$ORIG" ] || err "Original dir not found: $ORIG"
[ -d "$MOD" ] || err "Modified dir not found: $MOD"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Generating patch diff..."
# Optionally handle prefix removal by using tar staging
if [ -n "$STRIP_PREFIX" ]; then
  err "strip-prefix logic not implemented yet (placeholder)."
fi

# Use diff -ruN
diff -ruN "$ORIG" "$MOD" > "$OUT" || true

SIZE=$(stat -c%s "$OUT")
log "Patch written: $OUT (size=$SIZE bytes)"
log "Preview (head -40):"
head -40 "$OUT"