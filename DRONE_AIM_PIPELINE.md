# Drone-detection → gimbal aim pipeline

This connects two repos so the Colibri gimbal automatically slews to a drone
found by a fixed 3-camera detection rig:

- **`drones_best_conf`** — runs the real-time detector/tracker over **3 static IR
  cameras** (each 32° HFOV, 720×576, stitched left→right). When it confirms a
  drone track it converts the target's pixel position into a **real-world
  (yaw, pitch)** and streams it over UDP.
- **`next_vision`** (this repo) — receives those angles and drives the gimbal to
  them with the existing closed-loop angle-hold PID.

The two halves are decoupled by a small UDP/JSON message, so either can run on a
different machine.

## Data flow

```text
 3× IR cameras (32° HFOV, 720×576)
        │  H.264/UDP  :5001 :5002 :5003
        ▼
 drones_best_conf: run_experiment.py  (stitch → detect → track → 8-hit confirm)
        │  strongest confirmed track's stitched pixel (x, y)
        ▼
 StitchedCameraGeometry.pixel_to_yaw_pitch()   ← 32° per-camera pinhole + boresight
        │  UDP JSON  :5007   {"yaw","pitch","found", ...}
        ▼
 next_vision: pid_calibrator.py --aim
        │  yaw → roll axis,  pitch → pitch axis
        ▼
 GimbalPIDController.set_roll_deg / set_pitch_deg
        │  (axis, speed) rate command
        ▼
 ColibriSender → proxy.py (on the card, serial 19200 8E1) → Colibri gimbal moves & holds
```

Axis naming note: on the Colibri, the **roll axis is azimuth/yaw** and the
**pitch axis is elevation**. The drone side speaks yaw/pitch; the receiver maps
`yaw → roll`.

## The geometry (pixel → yaw/pitch)

Done on the drone side (it owns the rig layout), in
`drone_alert_prototype/gimbal_target_publisher.py`.

- Panels are `720×576`; the stitcher places them at `left_x=0`,
  `middle_x = 720 − overlap`, `right_x = 1440 − 2·overlap`, with middle drawn over
  left and right over middle. A stitched `x` is attributed to whichever camera is
  visible there.
- Per camera, a pinhole with `fx = 720 / (2·tan(16°))` (and `fy = fx`, square
  pixels) gives the off-axis angle from that camera's center.
- Camera boresights default to **contiguous & boresighted**: middle = 0°, adjacent
  centers ≈30° apart (32° FOV minus the ~2° from a 45 px overlap), so total
  coverage ≈ ±46°. The middle camera's center = gimbal (yaw 0, pitch 0); cameras
  assumed level.

```
yaw   = yaw_sign   · ( A[cam] + atan((local_x − 360) / fx) )
pitch = pitch_sign · ( E[cam] − atan((local_y − 288) / fy) )   # image-y grows downward
```

All of `overlap`, per-camera azimuth/elevation offsets, and the two signs are
constructor parameters; the HFOV is taken from the pipeline's
`physics_horizontal_fov_deg` (32.0) so there is one source of truth.

## Wire protocol

**UDP, one JSON datagram per processed frame, default port 5007.** Matches
next_vision's existing UDP convention (ArUco follow = 5005, wide-cam point = 5006).

```json
{"found": true, "yaw": 12.3, "pitch": -4.1, "x": 1420.0, "y": 250.0, "frame": 837, "track_id": 2}
{"found": false, "frame": 838}
```

next_vision consumes `found`, `yaw`, `pitch`; the rest is for debugging. UDP is
non-blocking and loss-tolerant, which is correct for a continuous setpoint stream.

## Behavior

- **Target:** the strongest **confirmed** track (highest `avg_score`); its latest
  position is sent every processed frame (~8 Hz). When nothing is confirmed, a
  `found:false` packet is sent.
- **Lost-target watchdog:** if no `found` packet arrives for `AIM_LOST_GRACE_S`
  (0.5 s), the receiver stops both axes (gimbal holds position).
- **Glitch clamp:** the setpoint may not jump more than `AIM_MAX_STEP_DEG` (20°)
  between updates, except on first acquire.
- **Mutual exclusion:** `--track`, `--point`, and `--aim` all drive absolute
  setpoints, so only one may be enabled at a time.

## How to run

### On the card (serial-attached to the camera)

```bash
python serailcontroler/proxy.py /dev/ttyS0 --host 0.0.0.0 --port 5000
```

### On the PC — gimbal receiver

```bash
# --host/--port point at the proxy; --aim binds UDP 5007 for angle packets
python control2/pid_calibrator.py --host <CARD_IP> --port 5000 --aim
# open the printed URL (http://127.0.0.1:8080) to watch pitch/roll track the target
```

### On the PC (or detection box) — drone pipeline with streaming enabled

Live, three real UDP cameras:

```bash
uv run python run_experiment.py \
  --config-path configs/online.yaml \
  --camera-ip 'udp://@:5001' --camera-ip 'udp://@:5002' --camera-ip 'udp://@:5003' \
  --gimbal-stream --gimbal-host <PC_IP> --gimbal-port 5007
```

`--gimbal-host` is where `pid_calibrator.py --aim` is listening (use `127.0.0.1`
if both run on the same PC).

### Localhost smoke test (no cameras, no hardware)

```bash
# terminal 1 — feed three looping videos as UDP streams
./stream_three_udp.sh feed1.mp4 feed2.mp4 feed3.mp4
# or, to test with fewer real cameras, use 'black' for any of the three
# (constant black screen sent to that port so the receiver still gets 3 streams):
./stream_three_udp_test.sh 'vids/cam32_500_attack_sky(9).mp4' black black

# terminal 2 — pipeline, streaming angles to localhost:5007
uv run python run_experiment.py \
  --config-path configs/online.yaml \
  --camera-ip 'udp://@:5001' --camera-ip 'udp://@:5002' --camera-ip 'udp://@:5003' \
  --gimbal-stream --gimbal-port 5007

# terminal 3 — receiver (against a running proxy, or watch the /data JSON without one)
python control2/pid_calibrator.py --host <CARD_IP> --port 5000 --aim
```

## Bring-up tuning

If an axis behaves wrong, fix it at the level that matches the cause:

- **Mount orientation (physical gimbal).** `MOUNT_INVERT_ROLL` / `MOUNT_INVERT_PITCH`
  in `control2/settings.py`. On this hardware roll is mirrored by the mount
  (`MOUNT_INVERT_ROLL = True`) but pitch is upright (`MOUNT_INVERT_PITCH = False`).
  For an inverted axis, *both* the measured angle (feedback in) and the rate
  command (out) are inverted once at the `ColibriSender` boundary — the closed
  loop stays stable, angles stay right-side-up (a right/up target slews the camera
  right/up), and it fixes **all** modes (aim / point / track / manual), not just
  aim. Flip a value if that axis slews the wrong way on hardware.
- **Detection-frame orientation.** If the wide cameras report a mirrored/flipped
  angle, fix on the drone side with `StitchedCameraGeometry(yaw_sign=…, pitch_sign=…)`,
  where the "real-world angle" is defined.
- **Per-mode fine direction.** `AIM_YAW_SIGN` / `AIM_PITCH_SIGN` (and the analogous
  `*_TRACK_SIGN` / `*_POINT_SIGN`) remain as last-resort per-mode tweaks; with the
  mount handled above they should stay `+1`.

Other knobs: `AIM_PORT`, `AIM_MAX_STEP_DEG`, `AIM_LOST_GRACE_S` in
`control2/settings.py`; per-camera `azimuth_offsets_deg` / `elevation_offsets_deg`
in `StitchedCameraGeometry` if the rig is not perfectly contiguous/level; the
gimbal actuator direction lives in the existing `PITCH_SIGN` / `ROLL_SIGN`.

## Files

**drones_best_conf**
- `drone_alert_prototype/gimbal_target_publisher.py` — geometry + UDP publisher (new)
- `drone_alert_prototype/experiment_runner.py` — builds the publisher, sends per frame
- `run_experiment.py` — `--gimbal-stream / --gimbal-host / --gimbal-port` CLI flags
- `tests/test_gimbal_target_publisher.py` — geometry + wire-format tests (new)

**next_vision**
- `control2/pid_calibrator.py` — `--aim / --aim-port` receiver mode
- `control2/settings.py` — `AIM_*` tunables

## Verification status

- **Drone geometry/publisher:** 10 unit tests pass — per-camera mapping, seam
  continuity across camera boundaries, zero-overlap spacing = FOV, sign flips,
  and the UDP wire format (`tests/test_gimbal_target_publisher.py`).
- **Full pipeline, end to end (headless):** replaying the 828-frame `sky(9)` clip
  with `--gimbal-stream` produced **828 datagrams (one per frame)**; **380** were
  `found:true` from real confirmed detections, carrying geometrically-correct
  angles (e.g. pixel `x=649 → yaw −17.12°`, near-top `y=38 → pitch +11.26°`), all
  within the camera FOV. (Single-clip test → left-camera region → negative yaw.)
- **Gimbal receiver:** UDP loopback drives the PID setpoints; the lost-target
  watchdog stops both axes; the 20°/update glitch clamp holds; `--track/--point/--aim`
  are mutually exclusive.

