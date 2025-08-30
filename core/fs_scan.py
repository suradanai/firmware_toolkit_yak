"""Filesystem & firmware scanning utilities extracted from app.py

Functions:
    scan_all_rootfs_partitions(fw_path, log_func=print)

The function samples the firmware binary to find filesystem signatures and
falls back to binwalk if direct signature scanning doesn't yield results.
"""
from __future__ import annotations
import os, shutil, subprocess, binascii
from typing import List, Dict, Callable, Any, Optional


_CACHE: Dict[str, List[Dict[str, Any]]] = {}

def scan_all_rootfs_partitions(fw_path: str, log_func: Callable[[str], None] = print, use_cache: bool = True) -> List[Dict[str, Any]]:
    """Return a list of detected rootfs partitions with offsets & sizes.

    Strategy:
      1. Direct byte-signature scan for common FS magic values.
      2. If nothing found, fallback to binwalk (--signature + raw bytes) if installed.

    Each returned dict contains: fs, offset, size, sig (or 'bw'), note(optional)
    """
    FS_SIGNATURES = [
        (b'hsqs', "squashfs"),
        (b'sqsh', "squashfs"),
        (b'CrAm', "cramfs"),
        (b'UBI#', "ubi"),
        (b'UBI!', "ubi"),
        (b'F2FS', "f2fs"),
        (b'JFFS', "jffs2"),
    ]
    # Simple caching based on file size + mtime
    try:
        if use_cache:
            st = os.stat(fw_path)
            cache_key = f"{fw_path}:{st.st_size}:{int(st.st_mtime)}"
            if cache_key in _CACHE:
                return _CACHE[cache_key]
    except Exception:
        cache_key = None

    results = []
    try:
        with open(fw_path, "rb") as f:
            data = f.read()
            for sig, name in FS_SIGNATURES:
                idx = 0
                while True:
                    idx = data.find(sig, idx)
                    if idx == -1:
                        break
                    results.append((name, sig, idx))
                    idx += 1
    except Exception as e:
        log_func(f"scan error: {e}")
        return []

    if results:
        parts = []
        sorted_results = sorted(results, key=lambda x: x[2])
        for i, (fs_name, sig, offset) in enumerate(sorted_results):
            next_offset = len(data)
            if i + 1 < len(sorted_results):
                next_offset = sorted_results[i + 1][2]
            size = next_offset - offset
            entry: Dict[str, Any] = dict(fs=fs_name, offset=offset, size=size, sig=sig.hex())
            # quick UBI volume marker heuristic: look for "UBI#" strings inside region
            if fs_name == 'ubi':
                try:
                    slice_bytes = data[offset: offset + min(size, 4096)]
                    if b'UBI#' in slice_bytes or b'UBI!' in slice_bytes:
                        entry['volumes_hint'] = slice_bytes.count(b'UBI')
                except Exception:
                    pass
            parts.append(entry)
        display_parts = [f"{p['fs']}@0x{p['offset']:X}" for p in parts]
        log_func(f"พบ rootfs {len(parts)} ชุด: {display_parts}")
        if use_cache and cache_key:
            _CACHE[cache_key] = parts
        return parts

    bw = shutil.which("binwalk")
    if not bw:
        log_func("ไม่พบ FS signatures และไม่มี binwalk ติดตั้ง -> ติดตั้ง binwalk3 เพื่อ improve detection (pip install binwalk3)")
        return []
    try:
        out = subprocess.check_output([bw, '--term', '--signature', '--raw-bytes=4', fw_path], text=True, stderr=subprocess.STDOUT)
    except Exception as e:
        log_func(f"binwalk error: {e}")
        return []
    lines = out.splitlines()
    found = []
    for line in lines:
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        parts_line = line.split(None, 1)
        if len(parts_line) < 2:
            continue
        try:
            off = int(parts_line[0])
        except ValueError:
            continue
        desc = parts_line[1].lower()
        for key, mapped in [("squashfs", "squashfs"), ("cramfs", "cramfs"), ("jffs2", "jffs2"), ("ubifs", "ubi"), ("ubi volume", "ubi")]:
            if key in desc:
                found.append((mapped, off, desc))
                break
    if not found:
        log_func("binwalk fallback ยังไม่พบ rootfs")
        return []
    with open(fw_path, 'rb') as f:
        size_fw = len(f.read())
    found_sorted = sorted(found, key=lambda x: x[1])
    parts = []
    for i, (fs_name, offset, desc) in enumerate(found_sorted):
        next_offset = size_fw
        if i + 1 < len(found_sorted):
            next_offset = found_sorted[i+1][1]
        part_size = next_offset - offset
        parts.append(dict(fs=fs_name, offset=offset, size=part_size, sig='bw', note=desc[:60]))
    display_parts = [f"{p['fs']}@0x{p['offset']:X}" for p in parts]
    log_func(f"(binwalk) พบ rootfs {len(parts)} ชุด: {display_parts}")
    if use_cache and cache_key:
        _CACHE[cache_key] = parts
    return parts
