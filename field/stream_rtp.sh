#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <home-ip> [port]" >&2
    exit 2
fi

home_ip=$1
port=${2:-5010}
video_device=${VIDEO_DEVICE:-/dev/video0}

exec gst-launch-1.0 -v \
    v4l2src device="$video_device" ! \
    videoconvert ! videoscale ! \
    video/x-raw,format=I420,width=1280,height=720,framerate=8/1 ! \
    queue leaky=downstream ! \
    mpph265enc rc-mode=cbr bps=4000000 gop=10 ! \
    h265parse ! \
    rtph265pay pt=96 aggregate-mode=zero-latency config-interval=-1 ! \
    udpsink host="$home_ip" port="$port" sync=false async=false
