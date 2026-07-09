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
local station running sender.py
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

For the GStreamer video path, you may also need system packages such as `python3-gi`, GStreamer plugins, and an OpenCV build with GStreamer support.

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


##  POC
chip side [192.168.1.30/24]:
```bash
ssh ubuntu@192.168.1.30 # passward: ubuntu
sudo su
cd /local/10_apps
## run stream sender:
# port 5001 for RPT video straming using gstreamer
./rtsp_cam_sender.sh 

## run proxy
# port 5000 for control
python nextCAM/proxy.py /dev/ttyS0 --host 192.168.1.30 --port 5000
```

pc side [192.168.1.201/24]:
```bash
./control/aruco_id0_viewer.py --track
python control2/pid_calibrator.py --host 192.168.1.30 --port 5000 --track
```



port 5005 for pixel-to-move stream (--track currently on the pid_controller run and aruco_id0_viewer.py)
Note that currently the video is rotated-180, so we also rotate the qr center pixel to match.

adding ip:
ip link show
`sudo ip route add default via 192.168.1.1 dev eth0` (replace eth0 with the right if)



## Drone-aim pipeline (3 static cameras -> gimbal)

Auto-slew the Colibri gimbal to a drone detected by the sibling
`../drones_best_conf` 3-camera rig. It converts a confirmed detection's pixel to
a real-world (yaw, pitch) and streams it over UDP :5007; `pid_calibrator --aim`
drives the gimbal there. Full details: `DRONE_AIM_PIPELINE.md`.

Run in three terminals (add `../drones_best_conf` as needed):

```bash
# 1) card [192.168.1.30] - serial proxy for gimbal control (port 5000)
python3 serailcontroler/proxy.py /dev/ttyS0 --host 192.168.1.30 --port 5000

# 2) PC - gimbal receiver: listens for yaw/pitch on udp:5007, drives the gimbal
#    (open http://127.0.0.1:8080 to watch it track; upside-down mount handled by
#     MOUNT_INVERT_* in control2/settings.py)
python control2/pid_calibrator.py --host 192.168.1.30 --port 5000 --aim

# 3) detection box (in ../drones_best_conf) - detect + stream target angles
uv run python run_experiment.py --config-path configs/online.yaml \
  --camera-ip 'udp://@:5001' --camera-ip 'udp://@:5002' --camera-ip 'udp://@:5003' \
  --gimbal-stream --gimbal-host <PC_IP> --gimbal-port 5007
```

Localhost test with no cameras (needs `ffmpeg`): feed video files and/or a
constant black screen to the three ports, then run terminals 2 and 3 with
`--gimbal-host 127.0.0.1`:

```bash
# in ../drones_best_conf  (use 'black' for any camera you don't have a clip for)
./stream_three_udp_test.sh black 'vids/cam32_500_attack_sky(9).mp4' black
```
