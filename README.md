# ADATA HD710 Pro: enabling TRIM and UAS (JMicron JMS578)

**English** | [Русский](README.ru.md)

The ADATA HD710 Pro 5 TB external drive ships with an SMR disk behind a JMicron
JMS578 USB bridge. ADATA's bridge firmware supports neither **TRIM** (UNMAP) nor
**UAS**. On an SMR disk without TRIM, sustained writes collapse to **3–6 MB/s**
once the drive runs out of fresh zones.

Flashing the bridge with Hardkernel's JMS578 firmware v173.01.00.02, with the
NVRAM patched back to ADATA's names, enables both. Writes become **~98 MB/s,
flat**.

This repo contains:
- `jms578_nvram.py`, a script that decodes and patches the NVRAM config block
  of JMS578 images. It builds the image from the **official Hardkernel file**,
  which you download yourself. No firmware binaries are included.
- `linux/50-jms578-trim.rules`, a udev rule. Without it, Linux keeps TRIM
  disabled even after the reflash.
- Everything learned along the way: the NVRAM map, the experiments, the open
  questions.

> ⚠️ **At your own risk.** Reflashing may void the warranty. Restore the original
> firmware before any warranty claim (see [Rollback](#rollback)).
> Data on the disk is not touched by a bridge reflash, but a bad flash can
> leave the enclosure unusable until you recover it via the SPI flash.

## Hardware (tested unit)

| | |
|---|---|
| Enclosure | ADATA HD710 Pro 5 TB (AHD710P-5TU31), USB 3.2 Gen1 Micro-B |
| Disk | WD50NPJZ-00CBYT0 (2.5", 15 mm, 4800 rpm, **SMR**, supports TRIM) |
| Bridge | JMicron **JMS578**, ADATA firmware **v119.2.0.3** |
| USB ID (stock) | `125f:a75a` A-DATA HD710 PRO, **Bulk-Only only** (`usb-storage`) |
| Host | Linux 6.1 (arm64 SBC), USB 3.0 |

Stock `sg_vpd -p bl` showed *Maximum unmap LBA count: not implemented*, and
`lsblk -D` showed `DISC-MAX 0B`.

## Results

20 GB file, `dd ... oflag=direct conv=fsync`, same USB port:

| | Write | Read | USB mode |
|---|---|---|---|
| Stock ADATA firmware | ~33 MB/s, **drops to 3–6 MB/s** on long writes | 57–70 MB/s | Bulk-Only, no TRIM |
| **Hardkernel v173 + ADATA names** | **98.5 MB/s, flat** | 106 MB/s | **UAS + TRIM** |
| (reference) Seagate Expansion 1 TB | 107 MB/s | 126–143 MB/s | UAS |

The first full `fstrim` trimmed 1.8 TiB in ~7 minutes with no errors. Over Samba,
writes run at 85–104 MB/s, so the disk itself is now the limit.

## What you lose

The HD710 Pro has a **shock sensor**. ADATA says it halts drive activity during
a shock and lights a **red LED**. This logic lives in **ADATA's bridge code**.
With the Hardkernel code:
- the shock sensor does nothing;
- the **red LED is permanently on**. This comes from the Hardkernel code itself,
  not from the NVRAM (see the experiments below).

For a drive that sits still next to a server, this is an acceptable trade. For
a drive you carry around, think twice.

## Firmware structure (JMS578)

An SPI image is **50688 bytes = 50176 bytes of 8051 code + 512 bytes of NVRAM at
`0xC400`**.

- The **NVRAM has no checksum**. Checked on 34 different JMS578 images: two
  images from the same vendor differ in a single serial-number character and
  both work.
- The **code area has a checksum at `0x3FC–0x3FF`**. The bridge also sets a flag
  at **`0x207` (00→01)** after its first boot and rewrites that checksum. So a
  dump read back from a used bridge differs from the release file in exactly
  these 5 bytes. This applies to both Hardkernel and ADATA code.
- The widely shared *"v173.1.0.2 with SMART + Serial + Powermode Support.bin"*
  (odroid forum, 2021) is byte-identical to the Hardkernel release except for
  exactly these 5 bytes. It looks like a readback from a used bridge, not a
  different firmware.

### NVRAM map

The `Source` column shows where each meaning comes from: **Zibri** = Zibri's
JMS577/578/579 customizer (`script2.js`), **obs** = our own observations.

| Offset | Meaning | Source |
|---|---|---|
| `0xC400–C403` | VID, PID (little endian). HK `152d:0578`, ADATA `125f:a75a` | obs |
| `0xC40C` | USB manufacturer string descriptor: `[len=2+2n][0x03][ASCII…]`, up to 14 chars (`0xC40E–C41B`) | obs |
| `0xC41C` | **unknown**. HK `03`, ADATA `00`. Together with `0xC4F3` it gates TRIM in the HK code | obs |
| `0xC430` | USB product string descriptor, same format, up to 34 chars | obs |
| `0xC454` | USB serial descriptor, same format, up to 16 chars at `0xC456`. `0x00` = report the HDD's own serial | Zibri + obs |
| `0xC4C8` | SCSI INQUIRY vendor (8 bytes, space-padded) | obs |
| `0xC4D0` | SCSI INQUIRY product (16 bytes, space-padded) | obs |
| `0xC4E7` | bit7 = 4K sectors (inverted), **bit6 = UAS**, bit5 = MultiSec. HK `c3`, ADATA `83` | Zibri, confirmed |
| `0xC4F2` | bit3 = energy saving, bit5 = LED **not** inverted. Both HK and ADATA use `38` | Zibri |
| `0xC4F3` | **unknown**. HK `c1`, ADATA `05`. The low bits differ between vendors (0/1/5/7/8/9). Gates TRIM together with `0xC41C` | obs |
| `0xC4F6–C4F7` | spin-down timeout, seconds, big endian. `0` = never. HK 600, ADATA 180 | Zibri, obs |

`python3 jms578_nvram.py info image.bin` decodes all of these.

## Experiments

All were flashed on the unit described above and verified with `sg_vpd -p lbpv`
(`LBPU`) and `lsusb -t`.

| # | Code | NVRAM changes | UAS | TRIM (LBPU) | LEDs |
|---|---|---|---|---|---|
| 0 | ADATA v119.2.0.3 | stock | ❌ | ❌ | blue only |
| 1 | ADATA v119.2.0.3 | VID:PID `152d:0578`, `C41C=03`, **`C4E7=c3` (UAS)**, `C4F3=c5` | ✅ | ❌ 0 | not recorded |
| 2 | ADATA v119.2.0.3 | as #1 but `C4F3=c1` (= full HK config) | ✅ | ❌ 0 | **blue only** |
| 3 | Hardkernel v173.01.00.02 | HK config + ADATA strings (**the result**) | ✅ | ✅ 1 | blue + **red always on** |
| 4 | Hardkernel v173.01.00.02 | as #3 but `C41C=00`, `C4F3=05` (ADATA values) | ✅ | ❌ 0 | blue + red |

Conclusions:
- **UAS on ADATA's code works**: just set bit 6 of `0xC4E7`.
- **ADATA's code has no TRIM at all.** Even with the complete HK NVRAM, it
  reports UNMAP as *not implemented*. Hardkernel's changelog says TRIM was
  added in their code: v173.01.00.01 "SAT and fstrim support", v173.01.00.02
  "Fix TRIM command".
- **In Hardkernel's code, TRIM is enabled by `0xC41C` and/or `0xC4F3`.** Which
  of the two, or which bit, is not yet isolated.
- **The red LED comes from Hardkernel's code**, not from these NVRAM bytes.

## How to

You need: Linux, `python3`, `sg3-utils`, a USB 3.0 port, and Hardkernel's
**`JMS578FwUpdate`** tool. It is a static ARM binary, so it runs on ARM boards.
On x86 use the Windows tool or qemu-user. All files are on the
[ODROID wiki](https://wiki.odroid.com/odroid-xu4/software/jms578_fw_update).
A mirror is in [hferreira23/JMS578](https://github.com/hferreira23/JMS578).

1. **Download the official firmware** `JMS578-Hardkenel-Release-v173.01.00.02-20190306.bin`
   and check it: sha256 must be
   `e815f7176807add17ae0b6b04fd44f9a1de5fc93e956ac61a74ab6a71d71e4b8`
   (the script also checks this).
2. **Stop everything** that uses the disk, then unmount it. The bridge will be
   power-cycled at step 6.
3. **Read the version and back up the original firmware.** Keep this file, you
   need it for warranty:
   ```bash
   ./JMS578FwUpdate -d /dev/sdX -v          # -> Bridge Firmware Version: v119.2.0.3
   ./JMS578FwUpdate -d /dev/sdX -b ./adata-original.bin
   python3 jms578_nvram.py info adata-original.bin   # shows your enclosure serial
   ```
4. **Build the image** from the Hardkernel file:
   - `--serial` sets the USB serial the enclosure reports. Pass the serial
     shown for your enclosure by `info` in step 3 (or by `lsusb -v`), or `hdd`
     to pass through the disk's own serial;
   - `--spindown` sets the spin-down timeout in seconds. The default is
     600 s (10 min), `0` disables it;
   - `--adata-vidpid` sets the USB ID to `125f:a75a`. By default the image
     keeps `152d:0578`, so Linux applies its JMS578 quirks.
   ```bash
   python3 jms578_nvram.py hd710pro JMS578-Hardkenel-Release-v173.01.00.02-20190306.bin \
       --serial YOURSERIAL -o hd710pro-hk173.bin
   ```
5. **Flash.** The tool verifies the write itself and should print
   `Programming & Compare Success!!`:
   ```bash
   ./JMS578FwUpdate -d /dev/sdX -f ./hd710pro-hk173.bin -b ./backup-before-flash.bin
   ```
6. **Cold start:** unplug the USB cable, wait 10 s, plug it back in.
7. **Verify:**
   ```bash
   lsusb -t                      # Driver=uas
   ./JMS578FwUpdate -d /dev/sdX -v   # v173.1.0.2
   sg_vpd -p lbpv /dev/sdX       # LBPU=1
   ```
8. **Enable TRIM in Linux.** The kernel sets `provisioning_mode=disabled` for this
   device even though the bridge reports UNMAP. Install the udev rule:
   ```bash
   sudo cp linux/50-jms578-trim.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger --action=add /sys/block/sdX
   cat /sys/block/sdX/device/scsi_disk/*/provisioning_mode   # unmap
   lsblk -D /dev/sdX                                          # DISC-MAX 4G
   ```
   Note that a rule matching `SUBSYSTEM=="scsi_disk"` **does not work** on
   hotplug: it fires before the kernel sets the mode and gets overwritten. The
   rule in this repo writes the mode when the block device appears. It was
   tested on replug and after a reboot. It also sets `read_ahead_kb=4096`.
9. Mount the disk and run `fstrim -v /mountpoint` once. After that,
   `fstrim.timer` keeps the disk trimmed.

## Rollback

Same steps 2–3, then flash your own backup and do a cold start:
```bash
./JMS578FwUpdate -d /dev/sdX -f ./adata-original.bin
```
If the bridge does not enumerate at all, open the enclosure. Hold the SPI flash
MISO pin to ground while powering up: the bridge then boots its internal ROM
code. Then flash the backup.

Want **UAS but keep ADATA's shock sensor** (no TRIM)? Patch your own backup:
```bash
python3 jms578_nvram.py patch adata-original.bin --uas on -o adata-uas.bin
```
For an SMR disk this is pointless, because the write collapse is caused by the
missing TRIM, not by the USB protocol.

## Open problems — help wanted

1. **Shock sensor and red LED with Hardkernel's code.** Find which GPIO drives
   the red LED and which GPIO the sensor uses, and make the HK code leave the
   LED off or implement the pause on shock. It needs disassembly of the 8051
   code. ADATA's and HK's code come from the same JMicron SDK (~86% similar),
   but the functions sit at different addresses.
2. **TRIM in ADATA's code.** Port the UNMAP → ATA DATA SET MANAGEMENT translation
   from HK v173.01.00.02 into ADATA v119.2.0.3. Remember to recompute the code
   checksum at `0x3FC`.
3. **Which bit enables TRIM**: `0xC41C` (00/03) or `0xC4F3` (05/c1). Test one at
   a time on the HK code.
4. The meaning of the other NVRAM bytes, and of the ADATA-only low bits `5` in
   `0xC4F3`.

PRs and issue reports with your own experiments (always state the code version,
the NVRAM diff, and `LBPU`/`lsusb -t`/LED results) are welcome.

## Credits

- Hardkernel, for the JMS578 firmware with TRIM and the flashing tool:
  [ODROID wiki](https://wiki.odroid.com/odroid-xu4/software/jms578_fw_update),
  [forum t=28241](https://forum.odroid.com/viewtopic.php?t=28241)
- Zibri, for the [JMS577/578/579 customizer](https://zibri.github.io/JMS579/index2.html)
  with the meaning of the NVRAM bits
- BetterFirmware and others, [forum t=41926](https://forum.odroid.com/viewtopic.php?t=41926)
- Firmware collections: [usbdev.ru](https://www.usbdev.ru/files/jmicron/jms578firmware/),
  [hferreira23/JMS578](https://github.com/hferreira23/JMS578)

The scripts and documentation are under the MIT license. The firmware and the
flashing tool are not included and belong to JMicron, Hardkernel and ADATA.
