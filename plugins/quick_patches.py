"""Quick Patch Actions

Provides simple one-click patch operations exposed via plugin simple actions.
"""
from __future__ import annotations
import os, tempfile
from core.patches import (
	patch_boot_delay,
	patch_rootfs_shell_serial,
	patch_rootfs_network,
	patch_root_password
)

def _ensure_out_dir(base: str) -> str:
	d = os.path.join(os.path.dirname(base) or '.', 'patched')
	os.makedirs(d, exist_ok=True)
	return d

def action_patch_bootdelay(ctx):
	if not ctx.firmware_path:
		ctx.add_log('[PATCH] no firmware loaded')
		return
	# Pass None for out_path to use new auto-naming (_bootdelay<val>.bin)
	ok,msg = patch_boot_delay(ctx.firmware_path, None, 1, None, ctx.add_log)
	ctx.add_log(f"[PATCH] bootdelay -> {'ok' if ok else 'fail'} {msg}")

def action_patch_serial(ctx):
	if not ctx.firmware_path:
		ctx.add_log('[PATCH] no firmware loaded')
		return
	out_dir = _ensure_out_dir(ctx.firmware_path)
	out_path = os.path.join(out_dir, os.path.basename(ctx.firmware_path).rsplit('.',1)[0] + '_serial.bin')
	ok,msg = patch_rootfs_shell_serial(ctx.firmware_path, None, out_path, ctx.add_log)
	ctx.add_log(f"[PATCH] serial console -> {out_path} ({'ok' if ok else msg})")

def action_patch_network(ctx):
	if not ctx.firmware_path:
		ctx.add_log('[PATCH] no firmware loaded')
		return
	out_dir = _ensure_out_dir(ctx.firmware_path)
	out_path = os.path.join(out_dir, os.path.basename(ctx.firmware_path).rsplit('.',1)[0] + '_net.bin')
	ok,msg = patch_rootfs_network(ctx.firmware_path, None, out_path, ctx.add_log)
	ctx.add_log(f"[PATCH] network services -> {out_path} ({'ok' if ok else msg})")

def action_patch_root_password(ctx):
	if not ctx.firmware_path:
		ctx.add_log('[PATCH] no firmware loaded')
		return
	out_dir = _ensure_out_dir(ctx.firmware_path)
	out_path = os.path.join(out_dir, os.path.basename(ctx.firmware_path).rsplit('.',1)[0] + '_rootpw.bin')
	ok,msg = patch_root_password(ctx.firmware_path, None, 'root', out_path, ctx.add_log)
	ctx.add_log(f"[PATCH] root password -> {out_path} ({'ok' if ok else msg})")

def register(reg):
	reg.simple('Patching','Patch Boot Delay (1s)', action_patch_bootdelay)
	reg.simple('Patching','Enable Serial Console', action_patch_serial)
	reg.simple('Patching','Disable Network Services', action_patch_network)
	reg.simple('Patching','Set Root Password (root)', action_patch_root_password)
