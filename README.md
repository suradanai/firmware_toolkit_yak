# Firmware Toolkit by yak

Firmware analysis, extraction, patching & GUI toolkit for embedded images (multi-SquashFS, JFFS2, uImage) with AI-assisted heuristics.

![Status](https://img.shields.io/badge/status-alpha-orange) ![License](https://img.shields.io/badge/license-MIT-green) ![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

> WARNING: Modifying firmware can brick hardware. Use on backups and lab devices only.

## Components Added

| File | Purpose |
|------|---------|
| `fw-manager.sh` | Orchestrates FMK extraction + fallback carving |
| `scripts/extract_multi_auto_v2.sh` | Intelligent multi-filesystem carve (SquashFS size-aware, unified JFFS2, optional kernels) |
| `firmware_setup.sh` | One-touch environment + extraction setup script |
| `scripts/repack_rootfs.sh` | Rebuild a modified SquashFS and inject back into firmware |
| `scripts/extract_kernels.sh` | Carve uImage kernels (auto or manual offsets) |
| `scripts/inspect_fs.sh` | Quick inspection of extracted rootfs/JFFS2 artifacts |
| `scripts/generate_patch.sh` | Produce unified diff of rootfs changes |
| `requirements.txt` | Added `jefferson` for JFFS2 parsing |

## Quick Start (One Touch)

```bash
./firmware_setup.sh --firmware /absolute/path/to/firmware.bin --include-kernel
```

Artifacts appear in `workspaces/ws_*` (FMK) or `workspaces/auto_v2_*` (fallback carve).

## Manual Carve (Direct)

```bash
scripts/extract_multi_auto_v2.sh input/firmware.bin --include-kernel
cat workspaces/auto_v2_*/summary_segments.txt
```

## Repack RootFS

1. Modify files under an extracted directory (e.g. `rootfs_1/`).
2. Rebuild + patch into new firmware:

```bash
scripts/repack_rootfs.sh \
  --rootfs-dir workspaces/auto_v2_2025XXXXXXXX/rootfs_1 \
  --orig-fw input/firmware.bin \
  --offset 0x240000 \
  --partition-size 0x3D0000 \
  --out-fw firmware_mod.bin
```

## Generate Patch of Changes

```bash
scripts/generate_patch.sh \
  --original workspaces/auto_v2_2025XXXXXXXX/rootfs_1_original \
  --modified workspaces/auto_v2_2025XXXXXXXX/rootfs_1 \
  --out rootfs_changes.patch
```

## Kernel Extraction (Standalone)

```bash
scripts/extract_kernels.sh --firmware input/firmware.bin --auto --dump-payload
```

## Inspect Filesystems

```bash
scripts/inspect_fs.sh workspaces/auto_v2_2025XXXXXXXX
less workspaces/auto_v2_2025XXXXXXXX/inspection/rootfs_summary.txt
```

## GUI Launch

```bash
./run-gui.sh --install-desktop   # (first run to add menu entry, optional)
./run-gui.sh                     # launches PySide6 GUI
```

On first GUI launch you will be asked to grant consent (patching, external tools, etc.). Optionally install the desktop shortcut.

## Notes & Caveats

- The FMK scripts expect to be run from their repository root (handled by `fw-manager.sh`).
- SquashFS padding default: 64 KiB. Adjust via `--pad-squash`.
- JFFS2 nodes are unified into one partition by default. Use `--multi-jffs2` only for debugging.
- Repacking does not recalculate external checksums/signatures beyond replacing raw partitions. If the device uses additional integrity layers (e.g., header CRC beyond uImage, secure boot), more tooling is needed.

## GUI: Multi-Squash (Tools)

The GUI includes a Tools → "Multi-Squash" page which can detect and optionally shrink multiple embedded SquashFS partitions inside a firmware image.

- Select a firmware file via the main dashboard (Open Firmware).
- Open Tools → Multi-Squash and press "Multi-Squash: Dry-run" to inspect detected parts.
- To run the shrink+repack pipeline, enable "Allow destructive trimming" if you want logs/tmp removed, then press "Multi-Squash: Apply".

Artifacts are written to the `output/` folder and include:
- patched firmware: `<orig>_patched.bin`
- gzip backup: `<orig>_patched.bin.gz`
- checksums: `output/SHA256SUMS`
- binary diff (fallback): `output/binary_diff.txt`
- metadata: `output/<patched>.meta.json`


## Desktop Shortcut

You can install a desktop launcher (with icon + wrapper) so you can open the GUI from your system menu.

### Automatic (Recommended)

```bash
./install-desktop-shortcut.sh
```

This will:

1. Copy `FirmwareWorkbench.desktop` to `~/.local/share/applications/`
2. Install a wrapper at `~/.local/bin/firmware-toolkit-yak`
3. Copy the SVG icon into your icon theme
4. Refresh desktop database & icon cache (if tools available)

Then press Super and type: Firmware Toolkit

### Manual (Fallback)

```bash
chmod +x run-gui.sh
cp FirmwareWorkbench.desktop ~/.local/share/applications/
gtk-update-icon-cache -f ~/.local/share/icons/hicolor 2>/dev/null || true
```

### Uninstall

```bash
rm -f ~/.local/share/applications/FirmwareWorkbench.desktop
rm -f ~/.local/bin/firmware-toolkit-yak
```

If the launcher does not appear immediately, log out/in or run:

```bash
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

## Safety

DO NOT flash modified images to production hardware without:

- Verifying partition boundaries
- Validating cryptographic signatures (if any)
- Backing up original firmware

## Development / Contribution

See `CONTRIBUTING.md` for guidelines. Version: refer to `VERSION` file.

## Future Ideas

- Add UBIFS support
- Auto-detect partition table headers
- Integrate signature / hash verification (uImage CRC re-gen, etc.)
 
## Legacy Note

Earlier README variant (simplified) mentioned only IP Camera firmware modification. Current scope is broader: multi-filesystem extraction, U-Boot environment analysis, rootfs patch automation, AI-assisted heuristics.
