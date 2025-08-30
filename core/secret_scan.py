"""Secret scanning utilities for extracted rootfs.
Lightweight regex-based patterns (no heavy external dependencies) with
best‑effort binary exclusion and size limits.
"""
from __future__ import annotations
import os, re
from typing import List, Dict, Iterable

# Patterns (name, compiled_regex)
_PATTERNS: Iterable[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Key", re.compile(r"(?i)aws(.{0,12})?(secret|access)_?(key|id)['\"]?\s*[:=]\s*['\"]([A-Za-z0-9/+=]{20,40})")),
    ("Private Key Block", re.compile(r"-----BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE KEY-----")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Generic API Key", re.compile(r"(?i)(api|secret|token)_?key['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_\-]{16,})")),
    ("Password Assignment", re.compile(r"(?i)password\s*[:=]\s*['\"]?([A-Za-z0-9_!@#$%^&*]{4,})")),
]

MAX_FILE_SIZE = 1024 * 1024  # 1MB per file scan limit
MAX_MATCHES_PER_FILE = 10
MAX_TOTAL_MATCHES = 500


def _is_probably_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    # Ratio of non-printable
    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    if len(data) == 0:
        return False
    return printable / len(data) > 0.85


def scan_secrets_in_dir(root_dir: str) -> List[Dict[str, str]]:
    """Return list of secret findings: {file, type, snippet}.
    Keeps overall match count bounded for performance.
    """
    findings: List[Dict[str, str]] = []
    total = 0
    for dp, _, files in os.walk(root_dir):
        for fn in files:
            if total >= MAX_TOTAL_MATCHES:
                return findings
            fp = os.path.join(dp, fn)
            try:
                if os.path.getsize(fp) > MAX_FILE_SIZE:
                    continue
                with open(fp, 'rb') as f:
                    data = f.read()
                if not _is_probably_text(data):
                    continue
                try:
                    text = data.decode('utf-8', errors='ignore')
                except Exception:
                    continue
                file_matches = 0
                for name, rgx in _PATTERNS:
                    for m in rgx.finditer(text):
                        snippet = m.group(0)[:120]
                        findings.append({
                            'file': os.path.relpath(fp, root_dir),
                            'type': name,
                            'snippet': snippet,
                        })
                        file_matches += 1
                        total += 1
                        if file_matches >= MAX_MATCHES_PER_FILE or total >= MAX_TOTAL_MATCHES:
                            break
                    if file_matches >= MAX_MATCHES_PER_FILE or total >= MAX_TOTAL_MATCHES:
                        break
            except Exception:
                continue
    return findings

__all__ = ["scan_secrets_in_dir"]
