#!/usr/bin/env python3
import os
import socket
import cv2
import time
import sys
import termios
import tty
import select
import threading
import math 
import gi
import numpy as np

from src.camera_control.camera_control import camera_control
gi.require_version('Gst','1.0')
from gi.repository import Gst, GLib

global points
points = []
    
def mouse_callback(event, x, y, flags, param):
    global points
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x,y))

        
def streamer_thread():
    global points
    pipeline_str = (f'udpsrc port=5000 buffer-size=2500000 '
            f'caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=(int)96" ! '
            f'rtpjitterbuffer latency=0 drop-on-latency=true ! rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! appsink drop=true max-buffers=1 sync=false')
    global resolution

    cap = cv2.VideoCapture(pipeline_str, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        print("Error. Unable to open video stream.")
        return
    
    cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Stream", mouse_callback)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("No frame received.")
            break
        
        resolution = frame.shape
        if len(points) > 1:
            for i in range(int(len(points) / 2)):
                pt1 = points[2*i]
                pt2 = points[2*i + 1]
                cv2.rectangle(frame, pt1, pt2, (0,255,0), 2)
                
        cv2.imshow("Stream", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('r'):
            points = []
        elif key == ord('q'):
            break
        
    cap.release() 
    cv2.destroyAllWindows()         
        
if __name__=="__main__":

    gst_thread = threading.Thread(target=streamer_thread, daemon=True)
    gst_thread.start()

    my_control = camera_control()
    control_thread = threading.Thread(target=my_control.run, daemon=True)
    control_thread.start()
        
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    try:
        tty.setcbreak(fd)
        char = '1'

        while True:   

            if select.select([sys.stdin],[],[],0)[0]:
                char = sys.stdin.read(1)

            if char == 'd':
                my_control.disable_frame_annotations()
                char = '1'

            if char == 'e':
                my_control.enable_frame_annotations()
                char = '1'

            if char == '2':
                my_control.set_ir()
                char = '1'

            if char == '3':
                my_control.set_vis()
                char = '1'
            
            if char == 'n':
                my_control.nuc()
                char = '1'
                
            if char == '9':
                pos = my_control.get_pos()
                print(pos)
                char = '1'
            
            if char == '+':
                pos = my_control.zoom(1)
                char = '1'

            if char == '-':
                pos = my_control.zoom(-1)
                char = '1'
                
            if char == '8':
                roll = input("Roll: ")
                pitch = input("Pitch: ")
                fov = input("Fov: ")
                my_control.move_to_pos(int(pitch), int(roll), [int(fov),int(fov)])

                char = '1'
                
            if char == 'b':
                if len(points) > 1:
                    for i in range(int(len(points) / 2)):
                        my_control.move_to_bbox([points[2*i], points[2*i + 1]])
                        
                points = []
                char = '1'
            
            if char == 'p':
                if len(points) > 1:
                    for i in range(int(len(points) / 2)):
                        my_control.move_to_point(points[2*i],0)
                        
                points = []
                char = '1'
            
    
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd,termios.TCSADRAIN, old_settings)


