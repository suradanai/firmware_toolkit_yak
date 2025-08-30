from core.fs_scan import scan_all_rootfs_partitions
import os, tempfile

def test_scan_empty(tmp_path):
    fw = tmp_path / "empty.bin"
    fw.write_bytes(b"\x00"*1024)
    parts = scan_all_rootfs_partitions(str(fw), log_func=lambda x: None)
    assert parts == []

def test_scan_squashfs_signature(tmp_path):
    fw = tmp_path / "squash.bin"
    # embed 'hsqs' at offset 100
    data = bytearray(b"\x00"*512)
    data[100:104] = b'hsqs'
    fw.write_bytes(data)
    parts = scan_all_rootfs_partitions(str(fw), log_func=lambda x: None)
    assert len(parts) == 1
    assert parts[0]['fs'] == 'squashfs'
