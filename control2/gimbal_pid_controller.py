"""
Closed-loop gimbal angle controller.

Subscribes to a feedback Event (measured pitch/roll degrees, fired by the
sender on every rx_status) and drives the gimbal toward per-axis angle
setpoints by firing a command Event with (axis, speed) each control tick.

Speed is a rate 0..4095 with BASELINE (2048) meaning "no movement", so the
output naturally idles at BASELINE when the error reaches zero -> the axis
holds its target continuously (station-keeping).
"""

import threading
import time

try:  # package import (python -m control2.run_pid_shell)
    from . import settings as cfg
    from .pid import PIDControl, _clamp
except ImportError:  # script import (python control2/run_pid_shell.py)
    import settings as cfg
    from pid import PIDControl, _clamp


def _wrap180(angle):
    """Wrap an angle to [-180, 180) so error takes the shortest path.

    Note the exact boundary maps 180 -> -180 (the same physical heading), which
    is harmless for control.
    """
    return (angle + 180.0) % 360.0 - 180.0


class GimbalPIDController:
    def __init__(self, feedback_event, command_event, config=cfg):
        self._cfg = config
        self._command_event = command_event

        self._pitch_pid = PIDControl(config.KP, config.KI, config.KD,
                                     config.OUTPUT_LIMIT, config.INTEGRAL_LIMIT)
        self._roll_pid = PIDControl(config.KP, config.KI, config.KD,
                                    config.OUTPUT_LIMIT, config.INTEGRAL_LIMIT)

        # Latest measured angles (updated from feedback).
        self._measured_pitch = 0.0
        self._measured_roll = 0.0

        # Setpoints and per-axis engagement.
        self._pitch_setpoint = 0.0
        self._roll_setpoint = 0.0
        self._active_pitch = False
        self._active_roll = False

        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        feedback_event.subscribe(self._on_feedback)

    # ------------------------------------------------------------------ #
    # Feedback (sensor)
    # ------------------------------------------------------------------ #
    def _on_feedback(self, pitch_deg, roll_deg):
        """Store the latest measured angles (fired on every rx_status)."""
        with self._lock:
            self._measured_pitch = pitch_deg
            self._measured_roll = roll_deg

    # ------------------------------------------------------------------ #
    # Setpoint commands (from the CLI)
    # ------------------------------------------------------------------ #
    def set_pitch_deg(self, deg):
        deg = _clamp(deg, self._cfg.PITCH_MIN, self._cfg.PITCH_MAX)
        with self._lock:
            self._pitch_setpoint = deg
            self._pitch_pid.reset()
            self._active_pitch = True

    def set_roll_deg(self, deg):
        deg = _clamp(deg, self._cfg.ROLL_MIN, self._cfg.ROLL_MAX)
        with self._lock:
            self._roll_setpoint = deg
            self._roll_pid.reset()
            self._active_roll = True

    def set_pitch_gains(self, kp, ki, kd):
        with self._lock:
            self._pitch_pid.set_gains(kp, ki, kd)

    def set_roll_gains(self, kp, ki, kd):
        with self._lock:
            self._roll_pid.set_gains(kp, ki, kd)

    def get_state(self):
        """Thread-safe snapshot of both axes for a UI/calibration tool."""
        with self._lock:
            pkp, pki, pkd = self._pitch_pid.gains
            rkp, rki, rkd = self._roll_pid.gains
            return {
                "pitch": {
                    "kp": pkp, "ki": pki, "kd": pkd,
                    "setpoint": self._pitch_setpoint,
                    "active": self._active_pitch,
                    "measured": self._measured_pitch,
                    "min": self._cfg.PITCH_MIN, "max": self._cfg.PITCH_MAX,
                },
                "roll": {
                    "kp": rkp, "ki": rki, "kd": rkd,
                    "setpoint": self._roll_setpoint,
                    "active": self._active_roll,
                    "measured": self._measured_roll,
                    "min": self._cfg.ROLL_MIN, "max": self._cfg.ROLL_MAX,
                },
            }

    def stop_pitch(self):
        with self._lock:
            self._active_pitch = False
        self._command_event.fire("pitch", self._cfg.BASELINE)

    def stop_roll(self):
        with self._lock:
            self._active_roll = False
        self._command_event.fire("roll", self._cfg.BASELINE)

    # ------------------------------------------------------------------ #
    # Control loop lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Halt both axes and stop the control loop thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        with self._lock:
            self._active_pitch = False
            self._active_roll = False
        # Ensure the gimbal is left stationary.
        self._command_event.fire("pitch", self._cfg.BASELINE)
        self._command_event.fire("roll", self._cfg.BASELINE)

    def _loop(self):
        dt = self._cfg.DT
        while self._running:
            self._tick(dt)
            time.sleep(dt)

    def _tick(self, dt):
        """Compute and emit one control update for each active axis."""
        with self._lock:
            active_pitch = self._active_pitch
            active_roll = self._active_roll
            pitch_error = self._pitch_setpoint - self._measured_pitch
            roll_error = _wrap180(self._roll_setpoint - self._measured_roll)
            pitch_out = self._pitch_pid.update(pitch_error, dt) if active_pitch else 0.0
            roll_out = self._roll_pid.update(roll_error, dt) if active_roll else 0.0

        if active_pitch:
            self._command_event.fire("pitch", self._to_speed(pitch_out, self._cfg.PITCH_SIGN))
        if active_roll:
            self._command_event.fire("roll", self._to_speed(roll_out, self._cfg.ROLL_SIGN))

    def _to_speed(self, output, sign):
        speed = round(self._cfg.BASELINE + sign * output)
        return int(_clamp(speed, self._cfg.RATE_MIN, self._cfg.RATE_MAX))
