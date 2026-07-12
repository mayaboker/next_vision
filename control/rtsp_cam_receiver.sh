#!/usr/bin/env bash
gst-launch-1.0 udpsrc port=5010 buffer-size=4194304 caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96" ! rtpjitterbuffer latency=200 do-lost=true ! rtph265depay ! h265parse ! avdec_h265 output-corrupt=false ! videoconvert ! videoflip method=rotate-180 ! autovideosink sync=false
