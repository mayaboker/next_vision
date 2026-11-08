# Working Uranus Setup

Tested on 2026-11-08: Ubuntu 22.04.5 ARM64, vendor kernel `5.10.160 #267`,
card MAC `a2:72:4e:01:f2:52`. This is the LT6911UXC revision, not the older
native-HDMI setup. **No kernel, device tree, boot files, or drivers were changed.**

- Card: `192.168.1.30`; home PC: `192.168.1.5`, both on the same Ethernet subnet.
- Video: `/dev/video22`, H.265/RTP to PC UDP `5010`.
- Control: `/dev/ttyS0`, 19200 baud, 8E1; proxy TCP `5000`.
- Existing vendor GStreamer/MPP plugin was reused; no video libraries installed.

## 1. Copy The Field Code

On the PC, from this repository's root:

```bash
tar --exclude=.venv --exclude=__pycache__ -czf /tmp/nextvision-field-20261108.tar.gz field
ssh ubuntu@192.168.1.30 'mkdir -p /home/ubuntu/Desktop/workbench/next_vision_rocky'
scp /tmp/nextvision-field-20261108.tar.gz ubuntu@192.168.1.30:/tmp/
ssh ubuntu@192.168.1.30 'tar -xzf /tmp/nextvision-field-20261108.tar.gz -C /home/ubuntu/Desktop/workbench/next_vision_rocky'
ssh ubuntu@192.168.1.30
```

Use the card's existing SSH password. Do not copy the PC's `.venv` to ARM64.

## 2. Install Python Dependencies

On the card, I installed uv 0.11.9 and used its existing Python 3.10.12:

```bash
curl -LsSf https://astral.sh/uv/0.11.9/install.sh -o /tmp/nextvision-uv-install.sh
sh /tmp/nextvision-uv-install.sh
cd /home/ubuntu/Desktop/workbench/next_vision_rocky/field
/home/ubuntu/.local/bin/uv sync --locked --python /usr/bin/python3
```

This created `field/.venv` and installed `pyserial==3.5`.

## 3. Start The Field Side

Check the camera's actual input size:

```bash
sudo v4l2-ctl -d /dev/v4l-subdev5 --query-dv-timings
```

It reported **1280x720 at 49.99 FPS** on this card. Stop the factory demo,
which otherwise owns the capture device, then start our proxy and sender:

```bash
cd /home/ubuntu/Desktop/workbench/next_vision_rocky/field
sudo systemctl stop uranus-demo.service
sudo nohup .venv/bin/python -u proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000 >/tmp/nextvision-proxy-20261108.log 2>&1 </dev/null &
sudo nohup env VIDEO_DEVICE=/dev/video22 \
  SOURCE_CAPS='video/x-raw,format=NV12,width=1280,height=720' \
  SOURCE_MIN_BUFFERS=12 ENCODER_FORMAT=NV12 \
  ./stream_rtp.sh 192.168.1.5 >/tmp/nextvision-stream-20261108.log 2>&1 </dev/null &
```

If the input is 1920x1080, use that size in `SOURCE_CAPS` instead. Do not set
the source size to the desired output size. NV12 capture **and** encoder input
avoid the gray-frame problem seen with automatic negotiation/I420 on this image.
The transmitted output is 1280x720, 25 FPS, 3 Mbps by default. This evenly divides
the 50 FPS camera input. Use `FPS=12` only if a different card cannot sustain 25.
`sudo` avoids changing the account's `video`/`dialout` permissions.

These commands are for a fresh boot: do not start duplicate proxies/senders.
They survive SSH disconnect, but do not autostart after reboot. The factory
service remains enabled and its files are unchanged; repeat this section after
reboot. To return to the factory demo, stop our two processes first, then run
`sudo systemctl start uranus-demo.service`.

## 4. Open The Home UI

On the PC, from this repository's root, I ran the existing home environment:

```bash
setsid -f home/.venv/bin/python -u home/basic_ui.py </dev/null >/tmp/nextvision-ui-20261108.log 2>&1
```

For a fresh PC, first create that environment with `cd home && uv sync --locked`.
Use host `192.168.1.30`, control port `5000`, video port `5010` in the UI.
Run only one UI/video receiver on UDP 5010.

## What Was Verified

- Real camera frames and readable overlay received through H.265/RTP on the PC.
- 147 commands produced 147 parsed camera replies in six seconds; these were
  real replies, not an internal loopback test. No UART software fix was needed.
- The UI connected and continued receiving live status at approximately 25 Hz.
- The camera currently reports mode `10` and shows `INIT` on its overlay.
  Gimbal movement/PID operation was **not verified** while it was in that state.

Only the field files, uv/Python environment, and running processes were added.
The factory service was stopped temporarily, not disabled or edited. Network,
firmware, kernel and device-tree settings were not changed on this card.

## Smoother Video Update

On 2026-11-08, increased real output from 12 to 25 FPS, capture buffers from
6 to 12, repeated H.265 headers at each IDR, and increased home jitter buffering
from 150 to 250 ms. Removed the receiver's artificial 24 FPS frame duplication.
The UART proxy and firmware were not changed.

Measured decoded output before: 11.25 FPS, longest gap 580 ms in 25 seconds.
After: 24.92 FPS, longest gap 83 ms, no gaps over 200 ms in 30 seconds.
This is a bounded test, not a guarantee against future input failures: the bridge
previously logged actual loss of camera signal, which buffering cannot repair.
