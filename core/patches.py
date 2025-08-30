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

def patch_boot_delay(fw_path, rootfs_part, new_delay, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # naive search for bootdelay= or bootdelay\0 etc.
        pat = re.compile(rb'bootdelay=\d+')
        repl = f'bootdelay={int(new_delay)}'.encode()
        new = pat.sub(repl, data)
        if new == data:
            log_func("ไม่พบ bootdelay ใน image")
        with open(out_path,'wb') as f: f.write(new)
        return True, ''
    except Exception as e:
        return False, str(e)

def patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # enable console: search patterns like 'console=ttyS0,115200 quiet'
        new = re.sub(rb'quiet', b'', data)
        with open(out_path,'wb') as f: f.write(new)
        return True, ''
    except Exception as e:
        return False, str(e)

def patch_rootfs_network(fw_path, rootfs_part, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
        data = _read_rootfs_slice(fw_path, rootfs_part)
        # crude disable telnet/ftp service strings
        for token in [b'telnetd', b'pure-ftpd', b'vsftpd']:
            if token in data:
                data = data.replace(token, b'_' + token)
        with open(out_path,'wb') as f: f.write(data)
        return True, ''
    except Exception as e:
        return False, str(e)

def patch_root_password(fw_path, rootfs_part, password, out_path, log_func: LogFunc) -> Tuple[bool,str]:
    try:
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
        return True, ''
    except Exception as e:
        return False, str(e)
