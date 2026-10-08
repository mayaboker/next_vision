#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <home-ip> [port]" >&2
    exit 2
fi

home_ip=$1
port=${2:-5010}
if [[ -n "${VIDEO_DEVICE:-}" ]]; then
    video_device=$VIDEO_DEVICE
elif [[ -e /dev/video11 ]] && [[ "$(cat /sys/class/video4linux/video11/name 2>/dev/null || true)" == "stream_hdmirx" ]]; then
    video_device=/dev/video11
else
    video_device=/dev/video0
fi
fps=${FPS:-12}
width=${WIDTH:-1280}
height=${HEIGHT:-720}
threads=${VIDEO_THREADS:-4}
bitrate=${BITRATE:-3000000}

for value in "$fps" "$width" "$height" "$threads" "$bitrate"; do
    [[ $value =~ ^[1-9][0-9]*$ ]] || { echo "Video settings must be positive integers" >&2; exit 2; }
done
((fps >= 2)) || { echo "FPS must be at least 2" >&2; exit 2; }

if [[ "$video_device" == "/dev/video11" ]]; then
    hdmirx_status=$(cat /sys/class/hdmirx/hdmirx/status 2>/dev/null || true)
    power_present=$(v4l2-ctl -d "$video_device" --get-ctrl=power_present 2>/dev/null | awk -F': ' '{print $2}')
    if [[ "$hdmirx_status" != "connected" || "$power_present" != "1" ]]; then
        echo "DragonEye HDMI input is unavailable (status=$hdmirx_status power_present=${power_present:-0})" >&2
        echo "Connect and power the camera at the board HDMI-IN, then rerun this command." >&2
        exit 1
    fi
fi

exec gst-launch-1.0 -q --no-position \
    v4l2src device="$video_device" io-mode=4 do-timestamp=true ! \
    queue max-size-buffers=2 leaky=downstream ! \
    videorate drop-only=true ! video/x-raw,framerate="$fps/1" ! \
    videoscale n-threads="$threads" ! video/x-raw,width="$width",height="$height" ! \
    videoconvert n-threads="$threads" ! video/x-raw,format=I420 ! \
    queue max-size-buffers=2 leaky=downstream ! \
    mpph265enc rc-mode=cbr bps="$bitrate" gop="$((fps / 2))" ! \
    h265parse ! \
    rtph265pay pt=96 mtu=1400 aggregate-mode=zero-latency config-interval=-1 ! \
    udpsink host="$home_ip" port="$port" sync=false async=false
