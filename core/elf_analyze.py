"""Lightweight ELF analysis helpers.
We avoid external heavy deps and inspect headers for architecture summary.
Optional: if 'r2' (radare2) or 'rabin2' is present we can gather extra info.
"""
from __future__ import annotations
import os, struct, subprocess, shutil
from typing import Dict, Any

ELF_MAGIC = b"\x7fELF"

ARCH_MAP = {
    0x03: "x86",
    0x3E: "x86_64",
    0x28: "ARM",
    0xB7: "ARM64",
    0x08: "MIPS",
    0x14: "PowerPC",
    0x9026: "Alpha",
}

CLASS_MAP = {1: "32-bit", 2: "64-bit"}
ENDIAN_MAP = {1: "LE", 2: "BE"}
TYPE_MAP = {1: "REL", 2: "EXEC", 3: "DYN"}


def analyze_elf(path: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": path}
    try:
        with open(path, 'rb') as f:
            head = f.read(0x40)
        if not head.startswith(ELF_MAGIC):
            info['error'] = 'not ELF'
            return info
        ei_class = head[4]
        ei_data = head[5]
        e_type = struct.unpack('<H' if ei_data == 1 else '>H', head[16:18])[0]
        e_machine = struct.unpack('<H' if ei_data == 1 else '>H', head[18:20])[0]
        info.update({
            'class': CLASS_MAP.get(ei_class, str(ei_class)),
            'endian': ENDIAN_MAP.get(ei_data, str(ei_data)),
            'type': TYPE_MAP.get(e_type, str(e_type)),
            'arch': ARCH_MAP.get(e_machine, hex(e_machine)),
            'size': os.path.getsize(path),
        })
        # optional rabin2 extra
        rabin = shutil.which('rabin2') or shutil.which('r2')
        if rabin:
            try:
                out = subprocess.check_output(['rabin2', '-I', path], text=True, stderr=subprocess.DEVNULL, timeout=5)
                for line in out.splitlines():
                    if ':' not in line:
                        continue
                    k, v = line.split(':', 1)
                    k = k.strip(); v = v.strip()
                    if k in ('arch', 'bits', 'machine', 'os', 'pic', 'relocs'):
                        info[f'rabin2_{k}'] = v
            except Exception:
                pass
    except Exception as e:
        info['error'] = str(e)
    return info

__all__ = ["analyze_elf"]
