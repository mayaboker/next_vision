# Next Vision Minimal

Minimal Colibri field proxy, RTP video sender, and headless pan/tilt controller.

## Field card

Requires Python 3.10+, `uv`, `/dev/ttyS0`, and GStreamer with the Rockchip
`mpph265enc` plugin. DragonEye cameras use the board's HDMI receiver
(`/dev/video11`, `rk_hdmirx`); `/dev/video0` is the separate analog ADV7282 input.

On the supplied Ubuntu image, install the userspace prerequisites once:

```bash
sudo apt install v4l-utils gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
```

The HDMI receiver and `adv7180` decoder are kernel drivers supplied by the board
image; they are not Python packages and should not be installed with `uv`.

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

The stream defaults to 1280x720 at 12 FPS and 3 Mbps. Override it with environment
variables, for example `FPS=12 BITRATE=2500000 ./stream_rtp.sh <HOME_IP>`.

Check the receiver before starting the sender:

```bash
./check_video.sh
```

For a DragonEye source, this must report `hdmirx_status: connected`,
`power_present: 1`, and valid HDMI timings. Set `VIDEO_DEVICE=/dev/video0`
only when using a CVBS/ADV7282 source.

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
