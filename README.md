# Next Vision Minimal

Minimal Colibri field proxy, RTP video sender, and headless pan/tilt controller.

For the exact commands used on the latest Ubuntu/LT6911UXC card, see
[SETUP.md](SETUP.md). Older hardware notes remain in `field/URANUS_SETUP.md`.

## Field card

Requires Python 3.10+, `uv`, `/dev/ttyS0`, and GStreamer with the Rockchip
`mpph265enc` plugin. The capture device defaults to `/dev/video0`.
Use `VIDEO_DEVICE` to override it. Device numbering does not identify the input:
the verified working card exposes `rk_hdmirx`, while inspected replacements
expose an ADV7282-M-to-MIPI path.

For a new Uranus card, follow [field/URANUS_SETUP.md](field/URANUS_SETUP.md).
It includes the verified HDMI device tree, backup/rollback, installation, and
video/UART acceptance checks. Video and camera control were both verified on
the Buildroot replacement on 2026-10-14.

On the supplied Ubuntu image, install the userspace prerequisites once:

```bash
sudo apt install v4l-utils gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
```

The video receiver and camera/bridge driver are supplied by the board kernel and
device tree. They must match the camera connection; `uv` installs only Python
dependencies. Some replacement images bind an ADV7282-M decoder through the
`adv7180` driver; that is not the capture path of the verified working setup.

```bash
cd field
uv sync
uv run python proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000
```

In another terminal, send H.265/RTP video to the home PC:

```bash
cd field
./stream_rtp.sh <HOME_IP>       # optional second argument: UDP port, default 5010
```

The stream defaults to 1280x720 at 25 FPS and 3 Mbps. Override it with environment
variables, for example `FPS=12 BITRATE=2500000 ./stream_rtp.sh <HOME_IP>`.
Newer LT6911UXC cards need explicit native-size NV12 `SOURCE_CAPS`; see the
Uranus setup guide. Optional `SOURCE_MIN_BUFFERS` sets the vendor capture pool.
The home receiver displays native frames with a 250 ms jitter buffer; it does
not duplicate frames to inflate the displayed FPS.

Check the receiver before starting the sender:

```bash
./check_video.sh
```

Check the actual capture driver and its input status. A MIPI media graph or a
working test pattern does not establish valid live camera frames. Verify a direct
capture before troubleshooting RTP; use HDMI timing checks only for `rk_hdmirx`.

See [field/VIDEO_SETUP.md](field/VIDEO_SETUP.md) for permissions, direct-capture
checks, and the current verification results.

## Home PC

```bash
cd home
uv sync
uv run python basic_ui.py
```

The combined UI shows RTP video, the live Thrustmaster controller, pan/tilt
targets and gains, RGB/IR sensor selection, palette, NUC, and closed-loop zoom
to the nearest camera-supported horizontal field of view. Controller inputs are
A1 yaw, inverted A2 pitch, button 4 zoom in, 9 zoom out, 7 NUC, 6 thermal
polarity, and 1 RGB/IR. Buttons 5 and 8 are displayed for focus, which the
current Colibri protocol does not expose.

For headless control and a separate video window:

```bash
cd home
uv run python angle_hold.py --host <FIELD_IP> --port 5000 \
  --tilt-target 0 --pan-target 0
./show_rtp.sh                 # optional argument: UDP port, default 5010
```

The tilt target accepts `-90..90` degrees and the pan target accepts `-180..180`
degrees. Each axis has independent `Kp`, `Ki`, and `Kd` values in the UI. The
controller receives pan/tilt feedback from the proxy and sends PID rate commands
until `Ctrl+C`; shutdown sends neutral rates and stops field transmission.

Control uses newline-delimited JSON over TCP `5000`. Video is one-way H.265/RTP
over UDP `5010`; it is not RTSP despite the old script names.
