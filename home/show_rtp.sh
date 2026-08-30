#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [port]" >&2
    exit 2
fi

port=${1:-5010}

exec gst-launch-1.0 -v \
    udpsrc port="$port" buffer-size=4194304 \
        caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96" ! \
    rtpjitterbuffer latency=200 do-lost=true ! \
    rtph265depay ! h265parse ! \
    avdec_h265 output-corrupt=false ! \
    videoconvert ! videoflip method=rotate-180 ! \
    autovideosink sync=false
