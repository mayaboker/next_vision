class PIDControl:
    def __init__(self, Kp, Ki, Kd, setpoint=0):
        self._Kp = Kp
        self._Ki = Ki
        self._Kd = Kd
        self._setpoint = setpoint
        self._last_error = 0.0
        self._integral = 0.0

    def update(self, current_value, dt, reset_target = None):
        if reset_target is not None:
            self._setpoint = reset_target

        error = current_value - self._setpoint
        self._integral += error * dt
        derivative = (error - self._last_error) / dt if dt > 0 else 0.0
        self._last_error = error
        output = self._Kp * error + self._Ki * self._integral + self._Kd * derivative
        return output
