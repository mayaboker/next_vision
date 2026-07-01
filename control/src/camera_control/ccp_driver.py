import math
import socket
import time

import numpy as np

from src.camera_control.pid_control import PIDControl
import src.camera_control.settings as settings


class CCPDriver:
    def __init__(self, ip, port, resolution, feed_back_driver):
        self._ccp_ip = ip
        self._ccp_port = port

        self._feed_back_driver = feed_back_driver
        self._resolution = resolution

        self._subs = set()

        self.target = None
        self.pid_controller_r = None
        self.pid_controller_p = None

    @staticmethod
    def _add_checksum(command):
        check_sum = (sum(command) & 0xff)
        return command + bytes([check_sum])

    def _build_message(self, ir=False, axis_speed_depends_on_FOV=0, annotations_on_frame=1, b_NUC=0, black_hot=0, zoom=0,
                       horizontal_move=0, vertical_move=0):
       
        # byte 0,1,2
        header = b'\xb0\x3b\x77'

        # byte 3
        cam_mode = (b'\x80') if ir else (b'\x00')

        # byte 4
        axis_speed_depends_on_FOV_command = (b'\x01') if axis_speed_depends_on_FOV else (b'\x00')
        annotations_on_frame_command = (b'\x00') if annotations_on_frame else (b'\x40')
        commands1 = bytes([axis_speed_depends_on_FOV_command[0] + annotations_on_frame_command[0]])

        # byte 5
        NUC = (b'\x20') if b_NUC else (b'\x00')
        black_white_polarity = (b'\x10') if black_hot else (b'\x00')
        commands2 = bytes([NUC[0] + black_white_polarity[0]])

        # byte 6,7,8
        byte_678 = b'\x00\x00\x00'

        # byte 14,15,16,17,18 (zoom, rool, pitch)
        zoom_command = b'\x00'
        if zoom > 0:
            zoom_command = b'\x80'
        if zoom < 0:
            zoom_command = b'\x40'

        # byte 9,10,11,12,13
        correlators = b'\x01\x00\x00\x00\x00'

        bit_17 = b'\x80'  # consider change to b'\x00'

        bit_14 = zoom_command[0]
        bit_18 = b'\x00'[0]
        bit_14 &= b'\xc3'[0]
        bit_18 &= b'\xc3'[0]

        bit_15 = vertical_move >> 4
        bit_14 |= (vertical_move & 0x0c) << 2
        bit_18 |= (vertical_move & 0x03) << 4

        bit_16 = horizontal_move >> 4
        bit_14 |= horizontal_move & 0x0c
        bit_18 |= (horizontal_move & 0x03) << 2

        return self._add_checksum(
            header + cam_mode + commands1 + commands2 + byte_678 + correlators + bytes([bit_14]) + bytes(
                [bit_15]) + bytes([bit_16]) + bit_17 + bytes([bit_18]))

    def ptz_cb(self, cam_params, zoom=0, horizontal_move=0, vertical_move=0):
        ir, axis_speed_depends_on_FOV, annotations_on_frame, b_NUC, black_hot = cam_params

        self.send_packet(self._build_message(ir, axis_speed_depends_on_FOV, annotations_on_frame, b_NUC, black_hot, zoom,
                                             horizontal_move, vertical_move))

    def send_packet(self, packet):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self._ccp_ip, self._ccp_port))
        sock.settimeout(5.0)
        hex_data = ' '.join([f'{b:02X}' for b in packet])
        # Create the desired JSON structure
        data = b'{"cmd": "raw", "data": "' + hex_data.encode() + b'"}\n'
        sock.sendall(data)

    def rotation_matrix(self, yaw, pitch):
        R_y = np.array([
            [math.cos(yaw), 0, math.sin(yaw)],
            [0, 1, 0],
            [-math.sin(yaw), 0, math.cos(yaw)],
        ])

        R_x = np.array([
            [1, 0, 0],
            [0, math.cos(pitch), -math.sin(pitch)],
            [0, math.sin(pitch), math.cos(pitch)]
        ])

        return R_y.dot(R_x)

    def gimbal_angles_from_vector(self, point):
        psi = math.atan2(point[0], point[2])
        phi = -math.asin(point[1])
        return math.degrees(psi), math.degrees(phi)

    def calculate_box_to_pos(self, bbox):
        point1, point2 = bbox

        resolution = self._resolution

        cam_mode, gimbal_satus, camera_total_pitch, camera_total_roll, camera_FOV = self._feed_back_driver.get_current_parameters()
        orig_cam_roll = camera_total_roll[0]
        orig_cam_pitch = camera_total_pitch[0]
        orig_fov = camera_FOV

        # Zoom
        box_width = abs(point1[0] - point2[0])
        box_height = abs(point1[1] - point2[1])

        zoom_factor_x = box_width / resolution[1]
        zoom_factor_y = box_height / resolution[0]

        if (point1 == point2):
            target_fov_x = orig_fov[0]
            target_fov_y = orig_fov[1]
        else:
            target_fov_x = orig_fov[0] * zoom_factor_x
            target_fov_y = orig_fov[1] * zoom_factor_y

        # Rotation
        center_point = (point1[0] + point2[0]) / 2, (point1[1] + point2[1]) / 2

        focal_length = (resolution[1] / 2) / math.tan(math.radians(orig_fov[0] / 2)), (resolution[0] / 2) / math.tan(
            math.radians(orig_fov[1] / 2))

        x_offset = -(resolution[1] / 2) + center_point[0]
        y_offset = (resolution[0] / 2) - center_point[1]

        # Target Ray in camera frame
        r_cam = np.array([x_offset, y_offset, (focal_length[0] + focal_length[1]) / 2])
        r_cam_norm = r_cam / np.linalg.norm(r_cam)

        # Rotate camera ray into world coordinates
        R = self.rotation_matrix(math.radians(orig_cam_roll), math.radians(orig_cam_pitch))
        r_world = R.dot(r_cam_norm)

        # calculate new gimbal angles
        target_roll, target_pitch = self.gimbal_angles_from_vector(r_world)
        return target_pitch, target_roll, target_fov_x, target_fov_y

    def move_to_pos(self, target, cam_params):
        target_pitch, target_roll, target_fov_x, target_fov_y = target
        pid_controller_r = PIDControl(settings.PID_KP, settings.PID_KI, settings.PID_KD, setpoint=target_roll)
        pid_controller_p = PIDControl(settings.PID_KP, settings.PID_KI, settings.PID_KD, setpoint=target_pitch)

        while True:
            _, _, camera_total_pitch, camera_total_roll, camera_FOV = self._feed_back_driver.get_current_parameters()

            current_roll = camera_total_roll[0]
            current_pitch = camera_total_pitch[0]

            error_r = current_roll - target_roll
            error_p = current_pitch - target_pitch

            print("delta in roll: ", error_r)
            print("delta in pitch: ", error_p)
            
            if abs(error_r) > settings.PID_TOLERANCE:
                pid_output_r = pid_controller_r.update(current_roll,  settings.PID_DT)
                horizontal_move = max(settings.CAMERA_MIN_MOVEMENT_RATE, min(settings.CAMERA_MAX_MOVEMENT_RATE, pid_output_r + settings.CAMERA_MID_MOVEMENT_RATE))
            else:
                horizontal_move = settings.CAMERA_MID_MOVEMENT_RATE

            if abs(error_p) > settings.PID_TOLERANCE:
                pid_output_p = pid_controller_p.update(current_pitch,  settings.PID_DT)
                vertical_move = max(settings.CAMERA_MIN_MOVEMENT_RATE, min(settings.CAMERA_MAX_MOVEMENT_RATE, pid_output_p + settings.CAMERA_MID_MOVEMENT_RATE))
            else:
                vertical_move = settings.CAMERA_MID_MOVEMENT_RATE

            if target_fov_x < camera_FOV[0] and target_fov_y < camera_FOV[1]:
                zoom = 1
            elif abs(target_fov_x - camera_FOV[0]) < 2 or abs(target_fov_y - camera_FOV[1]) < 2:
                zoom = 0
            else:
                zoom = -1

            ir, axis_speed_depends_on_FOV, annotations_on_frame, b_NUC, black_hot = cam_params
            self.ptz_cb(cam_params, zoom, int(horizontal_move), int(vertical_move))
            time.sleep(settings.PID_DT)

            if (abs(error_r) <= settings.PID_TOLERANCE and abs(error_p) <= settings.PID_TOLERANCE):
                self.target = None
                break

    def zoom (self, zoom, cam_params):
        horizontal_move = settings.CAMERA_MID_MOVEMENT_RATE
        vertical_move = settings.CAMERA_MID_MOVEMENT_RATE
        self.ptz_cb(cam_params, zoom, int(horizontal_move), int(vertical_move))
        time.sleep(settings.PID_DT)

    def advance_to_pos(self, target, cam_params):
        self.target = target
        target_pitch, target_roll, target_fov_x, target_fov_y = self.target
        if self.pid_controller_r == None:
            self.pid_controller_r = PIDControl(settings.PID_KP, settings.PID_KI, settings.PID_KD, setpoint=target_roll)
        if self.pid_controller_p == None:
            self.pid_controller_p = PIDControl(settings.PID_KP, settings.PID_KI, settings.PID_KD, setpoint=target_pitch)

        _, _, camera_total_pitch, camera_total_roll, camera_FOV = self._feed_back_driver.get_current_parameters()

        current_roll = camera_total_roll[0]
        current_pitch = camera_total_pitch[0]

        error_r = current_roll - target_roll
        error_p = current_pitch - target_pitch
        #print ("current (p,r): ", current_pitch, " ", current_roll)
        #print ("error (p,r): ", error_p, " ", error_r)

        if abs(error_r) > settings.PID_TOLERANCE:
            pid_output_r = self.pid_controller_r.update(current_roll,  settings.PID_DT, target_roll)
            horizontal_move = max(settings.CAMERA_MIN_MOVEMENT_RATE, min(settings.CAMERA_MAX_MOVEMENT_RATE, pid_output_r + settings.CAMERA_MID_MOVEMENT_RATE))
        else:
            horizontal_move = settings.CAMERA_MID_MOVEMENT_RATE

        if abs(error_p) > settings.PID_TOLERANCE:
            pid_output_p = self.pid_controller_p.update(current_pitch,  settings.PID_DT, target_pitch)
            vertical_move = max(settings.CAMERA_MIN_MOVEMENT_RATE, min(settings.CAMERA_MAX_MOVEMENT_RATE, pid_output_p + settings.CAMERA_MID_MOVEMENT_RATE))
        else:
            vertical_move = settings.CAMERA_MID_MOVEMENT_RATE

        if target_fov_x < camera_FOV[0] and target_fov_y < camera_FOV[1]:
            zoom = 1
        elif abs(target_fov_x - camera_FOV[0]) < 2 or abs(target_fov_y - camera_FOV[1]) < 2:
            zoom = 0
        else:
            zoom = -1

        ir, axis_speed_depends_on_FOV, annotations_on_frame, b_NUC, black_hot = cam_params
        self.ptz_cb(cam_params, zoom, int(horizontal_move), int(vertical_move))
        time.sleep(settings.PID_DT)

        if (abs(error_r) <= settings.PID_TOLERANCE and abs(error_p) <= settings.PID_TOLERANCE):
            self.pid_controller_p = None
            self.pid_controller_r = None
            self.target = None
            return 1
        return 0
