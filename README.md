# Next Vision Minimal

Minimal Colibri field proxy, RTP video sender, and headless angle-hold controller.

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

## Home PC

```bash
cd home
uv sync
uv run python basic_ui.py
```

For headless control and a separate video window:

```bash
cd home
uv run python angle_hold.py --host <FIELD_IP> --port 5000 --pitch 0 --pan 0
./show_rtp.sh                 # optional argument: UDP port, default 5010
```

`--pitch` accepts `-90..90` degrees and `--pan` accepts `-180..180` degrees.
The controller receives angle feedback from the proxy and sends PID rate commands
until `Ctrl+C`; shutdown sends neutral rates and stops field transmission.

Control uses newline-delimited JSON over TCP `5000`. Video is one-way H.265/RTP
over UDP `5010`; it is not RTSP despite the old script names.
