"""Direct Linux input and camera mapping for the T.16000M."""

from __future__ import annotations

from dataclasses import dataclass
import os
import struct


BASELINE = 2048
RATE_MIN = 0
RATE_MAX = 4095

YAW_AXIS = 0  # A1
PITCH_AXIS = 1  # A2
SENSOR_BUTTON = 1
ZOOM_IN_BUTTON = 4
FOCUS_INCREASE_BUTTON = 5
POLARITY_BUTTON = 6
NUC_BUTTON = 7
FOCUS_LOWER_BUTTON = 8
ZOOM_OUT_BUTTON = 9

BUTTON_ACTIONS = (
    (1, "RGB / Thermal"),
    (4, "Zoom in"),
    (9, "Zoom out"),
    (5, "Focus increase"),
    (8, "Focus lower"),
    (7, "NUC"),
    (6, "Black / White hot"),
)

BUTTON_POSITIONS = {
    0: (0.492, 0.284),
    1: (0.500, 0.607),
    2: (0.396, 0.473),
    3: (0.603, 0.461),
    4: (0.292, 0.472),
    5: (0.322, 0.506),
    6: (0.355, 0.554),
    7: (0.348, 0.661),
    8: (0.315, 0.602),
    9: (0.284, 0.547),
    10: (0.700, 0.479),
    11: (0.669, 0.514),
    12: (0.639, 0.556),
    13: (0.640, 0.674),
    14: (0.671, 0.606),
    15: (0.706, 0.565),
}
STICK_CENTER = (0.500, 0.456)


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    name: str
    guid: str
    axes: tuple[float, ...]
    buttons: tuple[bool, ...]


class LinuxJoystickInput:
    """Nonblocking Linux joystick reader."""

    EVENT = struct.Struct("IhBB")
    BUTTON = 0x01
    AXIS = 0x02
    INIT = 0x80

    def __init__(self, path="/dev/input/js0"):
        self.path = path
        self.fd = None
        self.axes = [0.0] * 4
        self.buttons = [False] * 16

    def open(self):
        self.close()
        try:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return False
        self.axes = [0.0] * 4
        self.buttons = [False] * 16
        return True

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None

    def poll(self):
        if self.fd is None:
            return None
        try:
            while True:
                data = os.read(self.fd, self.EVENT.size)
                if not data:
                    self.close()
                    return None
                if len(data) == self.EVENT.size:
                    self._apply(data)
        except BlockingIOError:
            pass
        except OSError:
            self.close()
            return None
        return ControllerSnapshot(
            name="Thrustmaster T.16000M",
            guid=self.path,
            axes=tuple(self.axes),
            buttons=tuple(self.buttons),
        )

    def _apply(self, data):
        _timestamp, value, event_type, number = self.EVENT.unpack(data)
        event_type &= ~self.INIT
        if event_type == self.AXIS:
            while number >= len(self.axes):
                self.axes.append(0.0)
            self.axes[number] = max(-1.0, min(1.0, value / 32767.0))
        elif event_type == self.BUTTON:
            while number >= len(self.buttons):
                self.buttons.append(False)
            self.buttons[number] = bool(value)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def axis_to_rate(value: float, deadzone: float, scale: int, inverted: bool = False) -> int:
    value = clamp(value, -1.0, 1.0)
    magnitude = abs(value)
    if magnitude <= deadzone:
        return BASELINE
    normalized = (magnitude - deadzone) / (1.0 - deadzone)
    signed = normalized if value > 0 else -normalized
    if inverted:
        signed = -signed
    return round(clamp(BASELINE + signed * scale, RATE_MIN, RATE_MAX))


def button(snapshot: ControllerSnapshot, index: int) -> bool:
    return index < len(snapshot.buttons) and snapshot.buttons[index]


def requested_direction(positive: bool, negative: bool) -> str:
    if positive == negative:
        return "stop"
    return "in" if positive else "out"


class CameraControls:
    def __init__(self, client, deadzone, rate_scale, invert_pitch, invert_yaw):
        self.client = client
        self.deadzone = deadzone
        self.rate_scale = rate_scale
        self.invert_pitch = invert_pitch
        self.invert_yaw = invert_yaw
        self.previous_buttons: tuple[bool, ...] = ()
        self.pitch_rate = BASELINE
        self.yaw_rate = BASELINE
        self.zoom = "stop"
        self.focus = "stop"

    def update(self, snapshot: ControllerSnapshot, axes_enabled: bool = True):
        commands = []
        pitch = snapshot.axes[PITCH_AXIS] if axes_enabled and len(snapshot.axes) > PITCH_AXIS else 0.0
        yaw = snapshot.axes[YAW_AXIS] if axes_enabled and len(snapshot.axes) > YAW_AXIS else 0.0
        pitch_rate = axis_to_rate(pitch, self.deadzone, self.rate_scale, self.invert_pitch)
        yaw_rate = axis_to_rate(yaw, self.deadzone, self.rate_scale, self.invert_yaw)
        if pitch_rate != self.pitch_rate:
            self.pitch_rate = pitch_rate
            commands.append(("pitch", {"value": pitch_rate}))
        if yaw_rate != self.yaw_rate:
            self.yaw_rate = yaw_rate
            commands.append(("roll", {"value": yaw_rate}))

        zoom = requested_direction(button(snapshot, ZOOM_IN_BUTTON), button(snapshot, ZOOM_OUT_BUTTON))
        if zoom != self.zoom:
            self.zoom = zoom
            commands.append(("zoom", {"value": zoom}))
        self._send(commands)

        increase_focus = button(snapshot, FOCUS_INCREASE_BUTTON)
        lower_focus = button(snapshot, FOCUS_LOWER_BUTTON)
        self.focus = "stop" if increase_focus == lower_focus else ("increase" if increase_focus else "lower")

        if self._pressed(snapshot, SENSOR_BUTTON):
            self.client.toggle_sensor()
        if self._pressed(snapshot, POLARITY_BUTTON):
            self.client.toggle_polarity()
        if self._pressed(snapshot, NUC_BUTTON):
            self.client.command("nuc")
        self.previous_buttons = snapshot.buttons

    def _pressed(self, snapshot: ControllerSnapshot, index: int) -> bool:
        was_pressed = index < len(self.previous_buttons) and self.previous_buttons[index]
        return button(snapshot, index) and not was_pressed

    def _send(self, commands):
        if not commands:
            return
        send_batch = getattr(self.client, "commands", None)
        if callable(send_batch):
            send_batch(commands)
            return
        for name, values in commands:
            self.client.command(name, **values)

    def neutral(self):
        self._send([
            ("pitch", {"value": BASELINE}),
            ("roll", {"value": BASELINE}),
            ("zoom", {"value": "stop"}),
        ])
        self.pitch_rate = BASELINE
        self.yaw_rate = BASELINE
        self.zoom = "stop"
        self.focus = "stop"
        self.previous_buttons = ()
