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

> **Your unit may differ.** Everything here was tested on **one** enclosure.
> Other batches, capacities (1–4 TB) or regions may ship with a different disk
> (CMR or SMR, different model), a different ADATA firmware version, or even a
> different bridge chip. **Check your unit first** (step 0 below) and stop if it
> doesn't match. If you try this on another revision, please open an issue with
> your `lsusb`, `JMS578FwUpdate -v`, disk model and results, so the list grows.

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
`0xC400`**. The firmware headers say *JMicron JMS579* even on JMS578 chips; the
same family is used in JMS576/577/578/579 bridges.

- The **NVRAM has no checksum**. Checked on 34 different JMS578 images: two
  images from the same vendor differ in a single serial-number character and
  both work.
- The second half of the NVRAM (`0xC500–C5FF`) is identical in every dump known
  (md5 `34a237c125b376b075debfaa6fbff386`, also on our ADATA and Hardkernel
  images). It is a handy check that you located the block correctly.
- The **code area has a checksum at `0x3FC–0x3FF`**. The bridge also sets a flag
  at **`0x207` (00→01)** after its first boot and rewrites that checksum. So a
  dump read back from a used bridge differs from the release file in exactly
  these 5 bytes. This applies to both Hardkernel and ADATA code.
- The widely shared *"v173.1.0.2 with SMART + Serial + Powermode Support.bin"*
  (odroid forum, 2021) is byte-identical to the Hardkernel release except for
  exactly these 5 bytes. It looks like a readback from a used bridge, not a
  different firmware.

### NVRAM map

Offsets are absolute (relative offset + `0xC400`). Sources: **tomman** =
[tomman's notes](https://helmet.kafuka.org/bboard/thread.php?id=259) (post
"JMS576/7/8/9 EEPROM offsets", plus nkma's corrections in the same thread);
**Zibri** = [Zibri's customizer](https://zibri.github.io/JMS579/index2.html);
**obs** = flashed and checked on our unit.

| Offset | Meaning | Source |
|---|---|---|
| `0xC400–C403` | VID, PID (little endian). HK `152d:0578`, ADATA `125f:a75a` | tomman, obs |
| `0xC408–C409` | USB bcdDevice? | tomman |
| `0xC40A` | SCSI identity byte. tomman's table: `0x0A` = use the SCSI strings at `0xC4C8`, anything else (usually `01`) = use the drive's ATA ID; a later post says the opposite. **Our unit: `0x0A`, and the enclosure reports the NVRAM strings**, which matches the table | tomman, obs |
| `0xC40C` | USB manufacturer string descriptor: `[len=2+2n][0x03][ASCII…]`, up to 14 chars (`0xC40E–C41B`). The length counts UTF-16 bytes, but the string is stored as ASCII | tomman, obs |
| `0xC41B–C41C` | `00 03` on HK: an empty "bogus" string descriptor that some dumps have (ADATA: `00 00`). **Not a setting**: changing `0xC41C` has no effect on TRIM (exp. #5) | tomman, obs |
| `0xC430` | USB product string descriptor, same format, up to 34 chars | tomman, obs |
| `0xC454` | USB serial descriptor, same format, up to 16 chars at `0xC456`. `0x00` = report the drive's own serial (sometimes a made-up one) | tomman, Zibri |
| `0xC4C8` | SCSI INQUIRY vendor (8 bytes, space-padded) | tomman, obs |
| `0xC4D0` | SCSI INQUIRY product (16 bytes, space-padded) | tomman, obs |
| `0xC4E0–C4E1` | `"HD"` | tomman |
| `0xC4E7` | features 1: **bit7 = USB Mass Storage (BOT)**, **bit6 = UAS**, **bit5 = 4K sector emulation** (keep off), bit1 usually set. HK `c3`, ADATA `83` (BOT only). Zibri's page has the labels of bits 7 and 5 swapped | tomman/nkma; bit6 obs |
| `0xC4F0–C4F1` | `"BC"` | tomman |
| `0xC4F2` | features 2: bit3 = power save (spin-down), **bit5 = activity-LED polarity**. HK and ADATA `38`. On the HD710 Pro, clearing bit5 (`18`) turns the **blue** LED off; the red LED is unaffected. Clearing bit4 (`28`) changed nothing visible | tomman/nkma, obs |
| `0xC4F3` | features 3: **bit6 = TRIM (UNMAP) in the HK code**. Bit7 is set in every known dump; bit3 is set in an ODD-enabled firmware. HK `c1`, ADATA `05` (bits 7–6 clear, ADATA-only bit2 set) | tomman, **obs (exp. #4, #6)** |
| `0xC4F6–C4F7` | spin-down timeout, seconds, big endian. `0` = never. HK 600, ADATA 180 | tomman, Zibri, obs |
| `0xC4F8–C4FD` | `40 0F 32 05 00 00` | tomman |
| `0xC4FE–C4FF` | `"JM"`, NVRAM identifier | tomman |
| `0xC500–C5FF` | constant block, same in all dumps | tomman, obs |

`python3 jms578_nvram.py info image.bin` decodes all of these.

## Experiments

All were flashed on the unit described above and verified with `sg_vpd -p lbpv`
(`LBPU`) and `lsusb -t`. All rows use the ADATA strings and VID:PID
`152d:0578` unless stated otherwise.

| # | Code | NVRAM changes (vs. HK config) | UAS | TRIM (LBPU) | LEDs |
|---|---|---|---|---|---|
| 0 | ADATA v119.2.0.3 | stock ADATA (`125f:a75a`) | ❌ | ❌ | blue only |
| 1 | ADATA v119.2.0.3 | ADATA config + **`C4E7=c3` (UAS)**, `C41C=03`, `C4F3=c5` | ✅ | ❌ 0 | not recorded |
| 2 | ADATA v119.2.0.3 | as #1 but `C4F3=c1` (= full HK config) | ✅ | ❌ 0 | **blue only** |
| 3 | Hardkernel v173.01.00.02 | none (**the result**) | ✅ | ✅ 1 | blue + **red always on** |
| 4 | Hardkernel v173.01.00.02 | `C41C=00`, `C4F3=05` (ADATA values) | ✅ | ❌ 0 | blue + red |
| 5 | Hardkernel v173.01.00.02 | `C41C=00`, `C4F2=18` | ✅ | ✅ 1 | **blue off**, red on |
| 6 | Hardkernel v173.01.00.02 | `C4F2=28`, `C4F3=81` | ✅ | ❌ 0 | blue blinks, red on |
| 7 | JMS578_PPE v124.01.00.02 (a third code base, from ralimtek's article) | HK config | ✅ | ⚠️ 1, but every `fstrim` DISCARD fails with *critical target error* | blue + red on |

Conclusions:
- **UAS on ADATA's code works**: just set bit 6 of `0xC4E7`.
- **ADATA's code has no TRIM at all.** Even with the complete HK NVRAM, it
  reports UNMAP as *not implemented*. Hardkernel's changelog says TRIM was
  added in their code: v173.01.00.01 "SAT and fstrim support", v173.01.00.02
  "Fix TRIM command".
- **In Hardkernel's code, TRIM is enabled by bit 6 of `0xC4F3`.** `0xC41C` does
  not matter (#5), and bit 7 alone is not enough (#6).
- **The red LED comes from Hardkernel's code.** None of the NVRAM bits tried
  (`C4F2` bits 4–5, `C4F3`, `C41C`) turns it off. `C4F2` bit 5 only inverts the
  blue activity LED.
- **PPE v124.01.00.02 is not an alternative**: it advertises UNMAP, but the
  actual TRIM commands fail (likely the bug Hardkernel fixed in v173.01.00.02,
  "Fix TRIM command"), and it lights the red LED too.

## How to

### What runs where

| Part | Platforms | Status |
|---|---|---|
| `jms578_nvram.py` (build / inspect / diff images) | **any OS**: pure Python 3, no dependencies | ✅ tested |
| Flashing: Hardkernel `JMS578FwUpdate` (v2.00 / v1.00) | **Linux on ARM**: 32-bit ARM static binary. Runs on Raspberry Pi, ODROID, other ARM SBCs, and on arm64 with 32-bit support | ✅ tested (arm64 SBC) |
| Flashing: JMicron `FwUpdateTool` (`FwUpdateTool_v1_19_16_24.exe`) | **Windows**: the chip vendor's own GUI tool, same functions (backup, flash `.bin`) | ⚠️ not tested by us |
| Flashing: `JMS578FwUpdate` via `qemu-user-static` (`qemu-arm`) | **Linux on x86-64** | ⚠️ not tested. The binary is static, so it should start; whether SG_IO passthrough works under emulation is unknown |
| Flashing: [BertoldVdb/jms578flash](https://github.com/BertoldVdb/jms578flash) (open source) | **any Linux**, incl. x86-64 | ⚠️ not tested by us. Reported working on a JMS579 (tomman's thread). By default it injects its own SPI code into the image, so a readback won't match the file; verify the NVRAM region only, or use `-hook=false` |
| TRIM afterwards (`fstrim`, udev rule) | Linux | ✅ tested |
| TRIM afterwards | Windows / macOS | ⚠️ not tested. Windows 10/11 should issue TRIM to UAS devices that report UNMAP; check with `fsutil behavior query DisableDeleteNotify` and the drive optimizer |

All tools are on the
[ODROID wiki](https://wiki.odroid.com/odroid-xu4/software/jms578_fw_update);
a mirror is in [hferreira23/JMS578](https://github.com/hferreira23/JMS578).
**Always make a backup (`-b`, or "Backup" in the Windows tool) before
flashing.** If you succeed with the Windows tool or qemu, please report it in an
issue.

The steps below use the Linux/ARM tool. You also need `python3`, `sg3-utils`
(and `smartmontools` for step 0) and a USB 3.0 port. With the Windows tool, do
steps 2–6 in its GUI (procedure from [ralimtek](https://ralimtek.com/posts/2021/jms578/)
and tomman's thread):
- the drive must be in the enclosure, otherwise the bridge does not enumerate;
- tick **"RD Version"** to show the extra options;
- backup: tick **"Backup Old Firmware Only"**, choose a file, *Run*; make a second
  backup and compare the two;
- flash: untick the backup option, *Load File* = the image from step 4, and
  **keep "Include JMS577 NVRAM" ticked**. Our image needs its NVRAM: the ADATA
  names and the TRIM bit live there. Then *Run* and power-cycle.

0. **Check your unit:**
   ```bash
   lsusb                          # stock: 125f:a75a A-DATA ... HD710 PRO
   ./JMS578FwUpdate -d /dev/sdX -v  # must print "Bridge Firmware Version: ..."; if it fails, it is not a JMS578 — stop
   sudo smartctl -i -d sat /dev/sdX # disk model; is it SMR? does it support TRIM ("TRIM Command: Available")?
   ```
   If your disk is CMR, TRIM gives little benefit: UAS alone may be all you want,
   and you can keep the shock sensor (see [Rollback](#rollback), `--uas on`).
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

### Alternative: no NVRAM at all

[ralimtek](https://ralimtek.com/posts/2021/jms578/) erases the whole flash and
writes only the code (Windows tool: *Erase All Flash Only*, then flash with
*Include JMS577 NVRAM* unticked). The bridge then runs on built-in defaults: it
reports the drive's real model and serial and does not spin it down. We have not
tried this on the HD710 Pro. You lose the ADATA names, and it is unknown whether
TRIM is on by default in the HK code.

The same article describes the recovery from a bad flash: short the SPI flash
**MISO pin to ground for ~1 s at power-up**. The bridge then boots from its
internal ROM, and you can erase and reflash.

### If UAS misbehaves

On some JMS578 boards UAS is unstable in hardware (stalls, data corruption,
growing `UDMA_CRC_Error_Count` in SMART), and no firmware fixes it (see
tomman's thread). Ours has been stable, but watch SMART attribute 199 and
`dmesg` for resets. If it happens, turn UAS off and keep TRIM, either
- in the NVRAM: `python3 jms578_nvram.py patch hd710pro-hk173.bin --uas off -o hd710pro-hk173-bot.bin`, then flash it; or
- on the host: boot with `usb-storage.quirks=152d:0578:u`.

TRIM also works over plain USB Mass Storage with the HK firmware. The udev rule
is still needed.

SMART: use `smartctl -d sat`. smartmontools picks the bridge type by VID:PID, and
`152d:0578` is in its database.

## Open problems — help wanted

1. **Shock sensor and red LED with Hardkernel's code.** Find which GPIO drives
   the red LED and which GPIO the sensor uses, and make the HK code leave the
   LED off or implement the pause on shock. The NVRAM bits are exhausted (see
   the experiments), so it needs disassembly of the 8051 code. ADATA's and HK's
   code come from the same JMicron SDK (~86% similar), but the functions sit at
   different addresses.
2. **TRIM in ADATA's code.** Port the UNMAP → ATA DATA SET MANAGEMENT translation
   from HK v173.01.00.02 into ADATA v119.2.0.3. Remember to recompute the code
   checksum at `0x3FC`.
3. The remaining unknown bits: `0xC4E7` bits 2/0, `0xC4F2` bits 6/4,
   `0xC4F3` bit 0 and the ADATA-only bit 2.
4. Does the Windows flasher, qemu-user or `jms578flash` work for this enclosure?

PRs and issue reports with your own experiments (always state the code version,
the NVRAM diff, and `LBPU`/`lsusb -t`/LED results) are welcome.

## Credits

- Hardkernel, for the JMS578 firmware with TRIM and the flashing tool:
  [ODROID wiki](https://wiki.odroid.com/odroid-xu4/software/jms578_fw_update),
  [forum t=28241](https://forum.odroid.com/viewtopic.php?t=28241)
- tomman (dilworks) and nkma, for the most complete NVRAM layout notes:
  [bboard thread](https://helmet.kafuka.org/bboard/thread.php?id=259),
  [Zibri/JMS579#3](https://github.com/Zibri/JMS579/issues/3)
- Zibri, for the [JMS577/578/579 customizer](https://zibri.github.io/JMS579/index2.html)
- Ralim, for the [JMS578 article](https://ralimtek.com/posts/2021/jms578/) (Windows procedure, blank NVRAM, recovery)
- BertoldVdb, for the open-source [jms578flash](https://github.com/BertoldVdb/jms578flash)
- BetterFirmware and others, [forum t=41926](https://forum.odroid.com/viewtopic.php?t=41926)
- Firmware collections: [usbdev.ru](https://www.usbdev.ru/files/jmicron/jms578firmware/),
  [hferreira23/JMS578](https://github.com/hferreira23/JMS578)

The scripts and documentation are under the MIT license. The firmware and the
flashing tool are not included and belong to JMicron, Hardkernel and ADATA.
