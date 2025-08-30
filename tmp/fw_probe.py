import os, sys, subprocess, shutil
FW = 'input/cw4t.bin'
if not os.path.isfile(FW):
    print('firmware not found:', FW); sys.exit(1)
FS_SIGS = [(b'hsqs','squashfs'),(b'sqsh','squashfs'),(b'CrAm','cramfs'),(b'UBI#','ubi'),(b'UBI!','ubi'),(b'F2FS','f2fs'),(b'JFFS','jffs2')]
with open(FW,'rb') as f:
    data = f.read()
found = []
for sig, name in FS_SIGS:
    idx = 0
    while True:
        idx = data.find(sig, idx)
        if idx == -1: break
        found.append((name, sig, idx))
        idx += 1
if not found:
    print('No raw FS signatures found in file')
else:
    found_sorted = sorted(found, key=lambda x: x[2])
    print('Found parts:')
    for i,(fs,sig,off) in enumerate(found_sorted):
        nxt = len(data)
        if i+1 < len(found_sorted): nxt = found_sorted[i+1][2]
        size = nxt - off
        print(f" - {i}: {fs} @ 0x{off:X} size={size}")
        out = f'/tmp/fw_part_{i}.bin'
        with open(out,'wb') as o:
            o.write(data[off:off+size])
        print('   wrote', out)
        if fs=='squashfs':
            uq = shutil.which('unsquashfs')
            if uq:
                try:
                    outp = subprocess.check_output([uq,'-s',out], text=True, stderr=subprocess.STDOUT, timeout=20)
                    for ln in outp.splitlines():
                        if 'Compression:' in ln:
                            print('   compression:', ln.strip())
                except Exception as e:
                    print('   unsquashfs probe failed:', e)
            else:
                print('   unsquashfs not found on PATH')
