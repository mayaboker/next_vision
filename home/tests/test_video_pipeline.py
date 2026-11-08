from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import unittest
from unittest.mock import Mock

from basic_ui import MainWindow


class VideoPipelineTests(unittest.TestCase):
    def test_receiver_keeps_native_frames_and_buffers_short_jitter(self):
        process = Mock()
        window = SimpleNamespace(
            video_process=process,
            _stop_process=Mock(),
            jpeg_buffer=bytearray(b"old frame"),
            video_port=SimpleNamespace(value=lambda: 5030),
            video_state=Mock(),
        )

        MainWindow.start_video(window)

        program, args = process.start.call_args.args
        self.assertEqual(program, "gst-launch-1.0")
        self.assertIn("port=5030", args)
        self.assertIn("latency=250", args)
        self.assertNotIn("videorate", args)
        self.assertFalse(any("framerate=" in arg for arg in args))
        self.assertIn("clocksync", args)
        self.assertIn("discard-corrupted-frames=true", args)
        self.assertEqual(window.jpeg_buffer, bytearray())
        self.assertEqual(window.video_frames, 0)
        window._stop_process.assert_called_once_with(process)

    def sender_args(self, **settings):
        script = Path(__file__).resolve().parents[2] / "field" / "stream_rtp.sh"
        env = os.environ.copy()
        for key in ("FPS", "WIDTH", "HEIGHT", "BITRATE", "VIDEO_THREADS",
                    "VIDEO_DEVICE", "SOURCE_CAPS", "SOURCE_MIN_BUFFERS", "ENCODER_FORMAT"):
            env.pop(key, None)
        env.update(settings)
        result = subprocess.run(
            ["bash", "-c", 'exec() { printf "%s\\0" "$@"; }; source "$1" 192.168.1.5',
             "test", str(script)],
            env=env, capture_output=True, check=True,
        )
        return result.stdout.decode().rstrip("\0").split("\0")

    def test_sender_uses_real_25_fps_and_repeats_keyframe_headers(self):
        args = self.sender_args()
        self.assertIn("video/x-raw,framerate=25/1", args)
        self.assertIn("gop=12", args)
        self.assertIn("header-mode=each-idr", args)

    def test_lower_frame_rate_and_native_capture_remain_configurable(self):
        caps = "video/x-raw,format=NV12,width=1920,height=1080"
        args = self.sender_args(FPS="12", SOURCE_CAPS=caps,
                                SOURCE_MIN_BUFFERS="12", ENCODER_FORMAT="NV12")
        self.assertIn("video/x-raw,framerate=12/1", args)
        self.assertIn("gop=6", args)
        self.assertIn("min-buffers=12", args)
        self.assertLess(args.index(caps), args.index("videoscale"))
        self.assertIn("video/x-raw,format=NV12", args)


if __name__ == "__main__":
    unittest.main()
