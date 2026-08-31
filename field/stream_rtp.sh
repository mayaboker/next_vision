#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <home-ip> [port]" >&2
    exit 2
fi

home_ip=$1
port=${2:-5010}
video_device=${VIDEO_DEVICE:-/dev/video0}
fps=${FPS:-20}
width=${WIDTH:-1280}
height=${HEIGHT:-720}
threads=${VIDEO_THREADS:-4}

for value in "$fps" "$width" "$height" "$threads"; do
    [[ $value =~ ^[1-9][0-9]*$ ]] || { echo "Video settings must be positive integers" >&2; exit 2; }
done
((fps >= 2)) || { echo "FPS must be at least 2" >&2; exit 2; }

exec gst-launch-1.0 -q --no-position \
    v4l2src device="$video_device" do-timestamp=true ! \
    queue max-size-buffers=2 leaky=downstream ! \
    videorate drop-only=true ! video/x-raw,framerate="$fps/1" ! \
    videoscale n-threads="$threads" ! video/x-raw,width="$width",height="$height" ! \
    videoconvert n-threads="$threads" ! video/x-raw,format=I420 ! \
    queue max-size-buffers=2 leaky=downstream ! \
    mpph265enc rc-mode=cbr bps=4000000 gop="$fps" ! \
    h265parse ! \
    rtph265pay pt=96 mtu=1400 aggregate-mode=zero-latency config-interval=-1 ! \
    udpsink host="$home_ip" port="$port" sync=false async=false
