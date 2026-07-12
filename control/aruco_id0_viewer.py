#!/usr/bin/env python3
"""
ArUco viewer for the NextVision H265 stream.

Receives the UDP/H265 RTP stream over GStreamer (via OpenCV), detects ArUco
markers each frame, highlights the target marker (default id 0) on top of the
live video, and displays it.

Requirements:
  - OpenCV built WITH GStreamer support, and the aruco module
    (`pip install opencv-contrib-python`).
  - The same GStreamer plugins used by the plain gst-launch receiver
    (rtpjitterbuffer, rtph265depay, h265parse, avdec_h265, videoconvert).

IMPORTANT: the ArUco dictionary below MUST match the dictionary your physical
marker was generated from. id 0 exists in every dictionary but the black/white
pattern differs per dictionary, so a mismatch means nothing is detected.

Usage:
  python3 control/aruco_id0_viewer.py                     # port 5010, DICT_4X4_50, id 0, 180-flip on
  python3 control/aruco_id0_viewer.py --dict 6X6_250 --id 0
  python3 control/aruco_id0_viewer.py --port 5010 --no-flip
  (press 'q' in the window to quit)
"""

import argparse
import json
import sys

try:
    import cv2
    import numpy as np
except ImportError as e:
    sys.exit(f"Missing dependency: {e}. Install with: pip install opencv-contrib-python numpy")


def build_pipeline(port):
    """GStreamer receive pipeline terminating in an appsink for OpenCV."""
    return (
        f'udpsrc port={port} '
        f'caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96" ! '
        f'rtpjitterbuffer latency=50 ! rtph265depay ! h265parse ! avdec_h265 ! '
        f'videoconvert ! appsink drop=true max-buffers=1 sync=false'
    )


def aruco_dicts():
    """Map friendly names -> cv2.aruco predefined dictionary ids (built lazily)."""
    a = cv2.aruco
    names = [
        "4X4_50", "4X4_100", "4X4_250", "5X5_50", "5X5_100", "5X5_250",
        "6X6_50", "6X6_100", "6X6_250", "7X7_50", "7X7_100", "ARUCO_ORIGINAL",
    ]
    out = {}
    for n in names:
        const = getattr(a, f"DICT_{n}", None)
        if const is not None:
            out[n] = const
    return out


def make_detector(dictionary_id):
    """Return a detect(gray)->(corners, ids) closure that works across OpenCV
    aruco API versions (>=4.7 ArucoDetector, and the older functional API)."""
    a = cv2.aruco
    if hasattr(a, "getPredefinedDictionary"):
        dictionary = a.getPredefinedDictionary(dictionary_id)
    else:  # very old API
        dictionary = a.Dictionary_get(dictionary_id)

    if hasattr(a, "ArucoDetector"):          # OpenCV >= 4.7
        params = a.DetectorParameters()
        detector = a.ArucoDetector(dictionary, params)

        def detect(gray):
            corners, ids, _ = detector.detectMarkers(gray)
            return corners, ids
    else:                                    # OpenCV < 4.7
        params = a.DetectorParameters_create()

        def detect(gray):
            corners, ids, _ = a.detectMarkers(gray, dictionary, parameters=params)
            return corners, ids

    return detect


def main():
    parser = argparse.ArgumentParser(description="Overlay a target ArUco marker on the H265 stream.")
    parser.add_argument("--port", type=int, default=5010, help="UDP port of the H265 RTP stream (default 5010)")
    parser.add_argument("--dict", default="4X4_50", help="ArUco dictionary, must match the printed marker (default 4X4_50)")
    parser.add_argument("--id", type=int, default=0, help="Target marker id to highlight (default 0)")
    parser.add_argument("--no-flip", action="store_true", help="Do NOT rotate 180 (camera is mounted upside down by default)")
    parser.add_argument("--track", action="store_true", help="Send the marker pixel error over UDP to the PID follower")
    parser.add_argument("--track-host", default="127.0.0.1", help="Host of the PID follower (default 127.0.0.1)")
    parser.add_argument("--track-port", type=int, default=5005, help="UDP port of the PID follower (default 5005)")
    args = parser.parse_args()

    if not hasattr(cv2, "aruco"):
        sys.exit("cv2.aruco not found. Install the contrib build: pip install opencv-contrib-python")

    dicts = aruco_dicts()
    if args.dict not in dicts:
        sys.exit(f"Unknown --dict '{args.dict}'. Options: {', '.join(dicts)}")

    detect = make_detector(dicts[args.dict])
    flip_180 = not args.no_flip

    track_sock = None
    track_dst = None
    if args.track:
        import socket
        track_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        track_dst = (args.track_host, args.track_port)
        print(f"🎯 Tracking: sending pixel error to udp://{args.track_host}:{args.track_port}")

    cap = cv2.VideoCapture(build_pipeline(args.port), cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        sys.exit("Unable to open the video stream. Is the sender running and is OpenCV built with GStreamer?")

    win = f"ArUco id {args.id}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    font = cv2.FONT_HERSHEY_SIMPLEX
    green = (0, 255, 0)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("No frame received.")
            break

        if flip_180:
            frame = cv2.flip(frame, -1)   # -1 = both axes = 180 rotation (upside-down mount)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids = detect(gray)

        h, w = frame.shape[:2]
        fcx, fcy = w // 2, h // 2   # image center

        found = False
        cx = cy = None
        if ids is not None:
            for marker_corners, marker_id in zip(corners, ids.flatten()):
                if int(marker_id) != args.id:
                    continue
                found = True
                # Outline + built-in id label.
                cv2.aruco.drawDetectedMarkers(frame, [marker_corners], np.array([[marker_id]]))
                # Prominent center label.
                pts = marker_corners.reshape(-1, 2)
                cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
                cv2.circle(frame, (cx, cy), 4, green, -1)
                cv2.putText(frame, f"id {args.id}", (cx - 24, cy - 12), font, 0.8, green, 2, cv2.LINE_AA)
                break

        # Image-center crosshair + error line to the marker (tracking aid).
        cv2.drawMarker(frame, (fcx, fcy), (255, 255, 255), cv2.MARKER_CROSS, 20, 1)
        if found:
            cv2.line(frame, (fcx, fcy), (cx, cy), green, 1)

        # Send pixel error to the follower (ex,ey = marker - image center).
        # Detection runs on the 180-rotated (display) frame, so rotate the point
        # back around center before sending, giving the error in the sensor/gimbal
        # frame the PID expects. Rotating 180 about center negates both offsets.
        if track_sock is not None:
            if not found:
                ex = ey = 0
            elif flip_180:
                ex, ey = fcx - cx, fcy - cy
            else:
                ex, ey = cx - fcx, cy - fcy
            payload = json.dumps({"ex": ex, "ey": ey, "found": found, "w": w, "h": h}).encode()
            try:
                track_sock.sendto(payload, track_dst)
            except OSError:
                pass

        # Small HUD.
        status = "DETECTED" if found else "searching..."
        cv2.putText(frame, f"DICT_{args.dict}  id={args.id}  {status}  [q]=quit",
                    (10, 24), font, 0.6, green if found else (0, 200, 255), 2, cv2.LINE_AA)

        cv2.imshow(win, frame)
        if (cv2.waitKey(1) & 0xFF) == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
