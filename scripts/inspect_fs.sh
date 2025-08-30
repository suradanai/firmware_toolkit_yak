#!/usr/bin/env bash
#
# inspect_fs.sh
#
# Quick triage of extracted filesystems (rootfs_* dirs + jffs2_full).
# Generates:
#   - rootfs_summary.txt (size/inodes key paths)
#   - passwd_shadow_report.txt (user accounts)
#   - version_strings.txt (grep for release/version markers)
#
# Usage:
#   scripts/inspect_fs.sh <extraction_workspace_dir>
#
set -euo pipefail

WS="$1"
[ -d "$WS" ] || { echo "[ERR] workspace not found: $WS" >&2; exit 1; }

OUT="$WS/inspection"
mkdir -p "$OUT"

echo "[*] Workspace: $WS"
echo "[*] Writing reports to: $OUT"

# RootFS summary
{
  echo "== RootFS Summary =="
  for d in "$WS"/rootfs_*; do
    [ -d "$d" ] || continue
    sz=$(du -sh "$d" 2>/dev/null | cut -f1)
    cnt=$(find "$d" -type f 2>/dev/null | wc -l)
    echo "- $(basename "$d"): size=$sz files=$cnt"
    for f in os-release version release issue; do
      if [ -f "$d/etc/$f" ]; then
        echo "  /etc/$f: $(head -n1 "$d/etc/$f")"
      fi
    done
  done
} > "$OUT/rootfs_summary.txt"

# Accounts report
{
  echo "== Accounts (/etc/passwd & shadow if present) =="
  for d in "$WS"/rootfs_*; do
    [ -d "$d" ] || continue
    if [ -f "$d/etc/passwd" ]; then
      echo "--- $(basename "$d")/etc/passwd ---"
      grep -vE '^(#|$)' "$d/etc/passwd" | cut -d: -f1,3,4,7
    fi
    if [ -f "$d/etc/shadow" ]; then
      echo "--- $(basename "$d")/etc/shadow (user:hash head) ---"
      awk -F: '{printf "%s:%s\n",$1,$2}' "$d/etc/shadow" | head
    fi
  done
  if [ -d "$WS/jffs2_full" ]; then
    if [ -f "$WS/jffs2_full/etc/passwd" ]; then
      echo "--- jffs2_full/etc/passwd ---"
      grep -vE '^(#|$)' "$WS/jffs2_full/etc/passwd" | cut -d: -f1,3,4,7
    fi
  fi
} > "$OUT/passwd_shadow_report.txt"

# Version strings
{
  echo "== Version Strings (grep release, version, build) =="
  grep -R -i -E 'version|release|build' "$WS" 2>/dev/null | head -200
} > "$OUT/version_strings.txt"

echo "[*] Generated:"
ls -1 "$OUT"