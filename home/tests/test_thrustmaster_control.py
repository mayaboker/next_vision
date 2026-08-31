import unittest

from thrustmaster import (
    BASELINE,
    CameraControls,
    ControllerSnapshot,
    axis_to_rate,
)


class FakeClient:
    def __init__(self):
        self.commands = []
        self.sensor = "visible"
        self.polarity = "white"

    def command(self, name, **values):
        self.commands.append((name, values))

    def toggle_sensor(self):
        self.sensor = "ir" if self.sensor == "visible" else "visible"
        self.command("sensor", value=self.sensor)
        return self.sensor

    def toggle_polarity(self):
        self.polarity = "black" if self.polarity == "white" else "white"
        self.command("polarity", value=self.polarity)
        return self.polarity


def snapshot(*, a1=0.0, a2=0.0, pressed=()):
    buttons = tuple(index in pressed for index in range(16))
    return ControllerSnapshot("T.16000M", "guid", (a1, a2), buttons)


class AxisMappingTests(unittest.TestCase):
    def test_deadzone_maps_to_neutral(self):
        self.assertEqual(axis_to_rate(0.08, 0.08, 1600), BASELINE)
        self.assertEqual(axis_to_rate(-0.08, 0.08, 1600), BASELINE)

    def test_full_axis_uses_configured_scale(self):
        self.assertEqual(axis_to_rate(1.0, 0.08, 1600), BASELINE + 1600)
        self.assertEqual(axis_to_rate(-1.0, 0.08, 1600), BASELINE - 1600)
        self.assertEqual(axis_to_rate(1.0, 0.08, 1600, inverted=True), BASELINE - 1600)


class CameraControlsTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.controls = CameraControls(self.client, 0.08, 1600, False, False)

    def test_a1_controls_yaw_and_a2_controls_pitch(self):
        self.controls.update(snapshot(a1=1.0, a2=-1.0))
        self.assertIn(("roll", {"value": BASELINE + 1600}), self.client.commands)
        self.assertIn(("pitch", {"value": BASELINE - 1600}), self.client.commands)

    def test_disarmed_axes_do_not_send_initial_extreme_values(self):
        self.controls.update(snapshot(a1=-1.0, a2=-1.0), axes_enabled=False)
        self.assertFalse(any(name in {"pitch", "roll"} for name, _values in self.client.commands))

    def test_inverted_pitch_reverses_a2(self):
        controls = CameraControls(self.client, 0.08, 1600, True, False)
        controls.update(snapshot(a2=1.0))
        self.assertIn(("pitch", {"value": BASELINE - 1600}), self.client.commands)

    def test_zoom_holds_and_stops_on_release(self):
        self.controls.update(snapshot(pressed={4}))
        self.controls.update(snapshot())
        self.assertEqual(
            [command for command in self.client.commands if command[0] == "zoom"],
            [("zoom", {"value": "in"}), ("zoom", {"value": "stop"})],
        )

    def test_toggle_buttons_only_fire_on_press_edge(self):
        held = snapshot(pressed={1, 6, 7})
        self.controls.update(held)
        self.controls.update(held)
        self.assertEqual(self.client.commands.count(("sensor", {"value": "ir"})), 1)
        self.assertEqual(self.client.commands.count(("polarity", {"value": "black"})), 1)
        self.assertEqual(self.client.commands.count(("nuc", {})), 1)

    def test_opposing_zoom_buttons_stop(self):
        self.controls.update(snapshot(pressed={4}))
        self.controls.update(snapshot(pressed={4, 9}))
        self.assertEqual(self.client.commands[-1], ("zoom", {"value": "stop"}))

    def test_neutral_stops_all_supported_continuous_controls(self):
        self.controls.update(snapshot(a1=1.0, a2=-1.0, pressed={4}))
        self.client.commands.clear()
        self.controls.neutral()
        self.assertEqual(
            self.client.commands,
            [
                ("pitch", {"value": BASELINE}),
                ("roll", {"value": BASELINE}),
                ("zoom", {"value": "stop"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
