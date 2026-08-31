import unittest

from basic_ui import UiControllerClient


class FakeWindow:
    def __init__(self):
        self.messages = None

    def _send_proxy_messages(self, *messages):
        self.messages = messages


class UiControllerClientTests(unittest.TestCase):
    def test_command_batches_update_and_immediate_send(self):
        window = FakeWindow()
        client = UiControllerClient(window)

        client.command("pitch", value=1234)

        self.assertEqual(
            window.messages,
            ({"cmd": "pitch", "value": 1234}, {"cmd": "send"}),
        )

    def test_multiple_updates_share_one_immediate_send(self):
        window = FakeWindow()
        client = UiControllerClient(window)

        client.commands([
            ("pitch", {"value": 1234}),
            ("roll", {"value": 2345}),
        ])

        self.assertEqual(
            window.messages,
            (
                {"cmd": "pitch", "value": 1234},
                {"cmd": "roll", "value": 2345},
                {"cmd": "send"},
            ),
        )


if __name__ == "__main__":
    unittest.main()
