#!/usr/bin/env python3
"""Hold the Colibri gimbal at fixed pitch and pan angles."""

import argparse
import json
import socket
import threading
import time


BASELINE = 2048
RATE_MIN = 0
RATE_MAX = 4095
OUTPUT_LIMIT = 2047
INTEGRAL_LIMIT = 2047
DT = 0.05

# Verified directions for the current camera mount.
PITCH_ACTUATOR_SIGN = -1
PAN_ACTUATOR_SIGN = -1
INVERT_PITCH = False
INVERT_PAN = True


def clamp(value, low, high):
    return max(low, min(high, value))


def wrap_180(angle):
    return (angle + 180.0) % 360.0 - 180.0


class PID:
    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.previous_error = None

    def update(self, error, dt):
        self.integral = clamp(
            self.integral + error * dt,
            -INTEGRAL_LIMIT,
            INTEGRAL_LIMIT,
        )
        derivative = 0.0
        if self.previous_error is not None and dt > 0:
            derivative = (error - self.previous_error) / dt
        self.previous_error = error
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        return clamp(output, -OUTPUT_LIMIT, OUTPUT_LIMIT)


class ProxyClient:
    def __init__(self, host, port):
        self.socket = socket.create_connection((host, port), timeout=5.0)
        self.socket.settimeout(None)
        self.send_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.status_event = threading.Event()
        self.latest_status = None
        self.latest_status_time = None
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receive_thread.start()

    def command(self, name, **values):
        message = {"cmd": name, **values}
        payload = (json.dumps(message) + "\n").encode("utf-8")
        with self.send_lock:
            self.socket.sendall(payload)

    def status(self):
        with self.status_lock:
            if self.latest_status is None:
                return None, None
            return dict(self.latest_status), self.latest_status_time

    def _receive_loop(self):
        buffer = ""
        try:
            while self.running:
                data = self.socket.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if message.get("type") == "rx_status":
                        with self.status_lock:
                            self.latest_status = message.get("status", {})
                            self.latest_status_time = time.monotonic()
                        self.status_event.set()
        except (OSError, UnicodeDecodeError):
            pass
        finally:
            self.running = False

    def close(self):
        self.running = False
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        self.receive_thread.join(timeout=1.0)


def rate_command(output, actuator_sign, inverted):
    rate = round(BASELINE + actuator_sign * output)
    rate = int(clamp(rate, RATE_MIN, RATE_MAX))
    if inverted:
        rate = int(clamp(2 * BASELINE - rate, RATE_MIN, RATE_MAX))
    return rate


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Field proxy IP")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--pitch", type=float, default=0.0, help="Pitch setpoint in degrees")
    parser.add_argument("--pan", type=float, default=0.0, help="Pan setpoint in degrees")
    parser.add_argument("--kp", type=float, default=100.0)
    parser.add_argument("--ki", type=float, default=0.01)
    parser.add_argument("--kd", type=float, default=0.001)
    parser.add_argument("--feedback-timeout", type=float, default=2.0)
    return parser.parse_args()


def main():
    args = parse_args()
    pitch_setpoint = clamp(args.pitch, -90.0, 90.0)
    pan_setpoint = clamp(args.pan, -180.0, 180.0)
    pitch_pid = PID(args.kp, args.ki, args.kd)
    pan_pid = PID(args.kp, args.ki, args.kd)

    client = ProxyClient(args.host, args.port)
    print(f"Connected to field proxy at {args.host}:{args.port}")

    try:
        client.command("start")
        if not client.status_event.wait(timeout=args.feedback_timeout):
            raise RuntimeError("no camera feedback received")

        previous_tick = time.monotonic()
        next_tick = previous_tick
        next_report = previous_tick
        while client.running:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(next_tick - now)
                now = time.monotonic()
            dt = max(now - previous_tick, 1e-6)
            previous_tick = now
            next_tick = now + DT

            status, status_time = client.status()
            if status is None or now - status_time > args.feedback_timeout:
                raise RuntimeError("camera feedback timed out")

            pitch = float(status["total_pitch_deg"])
            pan = float(status["total_roll_deg"])
            if INVERT_PITCH:
                pitch = -pitch
            if INVERT_PAN:
                pan = -pan

            pitch_output = pitch_pid.update(pitch_setpoint - pitch, dt)
            pan_output = pan_pid.update(wrap_180(pan_setpoint - pan), dt)
            client.command(
                "pitch",
                value=rate_command(pitch_output, PITCH_ACTUATOR_SIGN, INVERT_PITCH),
            )
            client.command(
                "roll",
                value=rate_command(pan_output, PAN_ACTUATOR_SIGN, INVERT_PAN),
            )

            if now >= next_report:
                print(
                    f"pitch {pitch:7.2f} -> {pitch_setpoint:7.2f} deg | "
                    f"pan {pan:7.2f} -> {pan_setpoint:7.2f} deg"
                )
                next_report = now + 1.0
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.command("pitch", value=BASELINE)
            client.command("roll", value=BASELINE)
            client.command("stop")
        except OSError:
            pass
        client.close()
        print("Stopped")


if __name__ == "__main__":
    main()
