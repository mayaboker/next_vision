"""
Standalone PID controller.

Same algorithm as control/src/camera_control/pid_control.py, but operates on a
caller-supplied ``error`` (so angle wrap-around can be handled by the caller)
and adds integral/output clamping for anti-windup.
"""


def _clamp(value, low, high):
    return max(low, min(high, value))


class PIDControl:
    def __init__(self, kp, ki, kd, output_limit, integral_limit):
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._output_limit = output_limit
        self._integral_limit = integral_limit
        self._last_error = 0.0
        self._integral = 0.0

    def reset(self):
        """Clear accumulated integral and derivative history."""
        self._last_error = 0.0
        self._integral = 0.0

    def update(self, error, dt):
        """Return the clamped PID output for the given error over dt seconds."""
        self._integral += error * dt
        self._integral = _clamp(self._integral, -self._integral_limit, self._integral_limit)

        derivative = (error - self._last_error) / dt if dt > 0 else 0.0
        self._last_error = error

        output = self._kp * error + self._ki * self._integral + self._kd * derivative
        return _clamp(output, -self._output_limit, self._output_limit)
