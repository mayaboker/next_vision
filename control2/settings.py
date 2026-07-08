"""
Self-contained tuning for the control2 gimbal PID.

Values mirror control/src/camera_control/settings.py but are duplicated here so
control2 has no dependency on the control/ package.
"""

# PID gains (error is in degrees).
# KP = 100.0
# KI = 0.1
# KD = 0.001
KP = 500
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
PITCH_SIGN = -1
ROLL_SIGN = -1

# Allowed setpoint ranges (from the CLI spec).
PITCH_MIN = -90
PITCH_MAX = 90.0
ROLL_MIN = -180.0
ROLL_MAX = 180.0

# ---------------------------------------------------------------------------
# ArUco visual-follow (outer loop) tuning
# ---------------------------------------------------------------------------
# UDP port the calibrator binds to receive pixel-error packets from the viewer.
TRACK_PORT = 5005

# Per-axis direction from image error -> gimbal motion. Combined with the 180
# display flip + hardware direction; flip a sign if that axis chases the wrong
# way during bring-up. BRING-UP TUNABLE.
PITCH_TRACK_SIGN = +1
ROLL_TRACK_SIGN = +1

# Normalized dead-zone (fraction of half-frame). Within this the axis is left
# alone so the gimbal doesn't jitter when the marker is already ~centered.
TRACK_DEADBAND = 0.03

# Max angle the setpoint may move away from the current angle in one update
# (deg). Rejects detection glitches / huge jumps.
TRACK_MAX_STEP_DEG = 15.0

# If no "found" packet arrives within this many seconds, stop the gimbal.
TRACK_LOST_GRACE_S = 0.5

# FOV fallback (deg) used only if rx_status has not reported FOV yet.
TRACK_FALLBACK_HFOV = 60.0
TRACK_FALLBACK_VFOV = 34.0

# ---------------------------------------------------------------------------
# Wide-camera "point-at-detection" mode (absolute pointing)
# ---------------------------------------------------------------------------
# The wide detection camera is FIXED and boresight-aligned with the gimbal at
# center. A detection's off-axis angle in the wide frame IS the absolute gimbal
# angle to point at it (no dependence on current gimbal angle).
# UDP port the calibrator binds to receive wide-camera detection packets.
POINT_PORT = 5006

# Per-axis direction from wide-frame detection -> gimbal angle. Flip if an axis
# points the wrong way during bring-up. BRING-UP TUNABLE.
PITCH_POINT_SIGN = +1
ROLL_POINT_SIGN = +1

# Max the pointing setpoint may jump in one update (deg); rejects glitches.
POINT_MAX_STEP_DEG = 20.0

# If no "found" detection arrives within this many seconds, stop the gimbal.
POINT_LOST_GRACE_S = 0.5
