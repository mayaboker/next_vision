#!/usr/bin/env python3
import os
import time
import sys
import termios
import tty
import select
import threading
import math
import gi
import socket
import numpy as np
import src.camera_control.settings as settings
from src.camera_control.pid_control import PIDControl
from src.camera_control.ccp_driver import CCPDriver
from src.camera_control.feedback_driver import FeedbackDriver
from enum import Enum

class camera_action(Enum):
    STATIC = 'static'
    NUC = 'nuc'
    MOVE_TO_POS = 'move_to_pos'
    ADVANCE_TO_POS = 'advance_to_pos'
    ZOOM = 'zoom'

class camera_control():
    def __init__(self):

        self.myFBdriver = FeedbackDriver(settings.CAMERA_FEEDBACK_IP, settings.CAMERA_PORT)
        feedback_thread = threading.Thread(target=self.myFBdriver.listen, daemon=True)
        feedback_thread.start()

        self.mydriver = CCPDriver(settings.CAMERA_IP, settings.CAMERA_PORT, settings.CAMERA_RESOLUTION, self.myFBdriver)
        self.started = False
        self.camera_action = camera_action.STATIC
        self.ir = settings.INIT_CAMERA_IR
        self.axis_speed_depends_on_FOV = settings.INIT_AXIS_SPEED_DEPEND_ON_FOV
        self.annotations_on_frame = settings.INIT_ANNOTATIONS_ON_FRAME
        self.b_NUC = settings.INIT_NUC
        self.black_hot = settings.INIT_BLACK_HOT
        self.target_pos = None

        self.is_running = True

    def set_ir(self):
        self.ir = True

    def set_vis(self):
        self.ir = False

    def set_black_hot(self):
        self.black_hot = 1

    def set_white_hot(self):
        self.black_hot = 0

    def enable_frame_annotations(self):
        self.annotations_on_frame = 1

    def disable_frame_annotations(self):
        self.annotations_on_frame = 0

    def shutdown(self):
        self.is_running = False

    def stop_movement(self):
        self.camera_action = camera_action.STATIC

    def nuc(self):
        self.camera_action = camera_action.NUC

    def move_to_bbox(self, bbox, wait_until_finish = 0):
        self.camera_action = camera_action.MOVE_TO_POS if wait_until_finish else camera_action.ADVANCE_TO_POS
        self.target_pos = self.mydriver.calculate_box_to_pos(bbox)

    def move_to_point(self, point, wait_until_finish = 0):
        self.camera_action = camera_action.MOVE_TO_POS if wait_until_finish else camera_action.ADVANCE_TO_POS
        self.target_pos = self.mydriver.calculate_box_to_pos((point, point))

    def move_to_pos(self, pitch, roll, fov, wait_until_finish = 0):
        self.camera_action = camera_action.MOVE_TO_POS if wait_until_finish else camera_action.ADVANCE_TO_POS
        self.target_pos = pitch, roll, fov[0], fov[1]

    def zoom(self, zoom):
        cam_params = (self.ir, self.axis_speed_depends_on_FOV, self.annotations_on_frame, self.b_NUC, self.black_hot)

        self.camera_action = camera_action.ZOOM 
        self.mydriver.zoom(zoom, cam_params)

    def get_status(self):
        return self.camera_action, self.myFBdriver.get_current_parameters()

    def get_pos(self):
        self.camera_action = camera_action.STATIC

        _, _, pitch, roll, fov = self.myFBdriver.get_current_parameters()   
        return pitch[0], roll[0], fov

    def run(self):
        self.camera_action = True
        while self.myFBdriver.get_current_parameters() == None:
            status_message = b'\xB0\x3B\x77\x60\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x80\x80\x80\x00\x43'
            self.mydriver.send_packet(status_message)
            time.sleep(settings.CAMERA_TIME_BETWEEN_COMMANDS)
        self.started = True
        vis,_, camera_total_pitch, camera_total_roll, camera_FOV = self.myFBdriver.get_current_parameters()
        self.ir = not vis
        self.target_pos = camera_total_pitch, camera_total_roll, camera_FOV[0], camera_FOV[1]

        while self.is_running:
            if self.camera_action == camera_action.STATIC :
                self.shutdown()

            cam_params = (self.ir, self.axis_speed_depends_on_FOV, self.annotations_on_frame, self.b_NUC, self.black_hot)

            if self.camera_action == camera_action.MOVE_TO_POS:
                if self.target_pos is not None:
                    self.mydriver.move_to_pos(self.target_pos, cam_params)
                    self.camera_action = camera_action.STATIC

            elif self.camera_action == camera_action.ADVANCE_TO_POS:
                if self.target_pos is not None:
                    if self.mydriver.advance_to_pos(self.target_pos, cam_params):
                        self.camera_action =  camera_action.STATIC

            elif self.camera_action == camera_action.NUC:
                self.b_NUC = 1
                cam_params = self.ir, self.axis_speed_depends_on_FOV, self.annotations_on_frame, self.b_NUC, self.black_hot
                self.mydriver.ptz_cb(cam_params, settings.INIT_ZOOM, settings.CAMERA_MID_MOVEMENT_RATE,settings.CAMERA_MID_MOVEMENT_RATE)
                time.sleep(settings.CAMERA_TIME_BETWEEN_COMMANDS)

                self.b_NUC = 0
                cam_params = self.ir, self.axis_speed_depends_on_FOV, self.annotations_on_frame, self.b_NUC, self.black_hot
                self.mydriver.ptz_cb(cam_params, settings.INIT_ZOOM, settings.CAMERA_MID_MOVEMENT_RATE, settings.CAMERA_MID_MOVEMENT_RATE)
                self.camera_action = camera_action.STATIC
            else:
                self.mydriver.ptz_cb(cam_params, settings.INIT_ZOOM, settings.CAMERA_MID_MOVEMENT_RATE, settings.CAMERA_MID_MOVEMENT_RATE)

            time.sleep(settings.CAMERA_TIME_BETWEEN_COMMANDS)
