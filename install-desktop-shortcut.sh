#!/usr/bin/env bash
# install-desktop-shortcut.sh
# ติดตั้งหรืออัปเดต .desktop entry สำหรับ Firmware Toolkit
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_SRC="$PROJECT_ROOT/FirmwareWorkbench.desktop"
DESKTOP_DST="$HOME/.local/share/applications/FirmwareWorkbench.desktop"
WRAPPER_BIN="$HOME/.local/bin/firmware-toolkit-yak"
ICON_SRC="$PROJECT_ROOT/icons/firmware_toolkit_yak.svg"
ICON_DST="$HOME/.local/share/icons/hicolor/scalable/apps/firmware_toolkit_yak.svg"

log(){ printf "[INSTALL-DESKTOP] %s\n" "$*"; }

if [ ! -f "$DESKTOP_SRC" ]; then
  log "ไม่พบไฟล์ .desktop: $DESKTOP_SRC"; exit 1
fi
mkdir -p "$(dirname "$DESKTOP_DST")"
cp "$DESKTOP_SRC" "$DESKTOP_DST"
chmod 644 "$DESKTOP_DST"
log "ติดตั้ง .desktop -> $DESKTOP_DST"

# ติดตั้ง wrapper (เพื่อหลีกเลี่ยง path ที่มีช่องว่างใน Exec=)
mkdir -p "$(dirname "$WRAPPER_BIN")"
cat >"$WRAPPER_BIN" <<EOF
#!/usr/bin/env bash
exec "$PROJECT_ROOT/run-gui.sh" "${@}"    
EOF
chmod +x "$WRAPPER_BIN"
log "สร้าง wrapper -> $WRAPPER_BIN"

# ถ้า PATH ผู้ใช้ยังไม่มี ~/.local/bin ให้แก้ Exec เป็น absolute
if ! command -v firmware-toolkit-yak >/dev/null 2>&1; then
  sed -i "s|^Exec=.*|Exec=$WRAPPER_BIN|" "$DESKTOP_DST" || true
  sed -i "s|^TryExec=.*|TryExec=$WRAPPER_BIN|" "$DESKTOP_DST" || true
  log "ปรับ Exec/TryExec ใน .desktop ให้เป็น absolute path (ยังไม่อยู่ใน PATH)"
fi

if [ -f "$ICON_SRC" ]; then
  mkdir -p "$(dirname "$ICON_DST")"
  cp "$ICON_SRC" "$ICON_DST" || true
  log "คัดลอกไอคอน -> $ICON_DST"
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
fi

# อัปเดต database ของ desktop entries (ถ้ามีเครื่องมือ)
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

log "เสร็จสิ้น: เปิดเมนู Desktop (หรือกด Super แล้วพิมพ์ Firmware Toolkit) เพื่อเรียกใช้"
