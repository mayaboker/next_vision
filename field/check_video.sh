#!/usr/bin/env bash
set -u

device=${VIDEO_DEVICE:-}
if [[ -z "$device" ]]; then
    if [[ -e /dev/video11 ]] && [[ "$(cat /sys/class/video4linux/video11/name 2>/dev/null || true)" == "stream_hdmirx" ]]; then
        device=/dev/video11
    else
        device=/dev/video0
    fi
fi

echo "device: $device"
if [[ "$device" == /dev/video11 ]] || [[ "$(cat "/sys/class/video4linux/$(basename "$device")/name" 2>/dev/null || true)" == "stream_hdmirx" ]]; then
    echo "driver: rk_hdmirx"
    for f in status edid; do
        if [[ -r /sys/class/hdmirx/hdmirx/$f ]]; then
            printf 'hdmirx_%s: ' "$f"
            cat "/sys/class/hdmirx/hdmirx/$f"
        fi
    done
    v4l2-ctl -d "$device" --get-ctrl=power_present 2>&1 || true
    v4l2-ctl -d "$device" --get-dv-timings 2>&1 || true
else
    echo "driver: $(v4l2-ctl -d "$device" --all 2>/dev/null | awk -F: '/Driver name/ {gsub(/^[ \t]+/, "", $2); print $2; exit}')"
    v4l2-ctl -d "$device" --all 2>&1 | sed -n '1,35p'
fi
