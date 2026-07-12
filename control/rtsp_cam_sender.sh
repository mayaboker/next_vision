#!/usr/bin/env bash
gst-launch-1.0 -v v4l2src device=/dev/video0 ! videoconvert ! videoscale ! video/x-raw,format=I420,width=1920,height=1080,framerate=30/1 ! queue leaky=downstream ! mpph265enc rc-mode=cbr bps=2000000 gop=10 ! h265parse ! rtph265pay pt=96 aggregate-mode=zero-latency config-interval=-1 ! udpsink host=192.168.1.200 port=5010 sync=false async=false
