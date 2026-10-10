#!/usr/bin/env python3
"""Inspect and patch the NVRAM (config) block of JMicron JMS578 firmware images.

A JMS578 SPI image is 50688 bytes: 50176 bytes of 8051 code + a 512-byte NVRAM
block at 0xC400 (USB IDs, strings, feature flags). The NVRAM block has no
checksum (verified on 34 images), so it can be edited safely. The code part is
NOT touched by this tool.

Commands:
  info    FILE                 show decoded NVRAM fields
  diff    A B                  show differing NVRAM bytes
  patch   IN -o OUT [options]  generic NVRAM patch
  hd710pro HK -o OUT --serial S
                               build the image used for the ADATA HD710 Pro from
                               the official Hardkernel v173.01.00.02 release
"""
import argparse
import hashlib
import sys

SIZE = 50688
NV = 0xC400

HK_V173_0102_SHA256 = "e815f7176807add17ae0b6b04fd44f9a1de5fc93e956ac61a74ab6a71d71e4b8"

# offsets inside the image
VIDPID = 0xC400          # VID LE, PID LE
USB_MFR = 0xC40C         # USB string descriptor: [len][0x03][ASCII...], len = 2 + 2*chars
USB_MFR_MAX = 14         # 0xC40E-0xC41B (0xC41C is a config byte)
USB_PROD = 0xC430
USB_PROD_MAX = 34        # 0xC432-0xC453
USB_SER = 0xC454
USB_SER_MAX = 16         # up to 0xC465
INQ_VENDOR = 0xC4C8      # SCSI INQUIRY vendor, 8 bytes, space padded
INQ_PRODUCT = 0xC4D0     # SCSI INQUIRY product, 16 bytes, space padded
FLAGS_E7 = 0xC4E7        # bit7 = !4K block, bit6 = UAS, bit5 = MultiSec (per Zibri's customizer)
FLAGS_F2 = 0xC4F2        # bit3 = energy saving, bit5 = !LED invert (per Zibri)
BYTE_1C = 0xC41C         # unknown; with Hardkernel code TRIM needs 0xC41C/0xC4F3 = 03/c1
BYTE_F3 = 0xC4F3         # unknown; low bits differ per vendor (ADATA = 5)
SPINDOWN = 0xC4F6        # big endian, seconds, 0 = never


def load(path):
    b = bytearray(open(path, "rb").read())
    if len(b) != SIZE:
        sys.exit(f"{path}: size {len(b)}, expected {SIZE} (code + NVRAM)")
    return b


def get_desc(b, off, maxchars):
    n = b[off]
    if n < 2 or b[off + 1] != 0x03:
        return None
    chars = (n - 2) // 2
    return bytes(b[off + 2:off + 2 + min(chars, maxchars)]).decode("ascii", "replace")


def set_desc(b, off, maxchars, s):
    raw = s.encode("ascii")
    if len(raw) > maxchars:
        sys.exit(f"string '{s}' too long (max {maxchars} chars)")
    b[off] = 2 + 2 * len(raw)
    b[off + 1] = 0x03
    b[off + 2:off + 2 + maxchars] = raw.ljust(maxchars, b"\0")


def set_fixed(b, off, width, s):
    raw = s.encode("ascii")
    if len(raw) > width:
        sys.exit(f"string '{s}' too long (max {width} chars)")
    b[off:off + width] = raw.ljust(width, b" ")


def info(b):
    vid = b[VIDPID] | b[VIDPID + 1] << 8
    pid = b[VIDPID + 2] | b[VIDPID + 3] << 8
    e7, f2 = b[FLAGS_E7], b[FLAGS_F2]
    sd = b[SPINDOWN] << 8 | b[SPINDOWN + 1]
    print(f"code sha256       {hashlib.sha256(b[:NV]).hexdigest()}")
    print(f"  (note: the bridge writes a flag at 0x207 and a code checksum at 0x3FC-0x3FF after first boot,")
    print(f"   so a dump read back from a used bridge differs from the release file in these 5 bytes)")
    print(f"VID:PID           {vid:04x}:{pid:04x}")
    print(f"USB manufacturer  {get_desc(b, USB_MFR, USB_MFR_MAX)!r}")
    print(f"USB product       {get_desc(b, USB_PROD, USB_PROD_MAX)!r}")
    print(f"USB serial        {get_desc(b, USB_SER, USB_SER_MAX)!r}  (0xC454 = {b[USB_SER]:#04x}; 0 = pass through HDD serial)")
    print(f"INQUIRY           {bytes(b[INQ_VENDOR:INQ_VENDOR+8]).decode('ascii','replace')!r} "
          f"{bytes(b[INQ_PRODUCT:INQ_PRODUCT+16]).decode('ascii','replace')!r}")
    print(f"0xC4E7 = {e7:#04x}     UAS={'on' if e7 & 0x40 else 'off'}  MultiSec={'on' if e7 & 0x20 else 'off'}  "
          f"4K={'on' if not e7 & 0x80 else 'off'}")
    print(f"0xC4F2 = {f2:#04x}     energy saving={'on' if f2 & 0x08 else 'off'}  LED invert={'no' if f2 & 0x20 else 'yes'}")
    print(f"0xC41C = {b[BYTE_1C]:#04x}     0xC4F3 = {b[BYTE_F3]:#04x}")
    print(f"spin-down         {sd} s" + (" (never)" if sd == 0 else f" ({sd/60:g} min)"))


def apply(b, a):
    if a.vidpid:
        v, p = (int(x, 16) for x in a.vidpid.split(":"))
        b[VIDPID:VIDPID + 4] = bytes([v & 0xFF, v >> 8, p & 0xFF, p >> 8])
    if a.manufacturer is not None:
        set_desc(b, USB_MFR, USB_MFR_MAX, a.manufacturer)
    if a.product is not None:
        set_desc(b, USB_PROD, USB_PROD_MAX, a.product)
    if a.serial is not None:
        if a.serial == "hdd":
            b[USB_SER] = 0
        else:
            if not a.serial.isalnum():
                sys.exit("serial must be alphanumeric")
            set_desc(b, USB_SER, USB_SER_MAX, a.serial)
    if a.inquiry_vendor is not None:
        set_fixed(b, INQ_VENDOR, 8, a.inquiry_vendor)
    if a.inquiry_product is not None:
        set_fixed(b, INQ_PRODUCT, 16, a.inquiry_product)
    if a.uas is not None:
        b[FLAGS_E7] = (b[FLAGS_E7] | 0x40) if a.uas == "on" else (b[FLAGS_E7] & ~0x40)
    if a.spindown is not None:
        b[SPINDOWN:SPINDOWN + 2] = a.spindown.to_bytes(2, "big")
    for kv in a.byte or []:
        off, val = (int(x, 16) for x in kv.split("="))
        if not NV <= off < SIZE:
            sys.exit(f"0x{off:x} is outside the NVRAM block (0xC400-0xC5FF); code is never patched")
        b[off] = val


def add_patch_opts(p):
    p.add_argument("--vidpid", help="e.g. 152d:0578")
    p.add_argument("--manufacturer")
    p.add_argument("--product")
    p.add_argument("--serial", help="USB serial (<=16 alnum chars) or 'hdd' to pass through the drive serial")
    p.add_argument("--inquiry-vendor")
    p.add_argument("--inquiry-product")
    p.add_argument("--uas", choices=["on", "off"])
    p.add_argument("--spindown", type=int, help="seconds, 0 = never")
    p.add_argument("--byte", action="append", help="raw NVRAM byte, e.g. C4F3=c1 (repeatable)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("file")
    s = sub.add_parser("diff"); s.add_argument("a"); s.add_argument("b")
    s = sub.add_parser("patch"); s.add_argument("input"); s.add_argument("-o", "--output", required=True)
    add_patch_opts(s)
    s = sub.add_parser("hd710pro", help="Hardkernel v173.01.00.02 + ADATA HD710 PRO names")
    s.add_argument("hk", help="JMS578-Hardkenel-Release-v173.01.00.02-20190306.bin")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--keep-hk-vidpid", action="store_true", default=True,
                   help="keep 152d:0578 so Linux applies its JMS578 quirks (default)")
    s.add_argument("--adata-vidpid", action="store_true", help="use ADATA 125f:a75a instead")
    add_patch_opts(s)
    a = ap.parse_args()

    if a.cmd == "info":
        info(load(a.file))
    elif a.cmd == "diff":
        x, y = load(a.a), load(a.b)
        d = [i for i in range(SIZE) if x[i] != y[i]]
        code = [i for i in d if i < NV]
        print(f"code bytes differing: {len(code)}" + (f" (first at {code[0]:#x})" if code else ""))
        for i in d:
            if i >= NV:
                print(f"{i:#06x}: {x[i]:02x} -> {y[i]:02x}")
    elif a.cmd == "patch":
        b = load(a.input); apply(b, a)
        open(a.output, "wb").write(b); info(b)
    elif a.cmd == "hd710pro":
        b = load(a.hk)
        h = hashlib.sha256(b).hexdigest()
        if h != HK_V173_0102_SHA256:
            sys.exit(f"unexpected sha256 {h}\nexpected the official Hardkernel v173.01.00.02 file {HK_V173_0102_SHA256}")
        if a.serial is None:
            sys.exit("--serial is required: use the serial printed on your enclosure / shown by lsusb -v "
                     "(the 12-char iSerial), or 'hdd' to report the drive's own serial")
        a.manufacturer = "ADATA" if a.manufacturer is None else a.manufacturer
        a.product = "HD710 PRO" if a.product is None else a.product
        a.inquiry_vendor = "ADATA" if a.inquiry_vendor is None else a.inquiry_vendor
        a.inquiry_product = "HD710 PRO" if a.inquiry_product is None else a.inquiry_product
        if a.adata_vidpid:
            a.vidpid = "125f:a75a"
        apply(b, a)
        open(a.output, "wb").write(b)
        info(b)
        print(f"\nwritten {a.output}  sha256 {hashlib.sha256(b).hexdigest()}")


if __name__ == "__main__":
    main()
