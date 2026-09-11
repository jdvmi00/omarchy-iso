# surfacelog — initramfs add-on that logs a live boot to the boot stick

A second, uncompressed initrd (`surfacelog.cpio`, newc, exactly 14336 bytes,
the size of its slot on the ISO) that GRUB appends to the archiso initramfs. It adds `hooks/surfacelog` and replaces
`config` so the hook runs right after `udev`, as the first late hook and the
first emergency hook. From then on the kernel log and some device state are
rewritten every 3 s onto the stick's FAT partition `ARCHISO_EFI`, before *and*
after `switch_root`, so a machine with no display/keyboard/network can be
debugged by pulling the stick afterwards.

Files:

- `rootfs/config` — original `config` with `surfacelog` inserted after `udev` in
  `HOOKS`, first in `LATEHOOKS`, first in `EMERGENCYHOOKS`.
- `rootfs/hooks/surfacelog` — the ash hook (run_hook / run_latehook / run_emergencyhook).
- `surfacelog.cpio` — `find . -mindepth 1 | cpio -o -H newc -R 0:0` of `rootfs/`.
- `_test/sim.sh` — user-namespace simulation of init → hook → real util-linux
  `switch_root` used to validate that the loop survives; not needed on the stick.

## Loading it from GRUB

Copy `surfacelog.cpio` to the root of the `ARCHISO_EFI` FAT32 partition of the
stick (it is writable, unlike the ISO 9660 partition). In the menu entry keep
the `linux` line and change only the `initrd` line, adding a `search` before it:

```
search --no-floppy --label ARCHISO_EFI --set=dbg
initrd /arch/boot/aarch64/initramfs-linux.img ($dbg)/surfacelog.cpio
```

`$root` stays the ISO 9660 partition (set by archiso's own `search --label`),
so the first path is unchanged; `($dbg)/surfacelog.cpio` is read from the FAT
partition. Useful additions to the `linux` line:

- `rd.log=kmsg rd.debug` — mkinitcpio's own `set -x` trace of `/init` goes to
  the kernel log and therefore into every `dmesg.txt` snapshot (shows exactly
  where init stops).
- `log_buf_len=8M` — so an early flood of messages is not lost from `dmesg`.
- `surfacelog_wait=N` (default 25 s to wait for the partition),
  `surfacelog_dev=/dev/sdX2` (override the device; a plain device path),
  `disablehooks=surfacelog` (turn the hook off without touching the cpio).
- `surfacelog_reboot=N` (default 0 = off): if the log partition is still not
  mounted N seconds after the hook started, the loop logs
  `surfacelog: no log device after N s, rebooting to preserve ramoops`, runs
  `sync`, waits 3 s, enables sysrq and writes `b` to `/proc/sysrq-trigger`
  (warm reset, ramoops kept). Works before and after switch_root (the loop
  reaches `/proc` as `../../proc`). The initial by-label poll is shortened to N
  so the reset is not delayed by it.
- `surfacelog_show=1`: `run_hook` mounts pstore and, if
  `/sys/fs/pstore/console-ramoops*` or `dmesg-ramoops*` exist, pages the
  previous boot's console log to `/dev/console` in the background: first a
  50-line summary (case-insensitive matches of
  `surfacelog|dwc3|xhci|usb|phy|dp_|drm|msm|panel|edp|error|fail|timeout|-110|-517`,
  deduplicated, most recent last), then the last 1200 lines in pages of 50
  with a `=== surfacelog: previous boot console log, page P/T (lines A-B of N) ===`
  header and 12 s between pages. The plymouth hook is disabled for that boot
  (`chmod 644 /hooks/plymouth`, the same thing `disablehooks=` does) so the
  splash cannot cover the text. If pstore is empty, one line saying so goes to
  the console and kmsg. Independently of this knob, all pstore files are staged
  in `/run/surfacelog-rt/pstore/` and copied into `boot-N/pstore-<name>` if the
  partition ever mounts.

Concatenated initrds are fine: mkinitcpio's `/init` only reads `/config` and
`/hooks/*` from the unpacked rootfs, and the kernel unpacks each archive of the
concatenated initramfs in turn (a zstd/gzip archive followed by a plain cpio is
supported, GRUB pads each file to 4 bytes). Later entries overwrite earlier
files, so the add-on's `config` replaces the original and `hooks/surfacelog` is
added. This is the same mechanism archiso already uses for `*-ucode.img`.

The menu `grub.cfg` lives on the read-only ISO 9660 partition
(`/boot/grub/grub.cfg`, loaded by the embedded config of `EFI/BOOT/BOOTAA64.EFI`).
Ways to get the edited lines in: press `e` in the GRUB menu (the firmware
display usually still works when Linux's does not); or remaster with
`xorriso -indev in.iso -outdev out.iso -boot_image any replay -update grub.cfg /boot/grub/grub.cfg`
and re-write the stick (then copy `surfacelog.cpio` back onto `ARCHISO_EFI`).

## Where the logs land

On the `ARCHISO_EFI` partition (mounted at `/run/surfacelog` during boot):

```
boot-count                    incremented once per boot
boot-N/info.txt               boot number, how the partition was found, /proc/version, /proc/cmdline
boot-N/dmesg.txt              full kernel log, rewritten every 3 s (written to .new, then renamed)
boot-N/heartbeat.txt          "round R uptime S pid1=NAME" every 3 s; pid1 flips from init to systemd after switch_root
boot-N/state.txt              ls -l /dev/disk/by-label /dev/disk/by-id, /proc/modules, /sys/bus/platform/drivers, /proc/1/mounts
boot-N/markers.txt            "switch_root about to happen (uptime …)", "emergency shell (uptime …)"
boot-N/dmesg-pre-switch_root.txt, mounts-pre-switch_root.txt   from the late hook
boot-N/dmesg-emergency.txt, mounts-emergency.txt               from the emergency hook
boot-N/surfacelog.log         the hook's own log (device search, mount errors, loop messages)
```

`sync` runs after every round, so at most ~3 s are lost on a hard hang.

Every step is also written to the kernel log as `surfacelog: …` (the loop keeps
an fd to `/dev/kmsg` open across switch_root), so even when nothing reaches the
stick, a later `dmesg`/journal shows: hook start, runtime copies ready, device
search progress every 5 s (what `/dev/disk/by-label` contains, `blkid -lt
LABEL=ARCHISO_EFI`, `/dev/sd?2`), the exact mount command with exit status and
stderr, the boot directory created, the first three dmesg writes and then one
every 30 s, and the switch_root / emergency markers. Device search order: the
by-label symlink (polled 0.5 s for `surfacelog_wait` seconds, default 25),
`blkid -lt LABEL=`, then — retried every 3 s by the loop, also after
switch_root — partition 2 of the device behind `/run/archiso/bootmnt` and every
`/dev/sd?2`, each verified with `blkid -p` to have `LABEL=ARCHISO_EFI` or
`TYPE=vfat`; the line `mount … (<how found>) -> rc=0` says which one worked. The FAT partition of an archiso stick is sized tightly; check
`df` for a few MiB of free space and delete old `boot-N` directories now and
then.

## Caveats found in init / init_functions

- `switch_root` is util-linux's (mkinitcpio's `base` hook adds it after the
  busybox symlinks). It MS_MOVEs `/dev`, `/proc`, `/sys` and `/run` (with their
  sub-mounts) into the new root, then deletes everything in the old rootfs.
  So `/run/surfacelog` survives and is visible as `/run/surfacelog` in the
  live system, but a process left behind keeps the *old, now empty* rootfs as
  its root: absolute paths like `/usr/bin/dmesg`, `/proc/uptime` or even
  `/dev/null` stop resolving, and executing a new-root binary through a relative
  path fails too, because the kernel resolves the ELF interpreter
  (`/lib/ld-linux-aarch64.so.1`) against the process root. mkinitcpio's busybox
  is dynamically linked, so it is not exempt. That is why the loop does not use
  `/usr/bin/…` paths as the spec suggested: it copies busybox, the dynamic
  loader, the needed libs, util-linux `mount` and `blkid` into
  `/run/surfacelog-rt` (tmpfs, moved along with `/run`), chdirs there and uses
  only relative paths: `../surfacelog` (the FAT partition), `../..` (the root
  that `/run` is mounted in, i.e. the real root after switch_root), and
  `./ld.so --library-path ./lib ./busybox dmesg` etc. Verified with
  `_test/sim.sh` (real util-linux switch_root in a user namespace): logging
  continues after the old root is wiped, in both the "mounted early" and the
  "partition appears only after switch_root" cases.
- The initramfs busybox is not built in standalone mode and has no `mount`,
  `setsid`, `findfs` or `blkid` applets (util-linux provides mount/blkid).
  `setsid` is therefore normally absent and the loop is started with a plain
  `&`, stdio pointed at its own log so it never holds init's console or the
  `rd.log` logger pipe open (`rdlogger_stop` would otherwise wait/kill).
- `run_hookfunctions` re-sources every hook file for each phase and only calls
  the function; the hook keeps state in `/run/surfacelog-rt/bootnum`, not in
  shell variables, and has no top-level side effects.
- Hooks run in init's shell without `set -e`; the hook nevertheless guards every
  command and always returns 0. Emergency hooks can run several times (fsck,
  mount failure, `break=`), the marker file is appended each time.
- `/init` runs `udevadm settle` in the udev hook before this one, but the USB
  stick can still be enumerating, hence the 0.5 s polling of
  `/dev/disk/by-label/ARCHISO_EFI` for up to 25 s with `blkid -lt LABEL=…`
  (and `findfs` if present) every 2 s as fallback. `vfat`/`nls_*` modules must
  be in the main initramfs (`lsinitcpio -l initramfs-linux.img | grep -E 'fat|nls_'`);
  archiso's `filesystems` hook normally includes them.
- With `archisosearchuuid=` archiso mounts every partition read-only while
  searching; a second read-only mount of the already-rw-mounted FAT partition
  is allowed by the kernel, so the two do not conflict.
