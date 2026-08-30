#!/usr/bin/env python3
"""Minimal video and PID control UI."""

import os
from pathlib import Path
import re
import signal
import sys

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)


HERE = Path(__file__).resolve().parent
MEASUREMENT = re.compile(r"pitch\s+([-\d.]+).*pan\s+([-\d.]+)")


class VideoView(QLabel):
    def __init__(self):
        super().__init__("Waiting for RTP video")
        self.image = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(560, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setObjectName("video")

    def set_image(self, image):
        self.image = image
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def _render(self):
        if self.image is None:
            return
        pixmap = QPixmap.fromImage(self.image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Next Vision")
        self.setMinimumSize(980, 640)
        self.video_process = QProcess(self)
        self.control_process = QProcess(self)
        self.jpeg_buffer = bytearray()
        self.stopping_control = False
        self._build_ui()
        self._wire_processes()
        self.start_video()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 22)
        outer.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("NEXT VISION")
        title.setObjectName("title")
        self.status = QLabel("IDLE")
        self.status.setObjectName("status")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)
        video_panel = QFrame()
        video_panel.setObjectName("panel")
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(10, 10, 10, 10)
        self.video_view = VideoView()
        video_layout.addWidget(self.video_view, 1)
        video_footer = QHBoxLayout()
        self.video_state = QLabel("RTP  ·  UDP 5010")
        self.video_state.setObjectName("muted")
        restart_video = QPushButton()
        restart_video.setObjectName("iconButton")
        restart_video.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        restart_video.setToolTip("Restart video")
        restart_video.clicked.connect(self.start_video)
        video_footer.addWidget(self.video_state)
        video_footer.addStretch()
        video_footer.addWidget(restart_video)
        video_layout.addLayout(video_footer)
        body.addWidget(video_panel, 1)

        controls = QFrame()
        controls.setObjectName("panel")
        controls.setFixedWidth(310)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(18, 18, 18, 18)
        controls_layout.setSpacing(14)
        controls_layout.addWidget(self._section("FIELD CONNECTION"))
        connection = QFormLayout()
        connection.setSpacing(9)
        self.host = QLineEdit("192.168.1.30")
        self.port = self._integer(5000, 1, 65535)
        self.video_port = self._integer(5010, 1, 65535)
        connection.addRow("Host", self.host)
        connection.addRow("Control port", self.port)
        connection.addRow("Video port", self.video_port)
        controls_layout.addLayout(connection)

        controls_layout.addWidget(self._section("ANGLE SETPOINT"))
        angles = QFormLayout()
        angles.setSpacing(9)
        self.pitch = self._decimal(0.0, -90.0, 90.0, 1.0)
        self.pan = self._decimal(0.0, -180.0, 180.0, 1.0)
        angles.addRow("Pitch", self.pitch)
        angles.addRow("Pan", self.pan)
        controls_layout.addLayout(angles)

        controls_layout.addWidget(self._section("PID GAINS"))
        gains = QFormLayout()
        gains.setSpacing(9)
        self.kp = self._decimal(100.0, 0.0, 10000.0, 1.0, 3)
        self.ki = self._decimal(0.01, 0.0, 1000.0, 0.01, 4)
        self.kd = self._decimal(0.001, 0.0, 1000.0, 0.001, 4)
        gains.addRow("Kp", self.kp)
        gains.addRow("Ki", self.ki)
        gains.addRow("Kd", self.kd)
        controls_layout.addLayout(gains)

        self.measured = QLabel("Pitch  --.--°     Pan  --.--°")
        self.measured.setObjectName("readout")
        controls_layout.addWidget(self.measured)
        controls_layout.addStretch()

        buttons = QHBoxLayout()
        stop = QPushButton("Stop")
        stop.setObjectName("secondary")
        stop.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        stop.clicked.connect(self.stop_control)
        apply = QPushButton("Apply && Hold")
        apply.setObjectName("primary")
        apply.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        apply.clicked.connect(self.start_control)
        buttons.addWidget(stop)
        buttons.addWidget(apply, 1)
        controls_layout.addLayout(buttons)
        body.addWidget(controls)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLESHEET)

    def _wire_processes(self):
        self.video_process.readyReadStandardOutput.connect(self._read_video)
        self.video_process.readyReadStandardError.connect(self.video_process.readAllStandardError)
        self.video_process.finished.connect(lambda: self.video_state.setText("VIDEO STOPPED"))
        self.control_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.control_process.readyReadStandardOutput.connect(self._read_control)
        self.control_process.finished.connect(self._control_finished)

    @staticmethod
    def _section(text):
        label = QLabel(text)
        label.setObjectName("section")
        return label

    @staticmethod
    def _integer(value, low, high):
        box = QSpinBox()
        box.setRange(low, high)
        box.setValue(value)
        return box

    @staticmethod
    def _decimal(value, low, high, step, decimals=2):
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setValue(value)
        return box

    def start_video(self):
        self._stop_process(self.video_process)
        self.jpeg_buffer.clear()
        port = self.video_port.value()
        self.video_state.setText(f"RTP  ·  UDP {port}")
        caps = "application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96"
        args = [
            "-q", "udpsrc", f"port={port}", "buffer-size=4194304", f"caps={caps}", "!",
            "rtpjitterbuffer", "latency=200", "do-lost=true", "!",
            "rtph265depay", "!", "h265parse", "!", "avdec_h265", "!",
            "videoconvert", "!", "videoflip", "method=rotate-180", "!",
            "jpegenc", "quality=88", "!", "fdsink", "fd=1",
        ]
        self.video_process.start("gst-launch-1.0", args)

    def _read_video(self):
        self.jpeg_buffer.extend(bytes(self.video_process.readAllStandardOutput()))
        latest = None
        while True:
            start = self.jpeg_buffer.find(b"\xff\xd8")
            end = self.jpeg_buffer.find(b"\xff\xd9", max(start + 2, 0))
            if start < 0 or end < 0:
                break
            latest = bytes(self.jpeg_buffer[start:end + 2])
            del self.jpeg_buffer[:end + 2]
        if latest:
            image = QImage.fromData(latest, "JPEG")
            if not image.isNull():
                self.video_view.set_image(image)
                self.video_state.setText(f"LIVE  ·  UDP {self.video_port.value()}")

    def start_control(self):
        self.stop_control()
        self.stopping_control = False
        self._set_status("CONNECTING", "pending")
        args = [
            "-u", str(HERE / "angle_hold.py"),
            "--host", self.host.text().strip(), "--port", str(self.port.value()),
            "--pitch", str(self.pitch.value()), "--pan", str(self.pan.value()),
            "--kp", str(self.kp.value()), "--ki", str(self.ki.value()), "--kd", str(self.kd.value()),
        ]
        self.control_process.start(sys.executable, args)

    def stop_control(self):
        if self.control_process.state() == QProcess.ProcessState.NotRunning:
            self._set_status("IDLE", "idle")
            return
        self.stopping_control = True
        try:
            os.kill(int(self.control_process.processId()), signal.SIGINT)
        except (OSError, ProcessLookupError):
            pass
        if not self.control_process.waitForFinished(2000):
            self.control_process.kill()
            self.control_process.waitForFinished(1000)
        self._set_status("IDLE", "idle")

    def _read_control(self):
        output = bytes(self.control_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in output.splitlines():
            if line.startswith("Connected"):
                self._set_status("HOLDING", "live")
            match = MEASUREMENT.search(line)
            if match:
                self.measured.setText(
                    f"Pitch  {float(match.group(1)):6.2f}°     Pan  {float(match.group(2)):6.2f}°"
                )

    def _control_finished(self, exit_code, _status):
        if not self.stopping_control and exit_code:
            self._set_status("CONTROL ERROR", "error")
        elif not self.stopping_control:
            self._set_status("IDLE", "idle")
        self.stopping_control = False

    def _set_status(self, text, state):
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @staticmethod
    def _stop_process(process):
        if process.state() == QProcess.ProcessState.NotRunning:
            return
        process.terminate()
        if not process.waitForFinished(1000):
            process.kill()
            process.waitForFinished(1000)

    def closeEvent(self, event: QCloseEvent):
        self.stop_control()
        self._stop_process(self.video_process)
        event.accept()


STYLESHEET = """
QWidget { color: #e8edea; font: 13px "Inter", "DejaVu Sans"; }
QMainWindow, QWidget#root { background: #121514; }
QLabel#title { font-size: 18px; font-weight: 700; color: #f4f7f5; }
QLabel#status { padding: 6px 10px; border-radius: 4px; background: #272c2a; color: #aeb8b3; font-weight: 700; }
QLabel#status[state="live"] { background: #173b2b; color: #70dda4; }
QLabel#status[state="pending"] { background: #3c3219; color: #efc86a; }
QLabel#status[state="error"] { background: #422222; color: #ff8989; }
QFrame#panel { background: #1b1f1d; border: 1px solid #343a37; border-radius: 8px; }
QLabel#video { background: #090b0a; border: 0; border-radius: 5px; color: #79827e; font-size: 15px; }
QLabel#section { color: #84d7aa; font-size: 11px; font-weight: 700; padding-top: 5px; }
QLabel#muted { color: #8e9993; font-size: 11px; }
QLabel#readout { background: #111412; border: 1px solid #343a37; border-radius: 5px; padding: 10px; color: #d9e2dd; }
QLineEdit, QSpinBox, QDoubleSpinBox { background: #101311; border: 1px solid #3b433f; border-radius: 5px; padding: 7px; color: #f2f5f3; selection-background-color: #347b56; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #55c789; }
QPushButton { min-height: 34px; border-radius: 5px; padding: 0 11px; font-weight: 600; }
QPushButton#primary { background: #55c789; color: #08150e; border: 1px solid #55c789; }
QPushButton#primary:hover { background: #6bd69a; }
QPushButton#secondary { background: #252a28; color: #dbe2de; border: 1px solid #424945; }
QPushButton#secondary:hover, QPushButton#iconButton:hover { background: #303633; }
QPushButton#iconButton { min-width: 32px; max-width: 32px; background: #252a28; border: 1px solid #424945; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
