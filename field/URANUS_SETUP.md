# Uranus Card Setup

## Newer Hardware: LT6911UXC Bridge

On 2026-11-01, an updated Uranus card ran Ubuntu 22.04.5, vendor kernel
`5.10.160 #267` (2026-10-15), Ethernet MAC `0a:d1:0f:8e:9e:b1`. Its camera
input uses an LT6911UXC HDMI-to-MIPI bridge, not native `rk_hdmirx`:

```text
LT6911UXC 6-002b -> csi2-dphy3 -> rkcif-mipi-lvds4 -> /dev/video22
```

The bridge detected 1280x720 progressive at 49.99 FPS. The existing repo sender
successfully delivered camera images and overlay to the home PC at 1280x720 /
12 FPS / H.265 with only `VIDEO_DEVICE=/dev/video22`. After reconnection/reboot,
the input changed to 1920x1080 at approximately 25 FPS. Automatic negotiation
then selected 1280x720 YUYV capture and produced gray/corrupted frames. Explicit
native-size NV12 capture with six source buffers restored clear camera images,
still scaled to 1280x720/12 FPS for transmission. **Keep this revision's
kernel and device tree; do not apply the older HDMI DTB procedure below.**
Its factory `uranus-demo.service` already captures `/dev/video22` and
`/dev/video0`. Temporarily stop it before using our sender; do not disable or
edit the service. Starting it again also runs a vendor `killall gst-launch-1.0`
pre-command, so do not run the demo and our capture pipelines together.

After copying `field` to `/home/ubuntu/Desktop/workbench/next_vision_rocky`,
install uv as below, then use the existing Python 3.10.12:

```bash
cd /home/ubuntu/Desktop/workbench/next_vision_rocky/field
/home/ubuntu/.local/bin/uv sync --locked --python /usr/bin/python3
sudo systemctl stop uranus-demo.service
sudo .venv/bin/python -u proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000
```

In another field terminal:

```bash
cd /home/ubuntu/Desktop/workbench/next_vision_rocky/field
sudo env VIDEO_DEVICE=/dev/video22 \
  SOURCE_CAPS='video/x-raw,format=NV12,width=1920,height=1080' \
  SOURCE_MIN_BUFFERS=12 ENCODER_FORMAT=NV12 ./stream_rtp.sh 192.168.1.5
```

Use the bridge's actual input size in `SOURCE_CAPS`, not the desired transmitted
size. Check with `sudo v4l2-ctl -d /dev/v4l-subdev5 --query-dv-timings`; discover
the bridge's subdevice through `media-ctl` if numbering differs. For a 1280x720
input, use that size instead. `SOURCE_MIN_BUFFERS` requires the vendor's
GStreamer `v4l2src` extension; omit it if that property is unavailable.
On this revision, keep NV12 at the encoder input too: a subsequent 1280x720
test had valid direct PNG captures but gray H.265 frames with the I420 path;
`ENCODER_FORMAT=NV12` produced clear decoded camera images.

The image's `ubuntu` account initially lacks `video` and `dialout` membership;
`sudo` avoids changing device permissions or account groups for this test.
To return to the original demo, stop our sender/proxy with Ctrl+C, then run
`sudo systemctl start uranus-demo.service`. A reboot also returns to the demo:
its enabled state was unchanged and our processes have no autostart.

Video passed, but the initial UART test received zero bytes / no parsed camera
feedback despite 147 outgoing packets at the old 19200 8E1 settings. UART0 still
uses `uart0m0-xfer`. Camera-control cable/connector verification remains pending;
do not treat video success as proof of camera control. Boot configuration and
the newer DTB were only read and backed up, never changed.
Subsequent temporary tests at 9600, 19200, 38400, 57600, and 115200 baud,
each with even and no parity, also received zero bytes. The original 19200 8E1
settings and proxy were restored; video continued throughout. Only `/dev/ttyS0`
and the separate debug console `/dev/ttyFIQ0` are exposed. The debug console and
device-tree pin routing were not modified or used for camera commands.

On 2026-11-04, this revision passed internal UART loopback at both 19200 and
115200 baud with even parity: 160 transmitted bytes exactly matched 160 received
bytes at each speed. The test used Linux `TIOCM_LOOP`, then disabled loopback and
restored the original termios settings. The proxy was restarted at 19200 8E1.
A subsequent normal camera test sent 147 commands in six seconds but received
no camera data. **The kernel RX count of 320 is from internal loopback only,
not camera feedback.** Video kept running with the same sender process.

A read-only audit of the live device tree, vendor demo, Rockchip initialization,
systemd/init scripts, and udev configuration found no camera UART-switch script
or declared UART transceiver/RS-422/RS-485 control. UART0 is enabled on GPIO0
pins 20/21; UART1-9 are disabled as normal serial devices, with UART2 separately
reserved by the FIQ debug console. A generic Bluetooth configuration mentions
UART6, but UART6 is disabled and this is not evidence of a camera connection.
No connector pinout or board schematic was found in the inspected vendor files.
The next useful check is the external connector/cable/transceiver path, ideally
by swapping only the board with a known-working card while retaining the camera,
cable, and power supply. Internal loopback does not verify that external path.

Later on 2026-11-04, after the user confirmed the same camera/cable worked on
the old card and reconnected the new card, normal UART communication succeeded:
147 commands received 147 parsed camera-status replies in six seconds at the
unchanged 19200 8E1 settings. The combined home UI received live feedback.
No UART/pin-mux/firmware change was needed for that successful retest; the exact
physical cause of the earlier failure was not established. The earlier failure
and loopback counts above are historical, not the current operating state.

The original boot configuration, DTB, kernel config, and demo service file are
saved outside Git in
`../next_vision_rocky_backups/replacement-ubuntu267-2026-11-01/nextvision-original-config-20261101.tar.gz`.

## Verified Setup

NextVision DragonEye, Uranus Drone / RK3588, verified 2026-10-14:

| Component | Working configuration |
| --- | --- |
| Field image | Vendor Buildroot 2021.11, October 28, 2025 |
| Kernel | Original `5.10.160 #163`, October 28, 2025 |
| Boot device tree | Included `board/rk3588-uranus-drone-hdmi-reference.dtb` |
| Capture | `rk_hdmirx`, `/dev/video0`, 1920x1080 progressive / 25 FPS input |
| Transmitted video | H.265/RTP, 1280x720 / 12 FPS / 3 Mbps, UDP 5010 |
| Camera control | `/dev/ttyS0`, 19200 baud, 8 data bits, even parity, 1 stop bit |
| UART pin mux | `uart0m0-xfer`, GPIO0 pins 20/21; not connector pin numbers |
| Python / dependencies | uv 0.11.9, managed Python 3.12.13, pyserial 3.5 |
| Network used | Card `192.168.1.30/24`, home PC `192.168.1.5/24`, TCP 5000 |

What changed: the replacement originally selected an ADV7282-M-to-MIPI device
tree. We installed the original working card's vendor HDMI device tree as a
separate file and changed only the boot configuration's `fdt` selection. Video
then worked with the replacement's original kernel. No replacement camera
driver, encoder library, bootloader, or kernel was needed.

UART initially received zero bytes, even with the original card's older kernel
#156. That kernel test was reverted. After the user reconnected the card on
2026-10-14, the unchanged proxy received 149 parsed camera-status messages in
six seconds; the combined UI and camera controls worked. **We did not establish
why reconnection restored UART. There is no additional proven UART software fix.**

The included DTB was copied byte-for-byte from the original working Ubuntu
card's boot partition (`rk-kernel.dtb`, also named
`rk3588-uranus-drone-hailo_hdmi.dtb_v3`). Its checksum is in `board/SHA256SUMS`.
It is a vendor binary, not a rebuilt device tree; source/BSP is not included.
The working replacement's Ethernet MAC was `ce:01:85:c0:ac:87`.

## 1. Identify And Copy

Use the board's actual SSH account. The verified Buildroot image uses `root`;
the tested Ubuntu images use `ubuntu`. Do not assume the password or IP is
identical on every image. On the card, inspect:

```bash
uname -a
cat /etc/os-release
cat /proc/device-tree/model
v4l2-ctl --list-devices
ls -l /dev/ttyS0 /dev/disk/by-partlabel/boot
gst-inspect-1.0 mpph265enc
```

The remaining field examples use a root shell on the matching Buildroot image.
On Ubuntu, use `sudo` for privileged operations. Keep the vendor kernel and MPP
GStreamer plugin. `uv` cannot install hardware drivers or this plugin.

From the home PC, at the repository root:

```bash
tar --exclude=.venv --exclude=__pycache__ -czf /tmp/nextvision-field.tar.gz field
ssh root@192.168.1.30 'mkdir -p /root/Desktop/workbench/next_vision_rocky'
scp -O /tmp/nextvision-field.tar.gz root@192.168.1.30:/tmp/
ssh root@192.168.1.30 'tar -xzf /tmp/nextvision-field.tar.gz -C /root/Desktop/workbench/next_vision_rocky'
```

`scp -O` uses the legacy SCP protocol required by this Buildroot/Dropbear image.
Do not copy `.venv` from the x86 PC to the ARM64 board.

## 2. Back Up And Select The HDMI Device Tree

**Only for the matching Uranus hardware and boot layout below.** Have a recovery
method before changing boot files. A matching model name alone is insufficient:
another Ubuntu card with kernel #255 still had no HDMI signal with this DTB.
Do not flash a whole image or copy Ubuntu libraries over Buildroot.

On the card, from the copied `field` directory:

```bash
cd /root/Desktop/workbench/next_vision_rocky/field
(cd board && sha256sum -c SHA256SUMS)
mkdir -p /mnt/nextvision-boot
mount -o ro /dev/disk/by-partlabel/boot /mnt/nextvision-boot
cat /mnt/nextvision-boot/extlinux/extlinux.conf
ls -l /mnt/nextvision-boot/Image-5.10.160 /mnt/nextvision-boot/rk-kernel.dtb
```

The verified partition is 256 MiB ext4 (`mmcblk0p3`). Its original boot entry
selects `/Image-5.10.160` and `/rk-kernel.dtb`. If the layout or other boot
options differ, stop and adapt the configuration; do not overwrite them with
the supplied minimal entry. Skip the change if already using the reference DTB.

Save an unmounted partition backup on the card, then copy it to the PC before
proceeding. Run the backup pipeline in Bash with `pipefail` enabled:

```bash
umount /mnt/nextvision-boot
set -o pipefail
dd if=/dev/disk/by-partlabel/boot bs=4M | gzip -1 > /root/nextvision-boot-before.img.gz
gzip -t /root/nextvision-boot-before.img.gz
```

From the PC:

```bash
scp -O root@192.168.1.30:/root/nextvision-boot-before.img.gz ./nextvision-boot-before.img.gz
```

On the card, in `field`, apply the selection only after the backup succeeds:

```bash
set -e
mount /dev/disk/by-partlabel/boot /mnt/nextvision-boot
test ! -e /mnt/nextvision-boot/extlinux/extlinux.conf.before-nextvision
cp /mnt/nextvision-boot/extlinux/extlinux.conf /mnt/nextvision-boot/extlinux/extlinux.conf.before-nextvision
cp board/rk3588-uranus-drone-hdmi-reference.dtb /mnt/nextvision-boot/
cp board/extlinux-hdmi.conf /mnt/nextvision-boot/extlinux/extlinux.conf.nextvision
mv /mnt/nextvision-boot/extlinux/extlinux.conf.nextvision /mnt/nextvision-boot/extlinux/extlinux.conf
sync
umount /mnt/nextvision-boot
reboot
```

This preserves the original kernel, DTB, and symlink. After reboot:

```bash
uname -a
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --query-dv-timings
```

Expected: original kernel #163, `rk_hdmirx` at `/dev/video0`, valid 1920x1080
timings at approximately 25 FPS. No input lock is a failed acceptance check,
not a reason to install Python packages.

## 3. Install Python And Start

For an Internet-connected board, install the tested uv version and managed
Python, then synchronize the committed dependency lockfile:

```bash
curl -LsSf https://astral.sh/uv/0.11.9/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
cd /root/Desktop/workbench/next_vision_rocky/field
uv python install 3.12.13
uv sync --locked --python 3.12.13
.venv/bin/python -c 'import serial; print(serial.__version__)'
```

The original deployment transferred ARM64 uv, its managed Python distribution,
and a pyserial 3.5 wheel from the PC because Buildroot had no Python. The online
commands above are the equivalent fresh installation, not a tested reflash.
If `curl` or TLS certificates are absent, download the matching ARM64 artifacts
on the PC and transfer them; do not install x86 binaries or build Python here.
See the official [uv installation](https://docs.astral.sh/uv/getting-started/installation/)
and [managed Python](https://docs.astral.sh/uv/concepts/python-versions/) documentation.

Run in two field terminals, both from `field`:

```bash
.venv/bin/python -u proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000
```

```bash
./stream_rtp.sh 192.168.1.5
```

To leave both running after SSH disconnect instead, start each with `nohup`:

```bash
nohup .venv/bin/python -u proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000 >/tmp/proxy.log 2>&1 </dev/null &
nohup ./stream_rtp.sh 192.168.1.5 >/tmp/stream_rtp.log 2>&1 </dev/null &
```

Run only one proxy and sender. No tmux, systemd service, init script, or autostart
was added. **After reboot, start these again.** Logs are in `/tmp` and are not
persistent. The DTB boot selection itself persists.

## 4. Home UI And Acceptance

Give the PC an unused address on the same subnet (`192.168.1.5/24` in this setup).
Send video to that PC address, not back to the card. Allow TCP 5000 on the field
card and incoming UDP 5010 on the PC. This is RTP, not an RTSP URL.

On the PC, with GStreamer and its H.265 software decoder already installed:

```bash
cd home
uv sync --locked
uv run python basic_ui.py
```

Set host `192.168.1.30`, control port `5000`, video port `5010`. Verify:

- Real changing camera images, not solid blue/gray or decoder test bars.
- Live pan/tilt and HFOV values, not just a connected proxy indication.
- Sensor/zoom/control operation in the UI, with the camera free to move safely.
- On the card, `cat /proc/tty/driver/serial` shows RX increasing during operation.

The current sender defaults to 25 real FPS and the home receiver preserves that
rate with a 250 ms jitter buffer. Older tests used 12 FPS plus receiver-side
duplication; that duplication has been removed. Use `FPS=12` for slower hardware.
Restart only the UI when needed; leave field processes running. Do not run
another receiver on UDP 5010 alongside the UI.

For an independent UART check, close the UI and any other controller first.
With the proxy running, execute this on the card from `field`:

```bash
.venv/bin/python - <<'PY'
import collections
import json
import socket
import time

counts = collections.Counter()
with socket.create_connection(("127.0.0.1", 5000), timeout=3) as sock:
    sock.settimeout(0.5)
    sock.sendall(b'{"cmd":"start"}\n')
    end = time.monotonic() + 6
    buffer = b""
    try:
        while time.monotonic() < end:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                message = json.loads(line)
                counts[message.get("type", "response")] += 1
    finally:
        sock.sendall(b'{"cmd":"stop"}\n')
print(dict(counts))
assert counts["rx_status"] > 0, "No parsed camera feedback"
PY
```

On 2026-10-14 this produced 150 `tx`, 149 `rx_raw`, and 149 `rx_status` messages.
`tx` or an `ok` acknowledgment alone proves no camera response. With no RX,
check the camera's power/startup and control cable/connector before changing
baud rates or kernels. Previously, internal UART loopback passed even while the
external camera connection received nothing.

## Rollback And Saved Backups

For the instructions above, restore only the previous boot entry:

```bash
mount /dev/disk/by-partlabel/boot /mnt/nextvision-boot
cp /mnt/nextvision-boot/extlinux/extlinux.conf.before-nextvision /mnt/nextvision-boot/extlinux/extlinux.conf
sync
umount /mnt/nextvision-boot
reboot
```

If the card cannot boot, mount its boot partition using the board's supported
recovery method and restore that entry there. Keep the whole partition backup
for recovery; do not blindly write it to a different card's bootloader/rootfs.

The already-configured reference replacement uses older backup filenames:
`extlinux.conf.before-nextvision-hdmi-20261012` is its original MIPI entry;
`extlinux.conf.before-working-kernel-20261012` is kernel #163 plus the working
HDMI DTB. Do not restore the MIPI entry just to undo a kernel experiment.

Historical full backups are outside Git, under the home PC's sibling directory:

```text
../next_vision_rocky_backups/working-card-2026-10-12/
../next_vision_rocky_backups/replacement-buildroot-2026-10-12/
../next_vision_rocky_backups/replacement-ubuntu255-2026-10-12/
```

These are not full flashable OS images. The small DTB and boot-entry template
needed for the verified configuration are included in this repository.
