"""Core file / hashing / entropy helpers extracted from app.py"""
from __future__ import annotations
import os, hashlib, binascii, math, random
from typing import List

__all__ = [
    'sha256sum','md5sum','crc32sum','get_entropy'
]

def sha256sum(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def md5sum(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def crc32sum(path: str) -> str:
    bufsize = 65536
    crc = 0
    with open(path, 'rb') as f:
        while True:
            data = f.read(bufsize)
            if not data:
                break
            crc = binascii.crc32(data, crc)
    return f"{crc & 0xFFFFFFFF:08x}"

def get_entropy(fw_path: str, sample_size=65536, samples=4):
    res = []
    try:
        filesize = os.path.getsize(fw_path)
        with open(fw_path, 'rb') as f:
            for _ in range(samples):
                if filesize > sample_size:
                    offset = random.randint(0, filesize - sample_size)
                    f.seek(offset)
                else:
                    f.seek(0)
                b = f.read(sample_size)
                if not b:
                    break
                freq = [0]*256
                for x in b:
                    freq[x] += 1
                L = len(b)
                e = -sum((c / L) * math.log2(c / L) for c in freq if c)
                res.append(round(e,3))
    except Exception:
        return '-'
    if not res:
        return '-'
    return f"min={min(res):.3f}, max={max(res):.3f}, avg={sum(res)/len(res):.3f}"
