## send

```

gst-launch-1.0 -v \
    v4l2src device=/dev/video0 ! \
    videoconvert ! \
    videoscale ! \
    video/x-raw,width=1920,height=1080,framerate=30/1 ! \
    queue ! \
    rtpvrawpay pt=96 ! \
    udpsink host=192.168.1.200 port=5000
    


```

##  get


```

gst-launch-1.0 -v     udpsrc port=5000 !     capsfilter caps="application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)RAW,sampling=(string)BGR,depth=(string)8,width=(string)1920,height=(string)1080,payload=(int)96" !     rtpvrawdepay !     videoconvert !     videoscale !     videoconvert !     xvimagesink sync=false


```

