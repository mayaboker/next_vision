#!/bin/bash -e
### BEGIN INIT INFO
# Provides:         
# Required-Start:
# Required-Stop:
# Default-Start:
# Default-Stop:
# Short-Description:
# Description:       Setup enable async for display
### END INIT INFO
#
#


case "$1" in
	start)
		python /local/10_apps/nextCAM/proxy.py /dev/ttyS0 1>>/tmp/next.log 2>>/tmp/next.log &	
		;;
	stop)
		;;
	restart|reload)
		;;
	*)
		echo "Usage: $0 {start|stop|restart}"
		exit 1
esac

exit $?

