# Next Vision Minimal

Minimal Colibri field proxy, RTP video sender, and headless pan/tilt controller.

## Field card

Requires Python 3.10+, `uv`, `/dev/ttyS0`, `/dev/video0`, and GStreamer with the
Rockchip `mpph265enc` plugin.

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

The stream defaults to 1280x720 at 24 FPS and 3 Mbps. Override it with environment
variables, for example `FPS=12 BITRATE=2500000 ./stream_rtp.sh <HOME_IP>`.

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
