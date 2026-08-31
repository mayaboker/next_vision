#!/usr/bin/env python3
"""Minimal video and PID control UI."""

import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time

from PyQt6.QtCore import QProcess, QRectF, QSocketNotifier, QTimer, Qt
from PyQt6.QtGui import QColor, QCloseEvent, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QAbstractSocket, QTcpSocket
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from thrustmaster import (
    BUTTON_ACTIONS,
    BUTTON_POSITIONS,
    STICK_CENTER,
    CameraControls,
    LinuxJoystickInput,
    button,
)


HERE = Path(__file__).resolve().parent
MEASUREMENT = re.compile(r"tilt value\s+([-\d.]+).*pan value\s+([-\d.]+)")
ZOOM_TOLERANCE_DEG = 0.1
ZOOM_TIMEOUT_MS = 30_000
CONTROLLER_DEADZONE = 0.08
CONTROLLER_RATE_SCALE = 1600


class UiControllerClient:
    """Adapt joystick camera commands to the UI's existing proxy socket."""

    def __init__(self, window):
        self.window = window
        self.polarity = "white"

    def command(self, name, **values):
        self.commands([(name, values)])

    def commands(self, commands):
        messages = [{"cmd": name, **values} for name, values in commands]
        messages.append({"cmd": "send"})
        self.window._send_proxy_messages(*messages)

    def toggle_sensor(self):
        current = self.window.sensor.currentData()
        value = "ir" if current == "visible" else "visible"
        self.window.sensor.setCurrentIndex(self.window.sensor.findData(value))
        self.command("sensor", value=value)
        return value

    def toggle_polarity(self):
        self.polarity = "black" if self.polarity == "white" else "white"
        self.command("polarity", value=self.polarity)
        return self.polarity


class ControllerPanel(QWidget):
    """Small embedded T.16000M state and action display."""

    SOURCE_WIDTH = 1206
    SOURCE_HEIGHT = 954
    CROP = (280, 245, 640, 690)

    def __init__(self, window, start_input=True):
        super().__init__()
        self.window = window
        self.setObjectName("controllerPanel")
        self.setFixedWidth(272)
        self.setMinimumHeight(520)
        self.snapshot = None
        self.device = LinuxJoystickInput()
        self.controls = None
        self.notifier = None
        self.manual_axes_active = False
        self.manual_zoom_active = False
        self.axes_armed = False
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(250)
        self.reconnect_timer.timeout.connect(self._ensure_device)

        source = QImage(str(HERE / "assets/t16000m-button-layout.jpg"))
        x, y, width, height = self.CROP
        self.diagram = QPixmap.fromImage(source.copy(x, y, width, height))
        inverted = self.diagram.toImage()
        inverted.invertPixels()
        self.diagram = QPixmap.fromImage(inverted)
        if start_input:
            self._start_input()

    def _start_input(self):
        self.controls = CameraControls(
            UiControllerClient(self.window),
            CONTROLLER_DEADZONE,
            CONTROLLER_RATE_SCALE,
            True,
            False,
        )
        self.reconnect_timer.start()
        self._ensure_device()

    def _ensure_device(self):
        if self.device.fd is not None or not self.device.open():
            return
        self.notifier = QSocketNotifier(self.device.fd, QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._poll)
        self.axes_armed = False
        self._poll()

    def _poll(self, *_args):
        snapshot = self.device.poll()
        if snapshot is None:
            if self.notifier is not None:
                self.notifier.setEnabled(False)
                self.notifier.deleteLater()
                self.notifier = None
            if self.snapshot is not None:
                self.controls.neutral()
                self.window._controller_axes_changed(False)
            self.manual_axes_active = False
            self.manual_zoom_active = False
            self.axes_armed = False
        else:
            axes_centered = len(snapshot.axes) > 1 and all(
                abs(snapshot.axes[index]) <= CONTROLLER_DEADZONE
                for index in (0, 1)
                if index < len(snapshot.axes)
            )
            self.axes_armed = self.axes_armed or axes_centered
            axes_active = any(
                abs(snapshot.axes[index]) > CONTROLLER_DEADZONE
                for index in (0, 1)
                if index < len(snapshot.axes)
            ) and self.axes_armed
            if axes_active != self.manual_axes_active:
                self.manual_axes_active = axes_active
                self.window._controller_axes_changed(axes_active)

            zoom_active = button(snapshot, 4) or button(snapshot, 9)
            if zoom_active and not self.manual_zoom_active:
                self.window._controller_zoom_started()
            self.manual_zoom_active = zoom_active
            self.controls.update(snapshot, axes_enabled=self.axes_armed)

        self.snapshot = snapshot
        self.update()

    def shutdown(self):
        self.reconnect_timer.stop()
        if self.notifier is not None:
            self.notifier.setEnabled(False)
            self.notifier = None
        if self.controls is not None:
            self.controls.neutral()
        self.device.close()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1b1f1d"))
        painter.setPen(QPen(QColor("#343a37"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        self._text(painter, "THRUSTMASTER", 14, 14, 9, QColor("#84d7aa"), bold=True)
        live = self.snapshot is not None
        ready = live and self.axes_armed
        status = "LIVE" if ready else ("CENTER STICK" if live else "OFFLINE")
        status_color = QColor("#55c789") if ready else QColor("#efbd48") if live else QColor("#68736e")
        self._text(painter, status, 244, 14, 7, status_color, bold=True, right=True)
        painter.setBrush(status_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(250, 17, 8, 8)

        image_rect = QRectF(36, 38, 200, 210)
        painter.fillRect(image_rect, QColor("#151917"))
        painter.save()
        painter.setOpacity(0.48)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.drawPixmap(image_rect, self.diagram, QRectF(self.diagram.rect()))
        painter.restore()
        painter.fillRect(QRectF(image_rect.x(), image_rect.y(), 17, image_rect.height()), QColor("#151917"))
        painter.fillRect(QRectF(image_rect.right() - 17, image_rect.y(), 17, image_rect.height()), QColor("#151917"))
        self._draw_controller_markers(painter, image_rect)

        self._text(painter, "CAMERA CONTROLS", 14, 263, 9, QColor("#8e9993"), bold=True)
        buttons = self.snapshot.buttons if self.snapshot else ()
        for row, (index, action) in enumerate(BUTTON_ACTIONS):
            column = row % 2
            line = row // 2
            x = 13 + column * 124
            y = 281 + line * 38
            width = 118 if column == 0 else 121
            pressed = index < len(buttons) and buttons[index]
            self._action(painter, x, y, width, index, action, pressed)

        axes_y = 437
        self._text(painter, "AXES", 14, axes_y, 9, QColor("#8e9993"), bold=True)
        axes = self.snapshot.axes if self.snapshot else ()
        self._axis(painter, axes_y + 22, "A1", "Yaw", axes[0] if len(axes) > 0 else 0.0)
        self._axis(painter, axes_y + 66, "A2", "Pitch", -axes[1] if len(axes) > 1 else 0.0)

    def _draw_controller_markers(self, painter, rect):
        crop_x, crop_y, crop_width, crop_height = self.CROP
        buttons = self.snapshot.buttons if self.snapshot else ()
        for index, (normalized_x, normalized_y) in BUTTON_POSITIONS.items():
            source_x = normalized_x * self.SOURCE_WIDTH - crop_x
            source_y = normalized_y * self.SOURCE_HEIGHT - crop_y
            x = rect.x() + source_x / crop_width * rect.width()
            y = rect.y() + source_y / crop_height * rect.height()
            pressed = index < len(buttons) and buttons[index]
            painter.setBrush(QColor("#efbd48") if pressed else QColor("#111412"))
            painter.setPen(QPen(QColor("#efbd48") if pressed else QColor("#55c789"), 1.5))
            painter.drawEllipse(QRectF(x - 8, y - 8, 16, 16))
            self._text(painter, str(index), x, y - 5, 7, QColor("#121514") if pressed else QColor("#e8edea"), center=True)

        axes = self.snapshot.axes if self.snapshot else ()
        a1 = axes[0] if len(axes) > 0 else 0.0
        a2 = -axes[1] if len(axes) > 1 else 0.0
        source_x = STICK_CENTER[0] * self.SOURCE_WIDTH - crop_x
        source_y = STICK_CENTER[1] * self.SOURCE_HEIGHT - crop_y
        origin_x = rect.x() + source_x / crop_width * rect.width()
        origin_y = rect.y() + source_y / crop_height * rect.height()
        target_x = origin_x + a1 * 11
        target_y = origin_y + a2 * 11
        painter.setPen(QPen(QColor("#55c789"), 2.5))
        painter.drawLine(int(origin_x), int(origin_y), int(target_x), int(target_y))
        painter.setBrush(QColor("#55c789"))
        painter.drawEllipse(QRectF(target_x - 4, target_y - 4, 8, 8))

    def _action(self, painter, x, y, width, index, action, pressed):
        rect = QRectF(x, y, width, 31)
        painter.setBrush(QColor("#4d3d1c") if pressed else QColor("#252a28"))
        painter.setPen(QPen(QColor("#efbd48") if pressed else QColor("#424945"), 1))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setBrush(QColor("#efbd48") if pressed else QColor("#111412"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(x + 7, y + 7, 17, 17))
        self._text(painter, str(index), x + 15.5, y + 9, 7, QColor("#121514") if pressed else QColor("#8e9993"), center=True)
        self._text(painter, action, x + 29, y + 10, 7, QColor("#f2f5f3") if pressed else QColor("#aeb8b3"))

    def _axis(self, painter, y, name, action, value):
        self._text(painter, name, 14, y, 8, QColor("#55c789"), bold=True)
        self._text(painter, action, 42, y, 8, QColor("#dbe2de"))
        self._text(painter, f"{value:+.3f}", 258, y, 8, QColor("#8e9993"), right=True)
        bar = QRectF(14, y + 19, 244, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#252a28"))
        painter.drawRoundedRect(bar, 3, 3)
        painter.setPen(QPen(QColor("#46504b"), 1))
        painter.drawLine(int(bar.center().x()), int(bar.top() - 2), int(bar.center().x()), int(bar.bottom() + 2))
        marker_x = bar.center().x() + max(-1.0, min(1.0, value)) * (bar.width() / 2 - 5)
        painter.setBrush(QColor("#55c789"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(marker_x - 4, bar.center().y() - 4, 8, 8))

    @staticmethod
    def _text(painter, text, x, y, size, color, *, bold=False, center=False, right=False):
        font = QFont("DejaVu Sans", size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(color)
        metrics = painter.fontMetrics()
        if center:
            x -= metrics.horizontalAdvance(text) / 2
        elif right:
            x -= metrics.horizontalAdvance(text)
        painter.drawText(int(x), int(y + metrics.ascent()), text)


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
        self.setMinimumSize(1360, 660)
        self.video_process = QProcess(self)
        self.control_process = QProcess(self)
        self.proxy_socket = QTcpSocket(self)
        self.proxy_socket.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
        self.proxy_endpoint = None
        self.pending_commands = []
        self.jpeg_buffer = bytearray()
        self.video_frames = 0
        self.video_fps_started = time.monotonic()
        self.zoom_control_active = False
        self.zoom_direction = None
        self.zoom_timer = QTimer(self)
        self.zoom_timer.setSingleShot(True)
        self.zoom_timer.setInterval(ZOOM_TIMEOUT_MS)
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
        controls.setMinimumWidth(350)
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

        controls_layout.addWidget(self._section("CAMERA"))
        camera = QGridLayout()
        camera.setHorizontalSpacing(9)
        camera.setVerticalSpacing(9)
        self.sensor = QComboBox()
        self.sensor.addItem("RGB", "visible")
        self.sensor.addItem("IR", "ir")
        self.palette = QComboBox()
        self.palette.addItem("Grey", "grey")
        self.palette.addItem("Color 1", "color1")
        self.palette.addItem("Color 2", "color2")
        self.palette.addItem("Color 3", "color3")
        self.nuc = QPushButton("Trigger NUC")
        self.nuc.setObjectName("secondary")
        camera.addWidget(QLabel("Sensor"), 0, 0)
        camera.addWidget(self.sensor, 0, 1)
        camera.addWidget(QLabel("Palette"), 1, 0)
        camera.addWidget(self.palette, 1, 1)
        camera.addWidget(self.nuc, 2, 1)
        controls_layout.addLayout(camera)

        controls_layout.addWidget(self._section("ZOOM"))
        zoom = QGridLayout()
        zoom.setHorizontalSpacing(9)
        zoom.setVerticalSpacing(9)
        zoom.addWidget(self._field_header("Target HFOV"), 0, 0)
        zoom.addWidget(self._field_header("Value"), 0, 1)
        self.zoom_target = self._decimal(20.0, 0.1, 100.0, 1.0)
        self.zoom_value = self._value_label()
        zoom.addWidget(self.zoom_target, 1, 0)
        zoom.addWidget(self.zoom_value, 1, 1)
        zoom_buttons = QHBoxLayout()
        stop_zoom = QPushButton("Stop")
        stop_zoom.setObjectName("secondary")
        stop_zoom.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        start_zoom = QPushButton("Go To Target")
        start_zoom.setObjectName("primary")
        start_zoom.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        stop_zoom.clicked.connect(self.stop_zoom)
        start_zoom.clicked.connect(self.start_zoom)
        zoom_buttons.addWidget(stop_zoom)
        zoom_buttons.addWidget(start_zoom, 1)
        zoom.addLayout(zoom_buttons, 2, 0, 1, 2)
        self.camera_state = QLabel("CONNECTING")
        self.camera_state.setObjectName("muted")
        zoom.addWidget(self.camera_state, 3, 0, 1, 2)
        controls_layout.addLayout(zoom)

        controls_layout.addWidget(self._section("TARGET SETPOINTS"))
        targets = QGridLayout()
        targets.setHorizontalSpacing(9)
        targets.setVerticalSpacing(9)
        targets.addWidget(self._field_header("Axis"), 0, 0)
        targets.addWidget(self._field_header("Target"), 0, 1)
        targets.addWidget(self._field_header("Value"), 0, 2)
        self.tilt_target = self._decimal(0.0, -90.0, 90.0, 1.0)
        self.pan_target = self._decimal(0.0, -180.0, 180.0, 1.0)
        self.tilt_value = self._value_label()
        self.pan_value = self._value_label()
        targets.addWidget(QLabel("Tilt"), 1, 0)
        targets.addWidget(self.tilt_target, 1, 1)
        targets.addWidget(self.tilt_value, 1, 2)
        targets.addWidget(QLabel("Pan"), 2, 0)
        targets.addWidget(self.pan_target, 2, 1)
        targets.addWidget(self.pan_value, 2, 2)
        controls_layout.addLayout(targets)

        controls_layout.addWidget(self._section("PID GAINS"))
        gains = QGridLayout()
        gains.setHorizontalSpacing(9)
        gains.setVerticalSpacing(9)
        gains.addWidget(self._field_header("Gain"), 0, 0)
        gains.addWidget(self._field_header("Tilt"), 0, 1)
        gains.addWidget(self._field_header("Pan"), 0, 2)
        self.tilt_kp = self._decimal(100.0, 0.0, 10000.0, 1.0, 3)
        self.tilt_ki = self._decimal(0.01, 0.0, 1000.0, 0.01, 4)
        self.tilt_kd = self._decimal(0.001, 0.0, 1000.0, 0.001, 4)
        self.pan_kp = self._decimal(100.0, 0.0, 10000.0, 1.0, 3)
        self.pan_ki = self._decimal(0.01, 0.0, 1000.0, 0.01, 4)
        self.pan_kd = self._decimal(0.001, 0.0, 1000.0, 0.001, 4)
        for row, (name, tilt_gain, pan_gain) in enumerate(
            (("Kp", self.tilt_kp, self.pan_kp),
             ("Ki", self.tilt_ki, self.pan_ki),
             ("Kd", self.tilt_kd, self.pan_kd)),
            start=1,
        ):
            gains.addWidget(QLabel(name), row, 0)
            gains.addWidget(tilt_gain, row, 1)
            gains.addWidget(pan_gain, row, 2)
        controls_layout.addLayout(gains)
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
        controls_scroll = QScrollArea()
        controls_scroll.setObjectName("controlsScroll")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setFixedWidth(380)
        controls_scroll.setWidget(controls)
        self.controller_panel = ControllerPanel(self)
        body.addWidget(self.controller_panel)
        body.addWidget(controls_scroll)
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
        self.proxy_socket.connected.connect(self._proxy_connected)
        self.proxy_socket.disconnected.connect(self._proxy_disconnected)
        self.proxy_socket.readyRead.connect(self._read_proxy)
        self.proxy_socket.errorOccurred.connect(self._proxy_error)
        self.zoom_timer.timeout.connect(self._zoom_timed_out)
        self.sensor.activated.connect(self._set_sensor)
        self.palette.activated.connect(self._set_palette)
        self.nuc.clicked.connect(lambda: self._apply_camera_command("nuc"))
        self._connect_proxy()

    @staticmethod
    def _section(text):
        label = QLabel(text)
        label.setObjectName("section")
        return label

    @staticmethod
    def _field_header(text):
        label = QLabel(text)
        label.setObjectName("fieldHeader")
        return label

    @staticmethod
    def _value_label():
        label = QLabel("--.--°")
        label.setObjectName("value")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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

    def _connect_proxy(self):
        endpoint = (self.host.text().strip(), self.port.value())
        if self.proxy_endpoint != endpoint:
            self.proxy_socket.abort()
            self.proxy_endpoint = endpoint
        if self.proxy_socket.state() == QAbstractSocket.SocketState.UnconnectedState:
            self.camera_state.setText("CONNECTING")
            self.proxy_socket.connectToHost(*endpoint)

    def _send_proxy(self, command, **values):
        self._send_proxy_messages({"cmd": command, **values})

    def _send_proxy_messages(self, *messages):
        payload = b"".join((json.dumps(message) + "\n").encode("utf-8") for message in messages)
        if self.proxy_socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.proxy_socket.write(payload)
            self.proxy_socket.flush()
        else:
            self.pending_commands.append(payload)
            self._connect_proxy()

    def _proxy_connected(self):
        self.camera_state.setText("FIELD CONNECTED")
        self._send_proxy_messages({"cmd": "start"}, {"cmd": "get_settings"})
        for payload in self.pending_commands:
            self.proxy_socket.write(payload)
        self.proxy_socket.flush()
        self.pending_commands.clear()

    def _proxy_disconnected(self):
        self.camera_state.setText("FIELD DISCONNECTED")
        self.zoom_control_active = False
        self.zoom_timer.stop()

    def _proxy_error(self, _error):
        self.camera_state.setText("FIELD OFFLINE")

    def _read_proxy(self):
        while self.proxy_socket.canReadLine():
            try:
                message = json.loads(bytes(self.proxy_socket.readLine()))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if message.get("type") == "rx_status":
                self._update_camera_feedback(message.get("status", {}))
            elif isinstance(message.get("settings"), dict):
                settings = message["settings"]
                sensor = str(settings.get("sensor", "")).lower()
                sensor_index = self.sensor.findData(sensor)
                if sensor_index >= 0:
                    self.sensor.setCurrentIndex(sensor_index)
                polarity = str(settings.get("ir_polarity_mode", "")).lower()
                if polarity in {"white_hot", "black_hot"}:
                    self.controller_panel.controls.client.polarity = polarity.removesuffix("_hot")
            elif message.get("status") == "error":
                self.camera_state.setText(message.get("message", "COMMAND ERROR").upper())
            elif (message.get("status") == "ok" and message.get("message") not in {
                "Command sent", "Transmission started", "Zoom set to stop",
            }):
                self.camera_state.setText(message.get("message", "FIELD CONNECTED").upper())

    def _update_camera_feedback(self, status):
        sensor_index = self.sensor.findData(str(status.get("sensor", "")).lower())
        if sensor_index >= 0:
            self.sensor.setCurrentIndex(sensor_index)
        try:
            hfov = float(status["hfov_deg"])
        except (KeyError, TypeError, ValueError):
            return
        self.zoom_value.setText(f"{hfov:.2f}°")
        if not self.zoom_control_active:
            return

        error = self.zoom_target.value() - hfov
        if abs(error) <= ZOOM_TOLERANCE_DEG:
            self._finish_zoom("ZOOM TARGET REACHED")
            return
        direction = "out" if error > 0 else "in"
        if direction != self.zoom_direction:
            self.zoom_direction = direction
            self._apply_camera_command("zoom", value=direction)
            self.camera_state.setText(f"ZOOMING {direction.upper()}")

    def _apply_camera_command(self, command, **values):
        self._send_proxy_messages(
            {"cmd": command, **values},
            {"cmd": "send"},
        )

    def _set_sensor(self, index):
        self._apply_camera_command("sensor", value=self.sensor.itemData(index))

    def _set_palette(self, index):
        self._apply_camera_command("palette", value=self.palette.itemData(index))

    def start_zoom(self):
        if self.controller_panel.manual_zoom_active:
            self.camera_state.setText("JOYSTICK ZOOM ACTIVE")
            return
        zoom_step = round(math.log(100.0 / self.zoom_target.value(), 1.03))
        zoom_step = max(0, min(255, zoom_step))
        self.zoom_target.setValue(100.0 / (1.03 ** zoom_step))
        self.zoom_control_active = True
        self.zoom_direction = None
        self.zoom_timer.start()
        self.camera_state.setText("SEEKING ZOOM TARGET")
        self._send_proxy("start")

    def stop_zoom(self):
        self._finish_zoom("ZOOM STOPPED")

    def _finish_zoom(self, message):
        self.zoom_control_active = False
        self.zoom_direction = None
        self.zoom_timer.stop()
        self._apply_camera_command("zoom", value="stop")
        self.camera_state.setText(message)

    def _zoom_timed_out(self):
        self._finish_zoom("ZOOM TIMEOUT")

    def _controller_zoom_started(self):
        self.zoom_control_active = False
        self.zoom_direction = None
        self.zoom_timer.stop()
        self.camera_state.setText("JOYSTICK ZOOM")

    def _controller_axes_changed(self, active):
        if active:
            if self.control_process.state() != QProcess.ProcessState.NotRunning:
                self.stop_control()
            self._send_proxy("start")
            self._set_status("JOYSTICK", "live")
        elif self.status.text() == "JOYSTICK":
            self._set_status("IDLE", "idle")

    def start_video(self):
        self._stop_process(self.video_process)
        self.jpeg_buffer.clear()
        self.video_frames = 0
        self.video_fps_started = time.monotonic()
        port = self.video_port.value()
        self.video_state.setText(f"RTP  ·  UDP {port}")
        caps = "application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96"
        args = [
            "-q", "udpsrc", f"port={port}", "buffer-size=4194304", f"caps={caps}", "!",
            "rtpjitterbuffer", "latency=150", "drop-on-latency=true", "do-lost=true", "!",
            "rtph265depay", "!", "h265parse", "!",
            "avdec_h265", "output-corrupt=false", "discard-corrupted-frames=true", "!",
            "videorate", "!", "video/x-raw,framerate=24/1", "!",
            "videoconvert", "!", "videoflip", "method=rotate-180", "!",
            "clocksync", "sync=true", "!",
            "queue", "max-size-buffers=1", "leaky=downstream", "!",
            "jpegenc", "quality=82", "!", "fdsink", "fd=1", "sync=false",
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
                self.video_frames += 1
                elapsed = time.monotonic() - self.video_fps_started
                if elapsed >= 1.0:
                    self.video_state.setText(
                        f"LIVE  ·  {self.video_frames / elapsed:.1f} FPS  ·  UDP {self.video_port.value()}"
                    )
                    self.video_frames = 0
                    self.video_fps_started = time.monotonic()

    def start_control(self):
        if self.controller_panel.manual_axes_active:
            self._set_status("CENTER JOYSTICK", "pending")
            return
        self.stop_control()
        self.stopping_control = False
        self._set_status("CONNECTING", "pending")
        self._connect_proxy()
        args = [
            "-u", str(HERE / "angle_hold.py"),
            "--host", self.host.text().strip(), "--port", str(self.port.value()),
            "--tilt-target", str(self.tilt_target.value()),
            "--pan-target", str(self.pan_target.value()),
            "--tilt-kp", str(self.tilt_kp.value()),
            "--tilt-ki", str(self.tilt_ki.value()),
            "--tilt-kd", str(self.tilt_kd.value()),
            "--pan-kp", str(self.pan_kp.value()),
            "--pan-ki", str(self.pan_ki.value()),
            "--pan-kd", str(self.pan_kd.value()),
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
                self.tilt_value.setText(f"{float(match.group(1)):.2f}°")
                self.pan_value.setText(f"{float(match.group(2)):.2f}°")

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
        if self.zoom_control_active:
            self._finish_zoom("ZOOM STOPPED")
            self.proxy_socket.waitForBytesWritten(200)
        self.controller_panel.shutdown()
        self.proxy_socket.waitForBytesWritten(200)
        self.proxy_socket.disconnectFromHost()
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
QWidget#controllerPanel { background: #1b1f1d; border: 0; }
QLabel#video { background: #090b0a; border: 0; border-radius: 5px; color: #79827e; font-size: 15px; }
QLabel#section { color: #84d7aa; font-size: 11px; font-weight: 700; padding-top: 5px; }
QLabel#muted { color: #8e9993; font-size: 11px; }
QLabel#fieldHeader { color: #8e9993; font-size: 11px; }
QLabel#value { background: #111412; border: 1px solid #343a37; border-radius: 5px; padding: 7px; color: #d9e2dd; }
QScrollArea#controlsScroll { background: transparent; }
QScrollBar:vertical { background: #151917; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #46504b; min-height: 28px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101311; border: 1px solid #3b433f; border-radius: 5px; padding: 7px; color: #f2f5f3; selection-background-color: #347b56; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #55c789; }
QComboBox QAbstractItemView { background: #101311; color: #f2f5f3; border: 1px solid #46504b; outline: 0; selection-background-color: #347b56; selection-color: #ffffff; padding: 4px; }
QComboBox::drop-down { border: 0; width: 26px; }
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
