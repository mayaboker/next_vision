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

Then open the printed URL (default http://127.0.0.1:8080) in a browser.
On launch the calibrator auto-starts 25 Hz camera transmission (so rx_status
feedback flows and rate commands reach the camera) and stops it on exit.
"""

import json
import os
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
    from .event_bus import Event
    from .gimbal_pid_controller import GimbalPIDController
except ImportError:  # script import
    from event_bus import Event
    from gimbal_pid_controller import GimbalPIDController

_PAGE_PATH = os.path.join(_HERE, "calibrator_page.html")
_WINDOW_SECONDS = 30.0          # rolling plot window
_BUFFER_MAXLEN = 4000           # samples retained per stream
_FRESH_FEEDBACK_S = 2.0         # feedback considered live if newer than this


class PidCalibrator:
    def __init__(self, host, port):
        self.sender = ColibriSender(host, port)
        # Quiet the sender's terminal chatter; the GUI is the display now.
        self.sender.show_tx = False
        self.sender.show_rx_raw = False
        self.sender.show_rx_status = False

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
        return {
            "now": now,
            "window": _WINDOW_SECONDS,
            "connected": connected,
            "receiving": receiving,
            "last_feedback_age": (now - last_fb) if last_fb else None,
            "pitch": st["pitch"],
            "roll": st["roll"],
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
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self):
        return self.sender.connect()

    def start(self):
        # Begin 25 Hz transmission so rx_status feedback flows and rate
        # commands actually reach the camera, then start the control loop.
        self.sender.start()
        self.controller.start()

    def stop(self):
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
        elif a in ("--help", "-h"):
            print(__doc__); sys.exit(0)
        else:
            print(f"❌ Error: Unknown option '{a}'"); sys.exit(1)
    return host, port, http_host, http_port


def main():
    host, port, http_host, http_port = _parse_args(sys.argv)

    calib = PidCalibrator(host, port)
    if not calib.connect():
        print("❌ Could not connect to the proxy. Is proxy.py running?")
        sys.exit(1)
    calib.start()

    httpd = ThreadingHTTPServer((http_host, http_port), _make_handler(calib))
    url = f"http://{http_host}:{http_port}"
    print(f"🎛️  PID calibrator UI: {url}")
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
