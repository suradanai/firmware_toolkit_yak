import os, tempfile, stat
from core.secret_scan import scan_secrets_in_dir
from core.elf_analyze import analyze_elf

def _make_fake_elf(path, arch=0x28):  # ARM default
    # Minimal 64-byte ELF header (not fully valid but enough for our parser)
    # e_ident: 0x7f 'E''L''F' + class(1=32bit) + data(1=LE) + version + OSABI + padding
    e_ident = b"\x7fELF" + bytes([1,1,1,0]) + b"\x00"*8
    # rest of header fields little-endian
    # e_type=2 (EXEC), e_machine=arch, e_version=1, e_entry.. arbitrary
    import struct
    hdr_rest = struct.pack('<HHI', 2, arch, 1) + b"\x00"*48
    with open(path,'wb') as f:
        f.write(e_ident + hdr_rest)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def test_secret_scan_and_elf():
    with tempfile.TemporaryDirectory() as d:
        # secret file
        secret_file = os.path.join(d, 'config.txt')
        with open(secret_file,'w') as f:
            f.write('API_KEY = "ABCDEFSECRETKEYTOKEN123456"\n')
        # non-secret file
        with open(os.path.join(d,'readme.txt'),'w') as f:
            f.write('hello world')
        # fake elf
        elf_path = os.path.join(d,'busybox')
        _make_fake_elf(elf_path)
        findings = scan_secrets_in_dir(d)
        assert any('API' in f['type'] or 'Generic API' in f['type'] for f in findings)
        elf_info = analyze_elf(elf_path)
        assert elf_info.get('arch') in ('ARM', hex(0x28))
        assert elf_info.get('class') in ('32-bit','64-bit')
