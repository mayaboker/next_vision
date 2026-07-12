#!/usr/bin/env python3
"""
PID gain calibrator (web GUI, live proxy).

Connects to the running Colibri proxy via ColibriSender, drives the gimbal
through control2's GimbalPIDController, and serves a browser page that plots
pitch/roll feedback vs setpoint in real time with editable Kp/Ki/Kd and
setpoint fields per axis. Tune gains and watch the response.

Zero third-party dependencies: stdlib HTTP server + a vanilla-JS canvas page.

Usage:
    python control2/pid_calibrator.py [--host <ip>] [--port <port>]
                                      [--http-host <ip>] [--http-port <port>]
                                      [--track | --track-port <udp_port>]
                                      [--point | --point-port <udp_port>]
                                      [--aim   | --aim-port   <udp_port>]

(--track, --point, and --aim all drive the gimbal's absolute setpoints, so at
most one may be enabled at a time.)

Then open the printed URL (default http://127.0.0.1:8080) in a browser.
On launch the calibrator auto-starts 25 Hz camera transmission (so rx_status
feedback flows and rate commands reach the camera) and stops it on exit.

ArUco follow (--track / --track-port): binds a UDP socket and expects pixel-error
packets {"ex","ey","found","w","h"} from aruco_id0_viewer.py --track. Each packet
is converted (via live FOV + current gimbal angle) into a target angle that drives
the tuned angle-hold PID so the camera keeps the marker centered.

Wide-cam pointing (--point / --point-port): binds a UDP socket and expects
detection packets {"x","y","w","h","hfov","found"} from a fixed wide camera
(e.g. drones_best_conf/stream_detections.py). Each detection's off-axis angle in
the wide frame is used as the ABSOLUTE gimbal angle to point at it (gimbal starts
centered). Use this to slew the zoom gimbal toward a detected target.

Absolute-angle aim (--aim / --aim-port): binds a UDP socket and expects packets
{"yaw","pitch","found"} of already-computed real-world angles (degrees) from an
upstream sensor that owns the geometry — e.g. drones_best_conf run with
--gimbal-stream, whose 3-camera 32° rig converts a confirmed drone's stitched
pixel into (yaw, pitch). yaw drives the roll axis (azimuth); pitch drives the
pitch axis. On loss of "found" the gimbal is stopped after AIM_LOST_GRACE_S.
"""

import json
import math
import os
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Make both this dir and the sibling serailcontroler dir importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO, "serailcontroler")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sender import ColibriSender  # noqa: E402  (from serailcontroler)

try:  # package import
    from . import settings as cfg
    from .event_bus import Event
    from .gimbal_pid_controller import GimbalPIDController
    from .pid import _clamp
except ImportError:  # script import
    import settings as cfg
    from event_bus import Event
    from gimbal_pid_controller import GimbalPIDController
    from pid import _clamp

_PAGE_PATH = os.path.join(_HERE, "calibrator_page.html")
_WINDOW_SECONDS = 30.0          # rolling plot window
_BUFFER_MAXLEN = 4000           # samples retained per stream
_FRESH_FEEDBACK_S = 2.0         # feedback considered live if newer than this


class PidCalibrator:
    def __init__(self, host, port, track_port=None, point_port=None, aim_port=None):
        self.sender = ColibriSender(host, port)
        # Quiet the sender's terminal chatter; the GUI is the display now.
        self.sender.show_tx = False
        self.sender.show_rx_raw = False
        self.sender.show_rx_status = False
        # Correct the upside-down mount once, at the gimbal boundary.
        self.sender.invert_pitch = cfg.MOUNT_INVERT_PITCH
        self.sender.invert_roll = cfg.MOUNT_INVERT_ROLL

        self.feedback_event = Event()
        self.command_event = Event()

        self.sender.feedback_event = self.feedback_event
        self.command_event.subscribe(self._send_rate)

        self.controller = GimbalPIDController(self.feedback_event, self.command_event)
        self.feedback_event.subscribe(self._on_feedback)

        # Rolling history: (t, pitch_meas, pitch_sp|None, roll_meas, roll_sp|None)
        self._history = deque(maxlen=_BUFFER_MAXLEN)
        self._lock = threading.Lock()
        self._last_feedback_t = None

        # ArUco visual-follow (outer loop) state.
        self._track_port = track_port
        self._track_running = False
        self._track_thread = None
        self._track_sock = None
        self._track_lock = threading.Lock()
        self._track = None            # latest {ex,ey,found,w,h,t}
        self._last_found_t = 0.0
        self._engaged = False         # currently driving from a found marker

        # Wide-camera "point-at-detection" (absolute pointing) state.
        self._point_port = point_port
        self._point_running = False
        self._point_thread = None
        self._point_sock = None
        self._point_lock = threading.Lock()
        self._point = None            # latest {x,y,w,h,hfov,found,t}
        self._point_last_found_t = 0.0
        self._point_engaged = False
        self._point_last_pitch = 0.0
        self._point_last_roll = 0.0

        # Absolute-angle "aim" state (upstream sensor sends yaw/pitch degrees).
        self._aim_port = aim_port
        self._aim_running = False
        self._aim_thread = None
        self._aim_sock = None
        self._aim_lock = threading.Lock()
        self._aim = None              # latest {yaw,pitch,found,t}
        self._aim_last_found_t = 0.0
        self._aim_engaged = False
        self._aim_last_pitch = 0.0
        self._aim_last_roll = 0.0
        self._aim_peer_ip = None       # source of aim packets, for feedback echo

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #
    def _send_rate(self, axis, speed):
        if axis == "pitch":
            self.sender.pitch(speed)
        elif axis == "roll":
            self.sender.roll(speed)

    def _on_feedback(self, pitch_deg, roll_deg):
        st = self.controller.get_state()
        pitch_sp = st["pitch"]["setpoint"] if st["pitch"]["active"] else None
        roll_sp = st["roll"]["setpoint"] if st["roll"]["active"] else None
        now = time.time()
        with self._lock:
            self._history.append((now, pitch_deg, pitch_sp, roll_deg, roll_sp))
            self._last_feedback_t = now

    # ------------------------------------------------------------------ #
    # Snapshot for /data
    # ------------------------------------------------------------------ #
    def snapshot(self):
        st = self.controller.get_state()
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        with self._lock:
            rows = [r for r in self._history if r[0] >= cutoff]
            last_fb = self._last_feedback_t
        pitch_series = [[r[0], r[1], r[2]] for r in rows]
        roll_series = [[r[0], r[3], r[4]] for r in rows]

        receiving = last_fb is not None and (now - last_fb) < _FRESH_FEEDBACK_S
        connected = bool(getattr(self.sender, "running", False))
        st["pitch"]["series"] = pitch_series
        st["roll"]["series"] = roll_series

        with self._track_lock:
            tr = dict(self._track) if self._track else None
        tracking = {
            "enabled": self._track_port is not None,
            "engaged": self._engaged,
            "found": bool(tr["found"]) if tr else False,
            "ex": tr["ex"] if tr else None,
            "ey": tr["ey"] if tr else None,
            "age": (now - tr["t"]) if tr else None,
        }
        with self._point_lock:
            po = dict(self._point) if self._point else None
        pointing = {
            "enabled": self._point_port is not None,
            "engaged": self._point_engaged,
            "found": bool(po["found"]) if po else False,
            "x": po["x"] if po else None,
            "y": po["y"] if po else None,
            "age": (now - po["t"]) if po else None,
        }
        with self._aim_lock:
            am = dict(self._aim) if self._aim else None
        aiming = {
            "enabled": self._aim_port is not None,
            "engaged": self._aim_engaged,
            "found": bool(am["found"]) if am else False,
            "yaw": am["yaw"] if am else None,
            "pitch": am["pitch"] if am else None,
            "age": (now - am["t"]) if am else None,
        }
        return {
            "now": now,
            "window": _WINDOW_SECONDS,
            "connected": connected,
            "receiving": receiving,
            "last_feedback_age": (now - last_fb) if last_fb else None,
            "pitch": st["pitch"],
            "roll": st["roll"],
            "tracking": tracking,
            "pointing": pointing,
            "aiming": aiming,
        }

    # ------------------------------------------------------------------ #
    # Commands from the UI
    # ------------------------------------------------------------------ #
    def apply_gains(self, axis, kp, ki, kd):
        if axis == "pitch":
            self.controller.set_pitch_gains(kp, ki, kd)
        elif axis == "roll":
            self.controller.set_roll_gains(kp, ki, kd)
        else:
            raise ValueError(f"unknown axis {axis!r}")

    def apply_setpoint(self, axis, deg):
        if axis == "pitch":
            self.controller.set_pitch_deg(deg)
        elif axis == "roll":
            self.controller.set_roll_deg(deg)
        else:
            raise ValueError(f"unknown axis {axis!r}")

    def stop_axis(self, axis):
        if axis == "pitch":
            self.controller.stop_pitch()
        elif axis == "roll":
            self.controller.stop_roll()
        else:
            raise ValueError(f"unknown axis {axis!r}")

    # ------------------------------------------------------------------ #
    # ArUco visual-follow (outer loop)
    # ------------------------------------------------------------------ #
    def _compute_targets(self, ex, ey, w, h):
        """Pixel error -> (pitch_target, roll_target) absolute angles, or None
        per axis when inside the dead-band. ex=cx-w/2 (horizontal->roll),
        ey=cy-h/2 (vertical->pitch)."""
        st = self.controller.get_state()
        cur_pitch = st["pitch"]["measured"]
        cur_roll = st["roll"]["measured"]

        status = self.sender.last_status or {}
        hfov = status.get("hfov_deg") or cfg.TRACK_FALLBACK_HFOV
        vfov = status.get("vfov_deg") or cfg.TRACK_FALLBACK_VFOV

        ex_n = ex / (w / 2.0) if w else 0.0
        ey_n = ey / (h / 2.0) if h else 0.0

        roll_target = None
        pitch_target = None
        if abs(ex_n) >= cfg.TRACK_DEADBAND:
            roll_off = _clamp(cfg.ROLL_TRACK_SIGN * ex_n * (hfov / 2.0),
                              -cfg.TRACK_MAX_STEP_DEG, cfg.TRACK_MAX_STEP_DEG)
            roll_target = cur_roll + roll_off
        if abs(ey_n) >= cfg.TRACK_DEADBAND:
            pitch_off = _clamp(cfg.PITCH_TRACK_SIGN * ey_n * (vfov / 2.0),
                               -cfg.TRACK_MAX_STEP_DEG, cfg.TRACK_MAX_STEP_DEG)
            pitch_target = cur_pitch + pitch_off
        return pitch_target, roll_target

    def _apply_track(self, ex, ey, w, h):
        self._last_found_t = time.time()
        pitch_t, roll_t = self._compute_targets(ex, ey, w, h)
        first = not self._engaged   # fresh integral on (re)acquire
        if pitch_t is not None:
            self.controller.set_pitch_deg(pitch_t, reset=first)
        if roll_t is not None:
            self.controller.set_roll_deg(roll_t, reset=first)
        self._engaged = True

    def _track_loop(self):
        sock = self._track_sock
        while self._track_running:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                data = None
            except OSError:
                break

            if data:
                try:
                    msg = json.loads(data)
                    ex = float(msg["ex"]); ey = float(msg["ey"])
                    found = bool(msg["found"])
                    w = float(msg["w"]); h = float(msg["h"])
                except (ValueError, KeyError, TypeError):
                    continue
                now = time.time()
                with self._track_lock:
                    self._track = {"ex": ex, "ey": ey, "found": found,
                                   "w": w, "h": h, "t": now}
                if found:
                    self._apply_track(ex, ey, w, h)

            # Lost-target watchdog: stop the gimbal if no marker for a while.
            if self._engaged and (time.time() - self._last_found_t) > cfg.TRACK_LOST_GRACE_S:
                self.controller.stop_pitch()
                self.controller.stop_roll()
                self._engaged = False

    def _start_tracking(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self._track_port))
        sock.settimeout(0.1)
        self._track_sock = sock
        self._track_running = True
        self._track_thread = threading.Thread(target=self._track_loop, daemon=True)
        self._track_thread.start()

    def _stop_tracking(self):
        self._track_running = False
        if self._track_sock is not None:
            try:
                self._track_sock.close()
            except OSError:
                pass
        if self._track_thread is not None:
            self._track_thread.join(timeout=1.0)

    # ------------------------------------------------------------------ #
    # Wide-camera "point-at-detection" (absolute pointing)
    # ------------------------------------------------------------------ #
    def _compute_point_target(self, x, y, w, h, hfov):
        """Wide-frame detection pixel -> ABSOLUTE gimbal (pitch, roll) angle.
        The wide camera is fixed and boresighted with the gimbal at center, so
        the detection's off-axis angle IS the angle to point at it."""
        if not hfov or w <= 0:
            return None, None
        fx = (w / 2.0) / math.tan(math.radians(hfov) / 2.0)  # pixels; square pixels
        if fx <= 0:
            return None, None
        roll = cfg.ROLL_POINT_SIGN * math.degrees(math.atan((x - w / 2.0) / fx))
        pitch = cfg.PITCH_POINT_SIGN * math.degrees(math.atan((y - h / 2.0) / fx))
        return pitch, roll

    def _apply_point(self, x, y, w, h, hfov):
        self._point_last_found_t = time.time()
        pitch_t, roll_t = self._compute_point_target(x, y, w, h, hfov)
        if pitch_t is None:
            return
        first = not self._point_engaged
        if not first:  # limit per-update jump (glitch rejection)
            pitch_t = _clamp(pitch_t, self._point_last_pitch - cfg.POINT_MAX_STEP_DEG,
                             self._point_last_pitch + cfg.POINT_MAX_STEP_DEG)
            roll_t = _clamp(roll_t, self._point_last_roll - cfg.POINT_MAX_STEP_DEG,
                            self._point_last_roll + cfg.POINT_MAX_STEP_DEG)
        self.controller.set_pitch_deg(pitch_t, reset=first)
        self.controller.set_roll_deg(roll_t, reset=first)
        self._point_last_pitch, self._point_last_roll = pitch_t, roll_t
        self._point_engaged = True

    def _point_loop(self):
        sock = self._point_sock
        while self._point_running:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                data = None
            except OSError:
                break

            if data:
                try:
                    msg = json.loads(data)
                    x = float(msg["x"]); y = float(msg["y"])
                    w = float(msg["w"]); h = float(msg["h"])
                    hfov = float(msg.get("hfov", cfg.TRACK_FALLBACK_HFOV))
                    found = bool(msg["found"])
                except (ValueError, KeyError, TypeError):
                    continue
                now = time.time()
                with self._point_lock:
                    self._point = {"x": x, "y": y, "w": w, "h": h,
                                   "hfov": hfov, "found": found, "t": now}
                if found:
                    self._apply_point(x, y, w, h, hfov)

            if self._point_engaged and (time.time() - self._point_last_found_t) > cfg.POINT_LOST_GRACE_S:
                self.controller.stop_pitch()
                self.controller.stop_roll()
                self._point_engaged = False

    def _start_pointing(self):
        # Start boresighted at center, then listen for detections.
        self.controller.set_pitch_deg(0.0, reset=True)
        self.controller.set_roll_deg(0.0, reset=True)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self._point_port))
        sock.settimeout(0.1)
        self._point_sock = sock
        self._point_running = True
        self._point_thread = threading.Thread(target=self._point_loop, daemon=True)
        self._point_thread.start()

    def _stop_pointing(self):
        self._point_running = False
        if self._point_sock is not None:
            try:
                self._point_sock.close()
            except OSError:
                pass
        if self._point_thread is not None:
            self._point_thread.join(timeout=1.0)

    # ------------------------------------------------------------------ #
    # Absolute-angle "aim" (upstream sensor already did the geometry)
    # ------------------------------------------------------------------ #
    def _apply_aim(self, yaw, pitch):
        self._aim_last_found_t = time.time()
        pitch_t = cfg.AIM_PITCH_SIGN * pitch
        roll_t = cfg.AIM_YAW_SIGN * yaw   # yaw (azimuth) drives the roll axis
        first = not self._aim_engaged     # fresh integral on (re)acquire
        if not first:  # limit per-update jump (glitch rejection)
            pitch_t = _clamp(pitch_t, self._aim_last_pitch - cfg.AIM_MAX_STEP_DEG,
                             self._aim_last_pitch + cfg.AIM_MAX_STEP_DEG)
            roll_t = _clamp(roll_t, self._aim_last_roll - cfg.AIM_MAX_STEP_DEG,
                            self._aim_last_roll + cfg.AIM_MAX_STEP_DEG)
        self.controller.set_pitch_deg(pitch_t, reset=first)
        self.controller.set_roll_deg(roll_t, reset=first)
        self._aim_last_pitch, self._aim_last_roll = pitch_t, roll_t
        self._aim_engaged = True

    def _aim_loop(self):
        sock = self._aim_sock
        while self._aim_running:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                data = None
            except OSError:
                break

            if data:
                self._aim_peer_ip = addr[0]
                try:
                    msg = json.loads(data)
                    found = bool(msg["found"])
                    yaw = float(msg["yaw"]) if found else 0.0
                    pitch = float(msg["pitch"]) if found else 0.0
                except (ValueError, KeyError, TypeError):
                    continue
                now = time.time()
                with self._aim_lock:
                    self._aim = {"yaw": yaw, "pitch": pitch, "found": found, "t": now}
                if found:
                    self._apply_aim(yaw, pitch)
                self._send_aim_feedback()

            if self._aim_engaged and (time.time() - self._aim_last_found_t) > cfg.AIM_LOST_GRACE_S:
                self.controller.stop_pitch()
                self.controller.stop_roll()
                self._aim_engaged = False

    def _send_aim_feedback(self):
        # Echo the gimbal's measured orientation back to the aim-packet sender so
        # an upstream display can show real vs commanded angles. yaw = roll axis.
        port = getattr(cfg, "AIM_FEEDBACK_PORT", 0)
        if not port or self._aim_peer_ip is None or self._aim_sock is None:
            return
        st = self.controller.get_state()
        payload = {
            "yaw": st["roll"]["measured"],
            "pitch": st["pitch"]["measured"],
            "engaged": self._aim_engaged,
        }
        try:
            self._aim_sock.sendto(
                json.dumps(payload).encode("utf-8"),
                (self._aim_peer_ip, int(port)),
            )
        except OSError:
            pass

    def _start_aiming(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self._aim_port))
        sock.settimeout(0.1)
        self._aim_sock = sock
        self._aim_running = True
        self._aim_thread = threading.Thread(target=self._aim_loop, daemon=True)
        self._aim_thread.start()

    def _stop_aiming(self):
        self._aim_running = False
        if self._aim_sock is not None:
            try:
                self._aim_sock.close()
            except OSError:
                pass
        if self._aim_thread is not None:
            self._aim_thread.join(timeout=1.0)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self):
        return self.sender.connect()

    def start(self):
        # Begin 25 Hz transmission so rx_status feedback flows and rate
        # commands actually reach the camera, then start the control loop.
        self.sender.start()
        self.controller.start()
        if self._track_port is not None:
            self._start_tracking()
        if self._point_port is not None:
            self._start_pointing()
        if self._aim_port is not None:
            self._start_aiming()

    def stop(self):
        if self._track_port is not None:
            self._stop_tracking()
        if self._point_port is not None:
            self._stop_pointing()
        if self._aim_port is not None:
            self._stop_aiming()
        self.controller.stop()
        self.sender.stop()
        self.sender.disconnect()


def _make_handler(calib):
    with open(_PAGE_PATH, "rb") as fh:
        page_bytes = fh.read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the terminal quiet

        def _send_json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page_bytes)))
                self.end_headers()
                self.wfile.write(page_bytes)
            elif path == "/data":
                self._send_json(calib.snapshot())
            else:
                self.send_error(404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send_json({"ok": False, "error": "invalid JSON"}, 400)
            try:
                axis = body.get("axis")
                if path == "/gains":
                    calib.apply_gains(axis, float(body["kp"]), float(body["ki"]), float(body["kd"]))
                elif path == "/setpoint":
                    calib.apply_setpoint(axis, float(body["deg"]))
                elif path == "/stop":
                    calib.stop_axis(axis)
                else:
                    return self.send_error(404)
            except (KeyError, ValueError, TypeError) as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            self._send_json({"ok": True, "state": calib.snapshot()})

    return Handler


def _parse_args(argv):
    host = ColibriSender.DEFAULT_HOST
    port = ColibriSender.DEFAULT_PORT
    http_host = "127.0.0.1"
    http_port = 8080
    track_port = None
    point_port = None
    aim_port = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--host" and i + 1 < len(argv):
            host = argv[i + 1]; i += 2
        elif a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1]); i += 2
        elif a == "--http-host" and i + 1 < len(argv):
            http_host = argv[i + 1]; i += 2
        elif a == "--http-port" and i + 1 < len(argv):
            http_port = int(argv[i + 1]); i += 2
        elif a == "--track-port" and i + 1 < len(argv):
            track_port = int(argv[i + 1]); i += 2
        elif a == "--track":  # enable ArUco follow on the default port
            track_port = cfg.TRACK_PORT; i += 1
        elif a == "--point-port" and i + 1 < len(argv):
            point_port = int(argv[i + 1]); i += 2
        elif a == "--point":  # enable wide-cam pointing on the default port
            point_port = cfg.POINT_PORT; i += 1
        elif a == "--aim-port" and i + 1 < len(argv):
            aim_port = int(argv[i + 1]); i += 2
        elif a == "--aim":  # enable absolute-angle aim on the default port
            aim_port = cfg.AIM_PORT; i += 1
        elif a in ("--help", "-h"):
            print(__doc__); sys.exit(0)
        else:
            print(f"❌ Error: Unknown option '{a}'"); sys.exit(1)

    # track / point / aim all drive the same absolute setpoints; only one may
    # own the gimbal at a time.
    if sum(p is not None for p in (track_port, point_port, aim_port)) > 1:
        print("❌ Error: use at most one of --track, --point, --aim"); sys.exit(1)
    return host, port, http_host, http_port, track_port, point_port, aim_port


def main():
    host, port, http_host, http_port, track_port, point_port, aim_port = _parse_args(sys.argv)

    calib = PidCalibrator(host, port, track_port=track_port, point_port=point_port,
                          aim_port=aim_port)
    if not calib.connect():
        print("❌ Could not connect to the proxy. Is proxy.py running?")
        sys.exit(1)
    calib.start()

    httpd = ThreadingHTTPServer((http_host, http_port), _make_handler(calib))
    url = f"http://{http_host}:{http_port}"
    print(f"🎛️  PID calibrator UI: {url}")
    if track_port is not None:
        print(f"🎯 ArUco follow enabled — listening for pixel error on udp/{track_port}")
    if point_port is not None:
        print(f"📍 Wide-cam pointing enabled — listening for detections on udp/{point_port}")
    if aim_port is not None:
        print(f"🎯 Aim enabled — listening for absolute yaw/pitch angles on udp/{aim_port}")
    print("   (camera transmission auto-started; Ctrl+C to quit)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        httpd.shutdown()
        calib.stop()


if __name__ == "__main__":
    main()
