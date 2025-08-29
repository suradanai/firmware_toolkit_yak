# คู่มือการใช้งาน (ภาษาไทย)  
Firmware Workbench Extended Toolkit

เอกสารฉบับนี้เป็น README ภาษาไทย สำหรับชุดสคริปต์ปรับปรุงที่ใช้ในการวิเคราะห์ แตก แก้ไข และรีแพ็กเฟิร์มแวร์อุปกรณ์ฝังตัว (Embedded Firmware) ที่มีระบบไฟล์ (SquashFS / JFFS2) หลายพาร์ท และ kernel รูปแบบ uImage

---

## สารบัญ

- [1. ภาพรวม (Overview)](#1-ภาพรวม-overview)  
- [2. ไฮไลท์ฟีเจอร์ (Features)](#2-ไฮไลท์ฟีเจอร์-features)  
- [3. โครงสร้างไฟล์ / สคริปต์ (Structure)](#3-โครงสร้างไฟล์--สคริปต์-structure)  
- [4. ความต้องการระบบ (Requirements)](#4-ความต้องการระบบ-requirements)  
- [5. การเริ่มต้นแบบรวดเร็ว (Quick Start)](#5-การเริ่มต้นแบบรวดเร็ว-quick-start)  
- [6. เวิร์กโฟลว์หลัก (Standard Workflow)](#6-เวิร์กโฟลว์หลัก-standard-workflow)  
- [7. กลไกการ Extract (ลึก)](#7-กลไกการ-extract-ลึก)  
- [8. สคริปต์ Carve ขั้นสูง (extract_multi_auto_v2.sh)](#8-สคริปต์-carve-ขั้นสูง-extract_multi_auto_v2sh)  
- [9. การวิเคราะห์ RootFS / JFFS2 / Kernel](#9-การวิเคราะห์-rootfs--jffs2--kernel)  
- [10. เลือก RootFS หลักอย่างไร](#10-เลือก-rootfs-หลักอย่างไร)  
- [11. การจัดการ JFFS2 (เหตุผลที่รวมเป็นก้อนเดียว)](#11-การจัดการ-jffs2-เหตุผลที่รวมเป็นก้อนเดียว)  
- [12. การแกะ Kernel (uImage) และ Payload LZMA](#12-การแกะ-kernel-uimage-และ-payload-lzma)  
- [13. การ Repack RootFS กลับเข้าเฟิร์มแวร์](#13-การ-repack-rootfs-กลับเข้าเฟิร์มแวร์)  
- [14. การสร้าง Patch ของการแก้ไข](#14-การสร้าง-patch-ของการแก้ไข)  
- [15. สคริปต์ตรวจเร็ว (inspect_fs.sh)](#15-สคริปต์ตรวจเร็ว-inspect_fssh)  
- [16. การคำนวณ Offset / ขนาด (Hex ↔ Decimal)](#16-การคำนวณ-offset--ขนาด-hex--decimal)  
- [17. ความปลอดภัย / สิ่งที่ควรและไม่ควรทำ](#17-ความปลอดภัย--สิ่งที่ควรและไม่ควรทำ)  
- [18. ตารางอาการ / วิธีแก้ (Troubleshooting Table)](#18-ตารางอาการ--วิธีแก้-troubleshooting-table)  
- [19. ปัญหาพบบ่อย (Common Issues)](#19-ปัญหาพบบ่อย-common-issues)  
- [20. คำสั่งลัด (Quick Reference)](#20-คำสั่งลัด-quick-reference)  
- [21. FAQ (ถามบ่อย)](#21-faq-ถามบ่อย)  
- [22. แนวทางต่อยอด (Future Ideas)](#22-แนวทางต่อยอด-future-ideas)  

---

## 1. ภาพรวม (Overview)

โครงการนี้ออกแบบให้:
- แตก (Extract) เฟิร์มแวร์ที่เป็นไฟล์ไบนารีเดี่ยว (ไม่มี partition table ชัดเจน)  
- รองรับหลายระบบไฟล์ในไฟล์เดียว (หลาย SquashFS + ส่วน config JFFS2 + kernel uImage)  
- มี Fallback กรณี FMK (Firmware Mod Kit) ไม่สามารถแตกสำเร็จ  
- ช่วยทำกระบวนการแก้ไข → รีแพ็ก → เปรียบเทียบ → วิเคราะห์ → สร้าง patch ได้รวดเร็ว  

แนวคิด: “พยายามใช้ FMK ก่อน ถ้าไม่ได้ ใช้ตัว carve แบบรู้ขนาดจริง (size-aware)”  

---

## 2. ไฮไลท์ฟีเจอร์ (Features)

| ฟีเจอร์ | รายละเอียด |
|---------|------------|
| FMK Integration | เรียก multi / single extract อัตโนมัติ |
| Size-Aware Carve | อ่านขนาด compressed ของ SquashFS (จาก binwalk) + padding |
| Unified JFFS2 | รวม node JFFS2 ทั้งหมดเป็น partition เดียว (ลดชิ้นส่วน) |
| Optional Kernel | เลือก carve uImage kernel ได้ (--include-kernel) |
| Repack RootFS | สคริปต์รีแพ็กและฝังกลับเข้าที่ offset เดิม |
| Inspection | รายงาน accounts / versions / filesystem summary |
| Patch Generation | สร้าง diff ของการแก้ไข rootfs |
| One-touch Setup | firmware_setup.sh รวม install + extract |
| Extensible | ง่ายต่อการเพิ่ม UBI/UBIFS ในอนาคต |

---

## 3. โครงสร้างไฟล์ / สคริปต์ (Structure)

```
.
├── fw-manager.sh
├── firmware_setup.sh
├── requirements.txt
├── README.md / README_TH.md (ไฟล์นี้)
└── scripts/
    ├── extract_multi_auto_v2.sh
    ├── extract_multi_auto.sh (สำรองรุ่นแรก)
    ├── repack_rootfs.sh
    ├── extract_kernels.sh
    ├── inspect_fs.sh
    └── generate_patch.sh
```

---

## 4. ความต้องการระบบ (Requirements)

ระบบ:
- Linux (Ubuntu / Debian แนะนำ)
- Python 3.10+ (รองรับ 3.12)

แพ็กเกจระบบ (apt):
```
sudo apt install -y binwalk squashfs-tools p7zip-full sleuthkit
```

Python (ใน venv):
```
pip install -r requirements.txt
```

เสริม (อาจเจอกรณีพิเศษ):
```
sudo apt install -y git build-essential zlib1g-dev liblzma-dev liblzo2-dev
```

---

## 5. การเริ่มต้นแบบรวดเร็ว (Quick Start)

```
./firmware_setup.sh --firmware /absolute/path/to/firmware.bin --include-kernel
```

เสร็จแล้วตรวจผล:
```
ls workspaces/
```

---

## 6. เวิร์กโฟลว์หลัก (Standard Workflow)

1. วางไฟล์เฟิร์มแวร์ลงใน input/ (หรือให้ setup script ทำให้)
2. เรียก: `./fw-manager.sh extract input/firmware.bin`
3. ถ้า FMK สำเร็จ → โฟลเดอร์ `workspaces/ws_*`
4. ถ้า FMK ล้มเหลว → โฟลเดอร์ `workspaces/auto_v2_*`
5. ตรวจไฟล์ `summary_segments.txt`
6. วิเคราะห์ rootfs / jffs2_full / kernel
7. แก้ไข rootfs → รีแพ็ก → ได้ไฟล์ใหม่พร้อมทดสอบ

---

## 7. กลไกการ Extract (ลึก)

ลำดับการทำงานของ `fw-manager.sh`:
1. clone/update FMK  
2. run: extract-multisquashfs-firmware.sh  
3. ถ้า fail → extract-firmware.sh  
4. ถ้า fail → fallback: `scripts/extract_multi_auto_v2.sh`  

`extract_multi_auto_v2.sh`:
- ใช้ binwalk สแกน signatures
- SquashFS → อ่าน “size: X bytes” + padding (ค่าเริ่ม 64K)  
- JFFS2 → เลือก offset แรก → carve ถึง EOF  
- uImage (ถ้าขอ) → carve ช่วงระหว่าง header → signature ถัดไป  
- สร้างไฟล์สรุป segment (อนาคตใช้ repack)

---

## 8. สคริปต์ Carve ขั้นสูง (extract_multi_auto_v2.sh)

คำสั่งตัวอย่าง:
```
scripts/extract_multi_auto_v2.sh input/firmware.bin --include-kernel
```

ออปชัน:
| ออปชัน | อธิบาย |
|--------|--------|
| --include-kernel | แกะ uImage kernels |
| --pad-squash N   | เปลี่ยน padding หลังขนาด compressed |
| --no-pad         | ไม่ padding |
| --multi-jffs2    | แยกทุก node JFFS2 (โหมด debug) |
| --out DIR        | กำหนด output เอง |
| --force-overwrite| ใช้ DIR เดิมซ้ำได้ |

ผลลัพธ์หลัก:
- rootfs_X.sqsh + rootfs_X/
- jffs2_full.bin + jffs2_full/
- kernel_X.uImage
- summary_segments.txt

---

## 9. การวิเคราะห์ RootFS / JFFS2 / Kernel

ตรวจ rootfs:
```
du -sh workspaces/auto_v2_*/rootfs_*
ls workspaces/auto_v2_*/rootfs_1/etc | head
```

ตรวจ config (JFFS2):
```
grep -R "root:" workspaces/auto_v2_*/jffs2_full/etc/passwd 2>/dev/null
```

Kernel:
```
file workspaces/auto_v2_*/kernel_*.uImage
strings workspaces/auto_v2_*/kernel_*.uImage | grep -i linux
```

---

## 10. เลือก RootFS หลักอย่างไร

หลักพิจารณา:
- ขนาดใหญ่สุด (ไฟล์เยอะ)
- มี `/sbin/init` หรือ `/init`
- มี `/etc/passwd`, `/etc/inittab`, `/etc/init.d/` ครบ
- busybox ตัวเต็ม
- มี libs (.so) จำนวนมาก

RootFS เล็กมาก (inodes น้อย) → มักเป็น recovery / secondary / language pack

---

## 11. การจัดการ JFFS2 (เหตุผลที่รวมเป็นก้อนเดียว)

binwalk รายงาน JFFS2 ทุกครั้งที่เจอ node header → ถ้า carve ทีละ node จะกระจัดกระจาย  
ใน v2 รวม offset แรก → EOF เพื่อให้ได้ไฟล์ระบบ config ครบชุด  
เฉพาะกรณี debug โครงสร้าง node ค่อยใช้ `--multi-jffs2`

---

## 12. การแกะ Kernel (uImage) และ Payload LZMA

ถ้าใช้ `--include-kernel` จะได้ไฟล์ kernel_X.uImage  
แยก payload:
```
dd if=kernel_0x60000.uImage of=kernel_payload.lzma bs=1 skip=$((0x40))
lzma -dc kernel_payload.lzma > kernel_unpacked 2>/dev/null || echo "ลองใช้ binwalk -e"
```

หรือ:
```
binwalk -e kernel_0x60000.uImage
```

---

## 13. การ Repack RootFS กลับเข้าเฟิร์มแวร์

ตัวอย่าง:
```
scripts/repack_rootfs.sh \
  --rootfs-dir workspaces/auto_v2_2025XXXXXX/rootfs_1 \
  --orig-fw input/firmware.bin \
  --offset 0x240000 \
  --partition-size 0x3D0000 \
  --out-fw firmware_mod.bin
```

ตรวจ:
```
binwalk firmware_mod.bin | grep -i squash
```

ข้อควรจำ:
- ห้ามใหญ่เกิน partition-size
- ยังไม่ได้ปรับ checksum/signature ขั้นสูง (ถ้ามี secure boot ต้องทำแยก)

---

## 14. การสร้าง Patch ของการแก้ไข

```
scripts/generate_patch.sh \
  --original rootfs_before \
  --modified rootfs_after \
  --out changes.patch
```

ใช้สำหรับรีวิว / แชร์ diff

---

## 15. สคริปต์ตรวจเร็ว (inspect_fs.sh)

```
scripts/inspect_fs.sh workspaces/auto_v2_2025XXXXXX
less workspaces/auto_v2_2025XXXXXX/inspection/rootfs_summary.txt
```

รายงาน:
- ขนาด rootfs แต่ละอัน
- จำนวนไฟล์
- Accounts (passwd/shadow)
- Version strings

---

## 16. การคำนวณ Offset / ขนาด (Hex ↔ Decimal)

แปลง hex → dec:
```
echo $((0x240000))
```

แปลง dec → hex:
```
printf "0x%X\n" 2359296
```

ตัวอย่าง dd:
```
dd if=input/firmware.bin of=rootfs1.sqsh bs=1 skip=$((0x240000)) count=$((0x3D0000))
```

---

## 17. ความปลอดภัย / สิ่งที่ควรและไม่ควรทำ

Do:
- สำรองเฟิร์มแวร์ต้นฉบับเสมอ
- ตรวจสอบขนาดพาร์ทก่อนเขียนทับ
- การเปลี่ยนไฟล์ system ให้รักษาสิทธิ์ (chmod / owner)
- ใช้ sandbox (เครื่อง VM) ในการทดสอบ

Don’t:
- Flash โดยไม่ตรวจ header/CRC
- ลบไฟล์ init/system libraries สำคัญ
- ใช้ path มีช่องว่างเมื่อทำ dd manual โดยไม่ระวัง

---

## 18. ตารางอาการ / วิธีแก้ (Troubleshooting Table)

| อาการ | สาเหตุ | วิธีแก้ |
|-------|--------|---------|
| binwalk ขึ้น “Cannot open file --version” | alias ทับ | `unalias binwalk; type -a binwalk` |
| FMK error `shared-ng.inc` | ไม่ cd เข้า FMK root | ใช้ fw-manager (แพตช์แล้ว) |
| JFFS2 แตกหลายสิบโฟลเดอร์ | ใช้ carve v1 | ใช้ v2 (unified) |
| unsquashfs FAILED | compression พิเศษ | ติดตั้ง sasquatch / ใช้ binwalk -e |
| jefferson FAILED | carve fragment / node เสีย | ใช้ jffs2_full (v2) อีกครั้ง |
| Repack ขนาดเกิน | ไฟล์เพิ่มเกิน partition-size | ลบไฟล์ไม่จำเป็น / เปลี่ยน compression |
| Patch ใหญ่เกิน | รวมไฟล์ binary | กรองไฟล์ใหญ่ / ลบไฟล์ชั่วคราวก่อน diff |

---

## 19. ปัญหาพบบ่อย (Common Issues)

1. ใช้ path placeholder → ลืมเปลี่ยน → cp fail  
2. ติดตั้ง binwalk จาก PyPI → import error  
3. ลืม `--include-kernel` → ไม่มี kernel_*  
4. Repack แล้ว boot loop → ลบ /sbin/init หรือ symlink busybox พัง  
5. JFFS2 ไม่มีไฟล์ user → ของจริงอยู่ใน rootfs overlay (บางรุ่น)  

---

## 20. คำสั่งลัด (Quick Reference)

One-touch:
```
./firmware_setup.sh --firmware /abs/path/fw.bin --include-kernel
```

Fallback carve ตรง ๆ:
```
scripts/extract_multi_auto_v2.sh input/firmware.bin --include-kernel
```

ดูสรุป:
```
cat workspaces/auto_v2_*/summary_segments.txt
```

Inspect:
```
scripts/inspect_fs.sh workspaces/auto_v2_*
```

Repack:
```
scripts/repack_rootfs.sh --rootfs-dir <dir> --orig-fw input/firmware.bin \
  --offset 0x240000 --partition-size 0x3D0000 --out-fw firmware_mod.bin
```

Patch:
```
scripts/generate_patch.sh --original rootfs_before --modified rootfs_after --out changes.patch
```

Kernel auto + payload:
```
scripts/extract_kernels.sh --firmware input/firmware.bin --auto --dump-payload
```

---

## 21. FAQ (ถามบ่อย)

**ถาม:** ต้องเพิ่ม binwalk ใน requirements.txt ไหม?  
**ตอบ:** ไม่จำเป็น ใช้ apt ดีกว่า (PyPI รุ่นเก่า)

**ถาม:** จะรู้ว่า rootfs ไหนคือ main?  
**ตอบ:** ดูขนาดใหญ่สุด + มี /sbin/init + busybox + etc ครบ

**ถาม:** เพิ่มไฟล์จนใหญ่ ใส่กลับไม่ได้?  
**ตอบ:** ลบไฟล์ log/unused, ลด binary, เช็ค padding

**ถาม:** รวม JFFS2 ทำไม?  
**ตอบ:** Node หลายชุดคือ partition เดียวกัน (ไม่จำเป็นต้องแตกแยก)

**ถาม:** ต้องแก้ Kernel อย่างไรถึง rebuild uImage?  
**ตอบ:** ใช้ `mkimage` (จาก u-boot-tools) ห่อ LZMA payload ใหม่ (ยังไม่รวมในสคริปต์)

---

## 22. แนวทางต่อยอด (Future Ideas)

- รองรับ UBIFS / UBI volume mapping  
- ตรวจและ regenerate uImage header CRC / image checksum  
- เสริม signature verification / secure boot hooks  
- เพิ่มตัวช่วย diff ระหว่าง rootfs หลายเวอร์ชันอัตโนมัติ  
- GUI ฟังก์ชัน (ใช้ PySide6 ที่มีใน requirements)  
- เพิ่มโมดูลแปลง overlay (union FS) ถ้าพบ  

---

## ภาคผนวก: ตัวอย่างวัฏจักรเต็ม (End-to-End Example)

```
# 1) Setup + Extract
./firmware_setup.sh --firmware /firmwares/cw4t.bin --include-kernel

# 2) ตรวจ rootfs
scripts/inspect_fs.sh workspaces/auto_v2_2025XXXXXX

# 3) แก้ไข rootfs_1 (เช่น เพิ่ม busybox applet / script)
vim workspaces/auto_v2_2025XXXXXX/rootfs_1/usr/bin/custom.sh
chmod +x workspaces/auto_v2_2025XXXXXX/rootfs_1/usr/bin/custom.sh

# 4) Repack
scripts/repack_rootfs.sh \
  --rootfs-dir workspaces/auto_v2_2025XXXXXX/rootfs_1 \
  --orig-fw input/firmware.bin \
  --offset 0x240000 \
  --partition-size 0x3D0000 \
  --out-fw firmware_mod.bin

# 5) Diff patch (re-extract original rootfs to rootfs_orig ก่อน)
scripts/generate_patch.sh \
  --original rootfs_orig \
  --modified workspaces/auto_v2_2025XXXXXX/rootfs_1 \
  --out changes.patch
```

---

## สรุปสั้น (TL;DR)

ใช้ `firmware_setup.sh` เพื่อ setup + extract  
ถ้า FMK fail → auto fallback ไป carve v2  
วิเคราะห์ main rootfs → แก้ → `repack_rootfs.sh` → ได้ firmware_mod.bin  
ตรวจ `summary_segments.txt` กำกับ offset ทุกครั้งก่อน dd หรือ repack  
สำรองต้นฉบับเสมอ และอย่า flash โดยไม่ตรวจสอบ

---

หากต้องการ:
- README อังกฤษ / ญี่ปุ่น
- ตัวอย่างสคริปต์ mkimage rebuild
- เพิ่มฟีเจอร์ UBIFS

แจ้งได้เลยครับ!

ขอให้สนุกกับการวิเคราะห์เฟิร์มแวร์ : )
