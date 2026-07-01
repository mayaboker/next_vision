#!/usr/bin/env python3
import os
import socket
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

cmd_toggle_annotations = "ann"
cmd_camera_mode = "mode"
cmd_nuc = "nuc"        
cmd_get_pos = "get_pos"
cmd_zoom = "zoom"
cmd_set_pos = "set_pos"
cmd_goto_bbox = "goto_bbox"
cmd_goto_point = "goto_point"

def check_enaugth_arguments(cmd, arguments, required_amount):
    if len(arguments) != required_amount:
        print(cmd, " requires ", required_amount, " arguments. You supplied only ", len(arguments), ".")


if __name__=="__main__":

    if len(sys.argv) < 2:
        print("Please provide a command.")
        print("Examples:")
        print("ann 1                       - Annotations On")
        print("mode 1                      - Camera mode IR")
        print("nuc                         - NUC in thermal")
        print("get_pos                     - return Pitch, Roll and FOV")
        print("zoom 1                      - Manual Zoom in")
        print("set_pos 30 50 92            - Set Camera Pitch, Roll and FOV ")
        print("goto_bbox 10 10 100 100     - Focus on the bbox by pixel")
        print("goto_point 30 30            - Rotate to center pixel")


    command = sys.argv[1]
    arguments = sys.argv[2:]

    my_control = camera_control()
    control_thread = threading.Thread(target=my_control.run, daemon=True)
    control_thread.start()

    while not my_control.started:
        continue

    if command == cmd_toggle_annotations:
        check_enaugth_arguments(command, arguments, 1)
        if arguments == '1':
            my_control.enable_frame_annotations()
        else:
            my_control.disable_frame_annotations()

    elif command == cmd_camera_mode:
        check_enaugth_arguments(command, arguments, 1)
        if arguments == '1':
            my_control.set_ir()
        else:
            my_control.set_vis()
            
    elif command == cmd_nuc:
        my_control.nuc()

    elif command == cmd_get_pos:
        pos = my_control.get_pos()
        print(pos)

    elif command == cmd_zoom:
        check_enaugth_arguments(command, arguments, 1)
        if arguments == '1':
            my_control.zoom(1)
        else:
            my_control.zoom(-1)

    elif command == cmd_set_pos:
        check_enaugth_arguments(command, arguments, 3)
        my_control.move_to_pos(int(arguments[0]), int(arguments[1]), [int(arguments[2]),int(arguments[2])])

    elif command == cmd_goto_bbox:
        check_enaugth_arguments(command, arguments, 4)
        my_control.move_to_bbox([(int(arguments[0]), int(arguments[1])), (int(arguments[2]), int(arguments[3]))])

    elif command == cmd_goto_point:
        check_enaugth_arguments(command, arguments, 2)
        my_control.move_to_point((int(arguments[0]), int(arguments[1])),0)

    else:
        print("Unknown command.")
    
    control_thread.join()
