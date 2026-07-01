# next_vision

Camera control utilities for a Colibri camera setup.

The project is split into two main parts:

- `serailcontroler/`: low-level serial protocol tools and a TCP JSON proxy.
- `control/`: higher-level camera control logic and OpenCV/GStreamer viewer.

The folder name `serailcontroler` is kept as it exists in the current project.

## Architecture

```text
camera hardware
  <serial: /dev/ttyS0 or /dev/ttyUSB0>
card running serailcontroler/proxy.py
  <TCP JSON: port 12345>
local station running sender.py or control/shob.py
```

## Install

On the card connected to the camera serial port:

```bash
python3 -m pip install -r requirements-card.txt
```

On the local station, for the OpenCV control UI:

```bash
python3 -m pip install -r requirements-local.txt
```

For the GStreamer video path used by `control/shob.py`, you may also need system packages such as `python3-gi`, GStreamer plugins, and an OpenCV build with GStreamer support.

## Run The Serial Proxy

Run this on the card connected to the camera:

```bash
python3 serailcontroler/proxy.py /dev/ttyS0 --host 0.0.0.0 --port 12345
```

If the camera appears as a USB serial device, use:

```bash
python3 serailcontroler/proxy.py /dev/ttyUSB0 --host 0.0.0.0 --port 12345
```

## Control From Local Station

For simple command control:

```bash
python3 serailcontroler/sender.py --host <CARD_IP> --port 12345
```

Useful interactive commands:

```text
ping
status
start
sensor ir
sensor visible
zoom in
zoom stop
center
nuc
stop
quit
```

For one-shot commands:

```bash
python3 serailcontroler/sender.py --host <CARD_IP> --cmd ping
python3 serailcontroler/sender.py --host <CARD_IP> --cmd sensor --value ir
python3 serailcontroler/sender.py --host <CARD_IP> --cmd zoom --value in
```

## Run The Visual Controller

Edit `control/src/camera_control/settings.py` and set:

```python
CAMERA_IP = "<CARD_IP>"
CAMERA_FEEDBACK_IP = "<CARD_IP>"
```

Then run:

```bash
python3 control/shob.py
```

`control/shob.py` expects an H265 RTP stream on UDP port `5000`.

## Git Push

Initialize and commit locally:

```bash
git init
git add .
git commit -m "Initial camera control project"
```

Then connect your remote repository and push:

```bash
git remote add origin <YOUR_GIT_REMOTE_URL>
git branch -M main
git push -u origin main
```

