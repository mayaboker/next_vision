# Video Setup

For the successfully recreated Buildroot setup, start with
[URANUS_SETUP.md](URANUS_SETUP.md). The sections below retain earlier diagnostic
results; failures on one card/image do not describe every Uranus card.

Identify the capture path from the board's actual driver and valid live frames,
not the device number or the physical connector's description. The working card
and the inspected replacement images expose different input paths.

## Dependencies

Use the board manufacturer's kernel and device tree for the actual camera/bridge
connection. The replacement inspected on 2026-10-08 runs Ubuntu 22.04.5, ARM64,
kernel 5.10.160, model `Uranus Drone`. Its media graph is:

```text
ADV7282-M (adv7180, I2C 7-0020)
  -> rockchip-csi2-dphy0 -> rockchip-mipi-csi2 -> /dev/video0
```

Install the README's GStreamer packages and synchronize Python dependencies with
`cd field && uv sync`. Hardware encoding additionally requires the board vendor's
Rockchip MPP package/plugin. Verify it with `gst-inspect-1.0 mpph265enc`.

For non-root access, run once and log out/in:

```bash
sudo usermod -aG video,dialout "$USER"
```

## Isolate Capture From Networking

Stop any video sender before capturing directly on the field board:

```bash
./check_video.sh
timeout --signal=INT 8 gst-launch-1.0 -q \
  v4l2src device=/dev/video0 num-buffers=5 ! \
  videoconvert ! pngenc ! multifilesink location=/tmp/camera-%02d.png
```

Inspect the PNGs. A registered capture device or nonempty file alone does not
verify live camera video. Only after a valid direct frame, run:

```bash
./stream_rtp.sh <HOME_IP>
```

## Replacement Diagnostics

On 2026-10-08, decoder color bars passed through MIPI, the repo's sender,
H.265/RTP, and the PC decoder at 1280x720/12 FPS. The test pattern was restored
to disabled. Live external captures remained uniformly black; the decoder had
no input lock while streaming. The UART's kernel counter also reported `rx:0`.
Proxy JSON acknowledgments verify command submission, not camera response.

A subsequent diagnostic tested all 13 documented ADV7282-M input selections
with the driver's clamp, filter, bias, and differential-input register sequence
while streaming. None acquired stable input lock; the saved registers were
restored. Direct serial tests at 19200 and 115200 baud, even and no parity,
also received zero bytes. The proxy was restarted after the test. The live
device tree selects UART0 group `uart0m0-xfer` (GPIO0 pins 20 and 21).

Internal UART loopback subsequently passed at both 19200 and 115200 baud with
even parity: each 128-byte challenge returned exactly. Normal mode received
zero bytes at either rate. This verifies the driver and UART's internal receive
path, but not the connector pin mapping, external transceiver, or actual wire
baud rate. Loopback was disabled and the proxy restarted. Its 256 received bytes
in `/proc/tty/driver/serial` came from this diagnostic, not camera feedback.

Disabling the decoder's CSI transmitter stopped capture after one in-flight
frame; restoring it resumed capture. Restarting CSI did not restore live video.
Read-only sampling of UART0's configured pins decoded consecutive outgoing
20-byte packets with valid parity, stop bits, and checksums at approximately
19200 baud. The receive pin stayed high without transitions. This verifies
transmission at the SoC, not passage through the connector or transceiver.
The user confirmed normal gimbal startup after a camera power cycle; a recheck
still found no decoder input lock or UART receive activity. The live device
tree exposes no UART transceiver-enable control, and the decoder's configured
reset and power-down GPIOs were deasserted.

Live video and camera control were not restored on those replacements. Compare the working
board's kernel, live device tree, camera driver initialization, and UART pin mux
with this board before installing another firmware image. An original image,
access to that board, or the supplier's BSP and connector pin map can establish
those differences reliably. No replacement driver has been verified.

## Working Reference

On 2026-10-12, the original card ran Ubuntu 22.04.5 with kernel 5.10.160 #156
(2025-07-16). Its `/dev/video0` binds `rk_hdmirx`, not the ADV7282 MIPI pipeline.
The receiver locked to 1920x1080 at 25 FPS. The existing
`/local/10_apps/stream_rtp.sh` delivered real camera frames at 1280x720/20 FPS
over H.265/RTP to the PC. The existing proxy also delivered parsed camera
feedback at 19200 baud, even parity; UART0 still uses `uart0m0-xfer`.
The combined home UI displayed live video and feedback. The card's original
scripts, kernel, device tree, and boot settings were left unchanged.

## Replacement Retests

On 2026-10-12, a Buildroot replacement running kernel #163 acquired live
1920x1080/25 FPS video after selecting the reference card's HDMI device tree.
The repo's sender delivered real frames at 1280x720/12 FPS. UART still received
zero bytes, including during a temporary test with the reference kernel #156.
Its boot selection was restored to kernel #163 with the HDMI device tree.
On 2026-10-14, after the user reconnected this card, video and UART both worked
with that configuration: 149 parsed camera-status replies in six seconds, real
RTP video, and working combined UI controls. No further UART software change was
made; the cause of its earlier missing replies was not established.

A subsequent Ubuntu replacement running kernel #255 (Ethernet MAC
`a2:72:4e:01:f2:52`) produced blue frames through its ADV/MIPI path and reported
no HDMI input signal. Testing the same reference HDMI device tree did not
restore video or UART feedback. Its original boot selection was restored.
Full boot-partition backups and rollback instructions for both cards are stored
outside the repository in the sibling `next_vision_rocky_backups` directory.
