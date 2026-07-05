"""
Self-contained tuning for the control2 gimbal PID.

Values mirror control/src/camera_control/settings.py but are duplicated here so
control2 has no dependency on the control/ package.
"""

# PID gains (error is in degrees).
KP = 100.0
KI = 0.1
KD = 0.001

DT = 0.05            # control loop period, seconds
TOLERANCE = 0.1      # deg; within this the PID naturally outputs ~BASELINE

# Rate command mapping. Baseline = no movement (RATE_MIDDLE_VAL in the driver).
BASELINE = 2048
RATE_MIN = 0
RATE_MAX = 4095

# Clamp the PID output so BASELINE +/- output stays inside [RATE_MIN, RATE_MAX].
OUTPUT_LIMIT = 2047
# Anti-windup: clamp the accumulated integral term.
INTEGRAL_LIMIT = 2047

# Per-axis actuator direction. If, on real hardware, an axis runs AWAY from the
# target (diverges / saturates), flip the sign for that axis. BRING-UP TUNABLE.
PITCH_SIGN = +1
ROLL_SIGN = -1

# Allowed setpoint ranges (from the CLI spec).
PITCH_MIN = 0.0
PITCH_MAX = 90.0
ROLL_MIN = -180.0
ROLL_MAX = 180.0
