"""Firmware patch helper functions extracted from app.py.
Each function performs an in-place style transformation by reading the
firmware/rootfs slice and writing a new modified firmware file.
"""
from __future__ import annotations
import os, re, tempfile, shutil, subprocess, hashlib
from passlib.hash import sha512_crypt
from typing import Tuple, Optional, Callable

LogFunc = Callable[[str], None]

__all__ = [
    'patch_boot_delay','patch_rootfs_shell_serial','patch_rootfs_network','patch_root_password'
]

def _read_rootfs_slice(fw_path: str, part: Optional[dict]) -> bytes:
    if not part:
        return open(fw_path,'rb').read()
    with open(fw_path,'rb') as f:
        f.seek(part['offset']); return f.read(part['size'])

def patch_boot_delay(fw_path, rootfs_part, new_delay, out_path: Optional[str], log_func: LogFunc) -> Tuple[bool,str]:
    """Patch bootdelay anywhere inside firmware or provided rootfs slice.

    Enhancements:
      - Auto-generate output filename if out_path not supplied (adds suffix _bootdelay<N>.bin next to original)
      - If no existing bootdelay=\d+ found, optionally insert one (append to first env-like region) rather than silently succeed.
      - Report number of replacements and original value(s) found.
      - Provide small diff-style context (first 2 matches) in log for transparency.
    """
    try:
        from app import backup_file, compute_sha256, log_patch_action
        new_delay_int = int(new_delay)
        # 1. Prepare output path
        if not out_path:
            base_dir, base_name = os.path.split(fw_path)
            stem, ext = os.path.splitext(base_name)
            out_path = os.path.join(base_dir, f"{stem}_bootdelay{new_delay_int}{ext or '.bin'}")
        # Avoid accidental overwrite of original
        if os.path.abspath(out_path) == os.path.abspath(fw_path):
            stem, ext = os.path.splitext(out_path)
            out_path = stem + f"_patched_bootdelay{new_delay_int}" + ext

        backup_path = backup_file(fw_path, backup_dir="backup", note="before_patch_boot_delay")
        orig_sha = compute_sha256(fw_path)
        log_patch_action('pre-patch', fw_path, orig_sha, f"before patch bootdelay={new_delay_int}")
        data = _read_rootfs_slice(fw_path, rootfs_part)

        pat = re.compile(rb'bootdelay=(\d+)')
        matches = list(pat.finditer(data))
        replaced_values = []
        if matches:
            # Replace all occurrences
            def _repl(m):
                old = m.group(1).decode(errors='ignore')
                replaced_values.append(old)
                return f"bootdelay={new_delay_int}".encode()
            new = pat.sub(_repl, data)
            inserted = False
        else:
            # Try to insert: find an env-like ascii region containing bootcmd / bootargs
            inserted = True
            anchor = None
            for token in (b'bootcmd=', b'bootargs='):
                pos = data.find(token)
                if pos != -1:
                    anchor = pos
                    break
            if anchor is not None:
                # Insert before anchor line: seek start of line
                line_start = data.rfind(b'\n', 0, anchor)
                if line_start == -1:
                    line_start = 0
                insertion = f"bootdelay={new_delay_int}\n".encode()
                new = data[:line_start] + insertion + data[line_start:]
            else:
                # Fallback append at end
                new = data + f"\nbootdelay={new_delay_int}\n".encode()
        # Write output
        with open(out_path,'wb') as f:
            f.write(new)
        patched_sha = compute_sha256(out_path)
        log_patch_action('post-patch', out_path, patched_sha, f"after patch bootdelay={new_delay_int}")

        # Build summary message
        if matches:
            summary = f"พบ bootdelay {len(matches)} ตำแหน่ง (เดิม: {', '.join(replaced_values)}) -> {new_delay_int} | output: {out_path}"
        elif inserted:
            summary = f"ไม่พบ bootdelay เดิม - ทำการเพิ่มใหม่ bootdelay={new_delay_int} | output: {out_path}"
        else:
            summary = f"patch bootdelay เสร็จสิ้น | output: {out_path}"

        # Diff preview (first two occurrences)
        preview_lines = []
        if matches:
            for m in matches[:2]:
                start = max(0, m.start() - 16)
                end = min(len(data), m.end() + 16)
                seg_old = data[start:end]
                seg_new = new[start:end]
                preview_lines.append(f"- {seg_old.decode(errors='ignore')}\n+ {seg_new.decode(errors='ignore')}")
        if preview_lines:
            log_func("\n".join(preview_lines))
        log_func(summary)
        return True, summary
    except Exception as e:
        return False, str(e)

def patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        from app import backup_file, compute_sha256, log_patch_action
        backup_path = backup_file(fw_path, backup_dir="backup", note="before_patch_rootfs_shell_serial")
        orig_sha = compute_sha256(fw_path)
        log_patch_action('pre-patch', fw_path, orig_sha, "before patch rootfs_shell_serial")
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # enable console: search patterns like 'console=ttyS0,115200 quiet'
        new = re.sub(rb'quiet', b'', data)
        with open(out_path,'wb') as f: f.write(new)
        patched_sha = compute_sha256(out_path)
        log_patch_action('post-patch', out_path, patched_sha, "after patch rootfs_shell_serial")
        return True, ''
    except Exception as e:
        return False, str(e)

def patch_rootfs_network(fw_path, rootfs_part, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        from app import backup_file, compute_sha256, log_patch_action
        backup_path = backup_file(fw_path, backup_dir="backup", note="before_patch_rootfs_network")
        orig_sha = compute_sha256(fw_path)
        log_patch_action('pre-patch', fw_path, orig_sha, "before patch rootfs_network")
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # crude disable telnet/ftp service strings
        for token in [b'telnetd', b'pure-ftpd', b'vsftpd']:
            if token in data:
                data = data.replace(token, b'_' + token)
        with open(out_path,'wb') as f: f.write(data)
        patched_sha = compute_sha256(out_path)
        log_patch_action('post-patch', out_path, patched_sha, "after patch rootfs_network")
        return True, ''
    except Exception as e:
        return False, str(e)

def patch_root_password(fw_path, rootfs_part, password, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        from app import backup_file, compute_sha256, log_patch_action
        backup_path = backup_file(fw_path, backup_dir="backup", note="before_patch_root_password")
        orig_sha = compute_sha256(fw_path)
        log_patch_action('pre-patch', fw_path, orig_sha, "before patch root_password")
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # simple /etc/shadow replacement approach (heuristic)
        hashed = sha512_crypt.hash(password)
        lines = data.split(b'\n')
        for i,l in enumerate(lines):
            if l.startswith(b'root:'):
                parts = l.split(b':')
                if len(parts) > 1:
                    parts[1] = hashed.encode()
                    lines[i] = b':'.join(parts)
        new = b'\n'.join(lines)
        with open(out_path,'wb') as f: f.write(new)
        patched_sha = compute_sha256(out_path)
        log_patch_action('post-patch', out_path, patched_sha, "after patch root_password")
        return True, ''
    except Exception as e:
        return False, str(e)
