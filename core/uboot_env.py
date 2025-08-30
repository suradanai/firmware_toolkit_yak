"""U-Boot environment scanning & patch utilities extracted from app.py"""
from __future__ import annotations
import os, re, struct, binascii
from typing import List, Dict, Tuple, Callable

LogFunc = Callable[[str], None]

__all__ = [
    'scan_uboot_env','analyze_bootloader_env','patch_uboot_env_bootdelay','patch_uboot_env_vars'
]

def scan_uboot_env(fw_path, max_search=0x200000, env_sizes=(0x1000,0x2000,0x4000,0x8000,0x10000), deep: bool=False):
    results=[]
    try:
        fsize=os.path.getsize(fw_path)
        if deep:
            limit=fsize if fsize < 64*1024*1024 else 64*1024*1024
        else:
            limit=min(fsize,max_search)
        with open(fw_path,'rb') as f:
            blob=f.read(limit)
        step=0x400 if not deep else 0x800
        for off in range(0, limit, step):
            for env_size in env_sizes:
                if off+env_size>len(blob):
                    continue
                block=blob[off:off+env_size]
                if len(block)<8:
                    continue
                crc_stored=struct.unpack('<I', block[:4])[0]
                data=block[4:]
                if b'=' not in data[:env_size-4]:
                    continue
                end_double=data.find(b'\x00\x00')
                if end_double==-1 or end_double<4:
                    continue
                env_region=data[:end_double+1]
                first_eq=env_region.find(b'=')
                if first_eq==-1 or first_eq>64:
                    continue
                calc=binascii.crc32(env_region)&0xffffffff
                raw_vars=env_region.split(b'\x00')
                kv={}; text_pairs=0
                for raw in raw_vars:
                    if not raw or b'=' not in raw:
                        continue
                    k,v=raw.split(b'=',1)
                    if not k or len(k)>64:
                        continue
                    if any(c<32 or c>126 for c in k):
                        continue
                    try:
                        k_dec=k.decode(); v_dec=v.decode(errors='ignore')
                    except:
                        continue
                    kv[k_dec]=v_dec; text_pairs+=1
                if text_pairs<3:
                    continue
                score=0
                if 'bootdelay' in kv: score+=5
                if 'baudrate' in kv: score+=2
                if 'ethaddr' in kv or 'ipaddr' in kv: score+=2
                score+=min(len(kv),50)/10.0
                results.append({'offset':off,'size':env_size,'crc':f"{crc_stored:08x}",'crc_calc':f"{calc:08x}",'valid':calc==crc_stored,'vars':kv,'bootdelay':kv.get('bootdelay'),'score':score})
    except Exception:
        pass
    # (Heuristic deep fallback omitted for brevity in extracted version)
    # Deduplicate
    dedup={}
    for r in results:
        key=(r['offset'], r['size'])
        if key not in dedup or r.get('score',0)>dedup[key].get('score',0):
            dedup[key]=r
    out=list(dedup.values())
    out.sort(key=lambda r:(-r.get('score',0), r['offset']))
    return out

def analyze_bootloader_env(env_blocks):
    findings=[]; suggestions=[]
    if not env_blocks:
        return ["[BOOTENV] ไม่พบ environment"], ["ไม่สามารถวิเคราะห์ bootloader env (ไม่พบ)"]
    best=env_blocks[0]
    vars_=best.get('vars',{})
    findings.append(f"[BOOTENV] ใช้บล็อค @0x{best['offset']:X} size=0x{best['size']:X} valid_crc={best['valid']} vars={len(vars_)}")
    key_groups={'boot':['bootcmd','bootargs','bootdelay','bootfile','autoload'], 'net':['ipaddr','serverip','gatewayip','netmask','ethaddr'], 'hw':['baudrate','mtdparts','console'], 'misc':['preboot','stdin','stdout','stderr','bootretry']}
    for grp,keys in key_groups.items():
        present=[k for k in keys if k in vars_]
        if present:
            findings.append(f"[BOOTENV] {grp}: "+", ".join(f"{k}={vars_[k]}" for k in present))
    def add_sug(cond,msg):
        if cond and msg not in suggestions: suggestions.append(msg)
    try:
        bd=int(vars_.get('bootdelay','0')); add_sug(bd>3, f"ลด bootdelay {bd}->1 เพื่อบูตเร็วขึ้น")
    except: pass
    bc=vars_.get('bootcmd','')
    add_sug('tftp' in bc.lower(), 'พิจารณาลบ tftp จาก bootcmd หากไม่ใช้ network boot')
    ba=vars_.get('bootargs','')
    add_sug('console=' not in ba, 'เพิ่ม console=ttyS0,115200 ใน bootargs เพื่อ debug')
    add_sug('root=' not in ba, 'กำหนด root= ใน bootargs ให้ชัดเจน')
    eth=vars_.get('ethaddr','')
    mac_re=re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
    add_sug(eth and not mac_re.match(eth), 'ethaddr รูปแบบไม่ถูกต้อง')
    if suggestions:
        findings.append('[BOOTENV] ข้อเสนอ:'); findings.extend('  - '+s for s in suggestions)
    else:
        findings.append('[BOOTENV] ไม่พบข้อเสนอเพิ่มเติม')
    return findings, suggestions

def patch_uboot_env_bootdelay(src_fw, dst_fw, new_val, log_func: LogFunc=lambda m:None):
    envs=scan_uboot_env(src_fw)
    if not envs:
        log_func('[UBOOT] ไม่พบ environment สำหรับแก้ไข'); return False
    target=None
    for e in envs:
        if e.get('bootdelay') is not None: target=e; break
    if not target: target=envs[0]
    off=target['offset']; size=target['size']
    with open(src_fw,'rb') as f: f.seek(off); block=f.read(size)
    if len(block)!=size: log_func('[UBOOT] อ่าน block ไม่ครบ'); return False
    stored_crc=struct.unpack('<I', block[:4])[0]; data=block[4:]
    end_double=data.find(b'\x00\x00')
    if end_double==-1: log_func('[UBOOT] ไม่พบ \0\0'); return False
    env_region=data[:end_double+1]
    pairs=[]
    for raw in env_region.split(b'\x00'):
        if not raw or b'=' not in raw: continue
        k,v=raw.split(b'=',1)
        try: pairs.append((k.decode(), v.decode(errors='ignore')))
        except: pass
    updated=False
    for i,(k,v) in enumerate(pairs):
        if k=='bootdelay':
            if v!=str(new_val): pairs[i]=(k,str(new_val)); updated=True
            else: updated=True
            break
    else:
        pairs.append(('bootdelay', str(new_val))); updated=True
    kv_bytes=b''.join(f"{k}={v}".encode()+b'\x00' for k,v in pairs)
    new_env_region=kv_bytes+b'\x00'
    new_crc=binascii.crc32(new_env_region) & 0xffffffff
    new_block=struct.pack('<I', new_crc)+new_env_region+data[end_double+2:]
    with open(src_fw,'rb') as f:
        whole=f.read()
    new_whole=whole[:off]+new_block+whole[off+len(new_block):]
    with open(dst_fw,'wb') as f: f.write(new_whole)
    log_func(f'[UBOOT] bootdelay -> {new_val} (offset 0x{off:X})')
    return True

def patch_uboot_env_vars(src_fw, dst_fw, off, size, updates: dict, log_func: LogFunc=lambda m:None):
    with open(src_fw,'rb') as f: f.seek(off); block=f.read(size)
    if len(block)!=size: log_func('[UBOOT] block size mismatch'); return False
    stored_crc=struct.unpack('<I', block[:4])[0]; data=block[4:]
    end_double=data.find(b'\x00\x00')
    if end_double==-1: log_func('[UBOOT] no double null'); return False
    env_region=data[:end_double+1]
    vars_list=[]
    for raw in env_region.split(b'\x00'):
        if not raw or b'=' not in raw: continue
        k,v=raw.split(b'=',1)
        try: vars_list.append([k.decode(), v.decode(errors='ignore')])
        except: pass
    kv_index={k:i for i,(k,v) in enumerate(vars_list)}
    for k,v in updates.items():
        if k in kv_index:
            vars_list[kv_index[k]][1]=str(v)
        else:
            vars_list.append([k,str(v)])
    kv_bytes=b''.join(f"{k}={v}".encode()+b'\x00' for k,v in vars_list)
    new_env_region=kv_bytes+b'\x00'
    new_crc=binascii.crc32(new_env_region) & 0xffffffff
    new_block=struct.pack('<I', new_crc)+new_env_region+data[end_double+2:]
    with open(src_fw,'rb') as f: whole=f.read()
    new_whole=whole[:off]+new_block+whole[off+len(new_block):]
    with open(dst_fw,'wb') as f: f.write(new_whole)
    log_func(f'[UBOOT] updated vars: {", ".join(updates.keys())}')
    return True
