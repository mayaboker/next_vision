import unittest

from thrustmaster import LinuxJoystickInput


class LinuxJoystickInputTests(unittest.TestCase):
    def test_decodes_axis_and_button_events(self):
        joystick = LinuxJoystickInput()
        joystick._apply(joystick.EVENT.pack(1, 16384, joystick.AXIS, 0))
        joystick._apply(joystick.EVENT.pack(2, 1, joystick.BUTTON, 9))

        self.assertAlmostEqual(joystick.axes[0], 0.5, places=3)
        self.assertTrue(joystick.buttons[9])

    def test_decodes_initialization_events(self):
        joystick = LinuxJoystickInput()
        joystick._apply(joystick.EVENT.pack(1, -32767, joystick.AXIS | joystick.INIT, 1))
        joystick._apply(joystick.EVENT.pack(2, 0, joystick.BUTTON | joystick.INIT, 4))

        self.assertEqual(joystick.axes[1], -1.0)
        self.assertFalse(joystick.buttons[4])


if __name__ == "__main__":
    unittest.main()
