from core.file_utils import sha256sum, md5sum, crc32sum, get_entropy
import tempfile, os

def test_hash_functions(tmp_path):
    p = tmp_path / "sample.bin"
    data = b"A"*1024 + b"B"*2048
    p.write_bytes(data)
    assert sha256sum(str(p))
    assert md5sum(str(p))
    assert crc32sum(str(p))

def test_entropy(tmp_path):
    p = tmp_path / "rand.bin"
    p.write_bytes(os.urandom(4096))
    ent = get_entropy(str(p))
    assert 'avg=' in ent
