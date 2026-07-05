#!/usr/bin/env python3
"""
Closed-loop launcher: the standard Colibri sender shell plus PID angle-hold.

Wires the serailcontroler sender to the control2 GimbalPIDController via two
Events, and extends the CLI with:

    pitch_deg <0-90>       hold pitch at an absolute angle
    roll_deg  <-180-180>   hold roll  at an absolute angle

Run 'start' first so feedback flows and rate commands transmit.

Usage:
    python control2/run_pid_shell.py [--host <ip>] [--port <port>]
"""

import os
import sys

# Make both this dir (control2) and the sibling serailcontroler dir importable
# whether launched as "python control2/run_pid_shell.py" or "-m control2.run_pid_shell".
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO, "serailcontroler")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sender import ColibriSender, SenderShell  # noqa: E402  (from serailcontroler)

try:  # package import
    from .event_bus import Event
    from .gimbal_pid_controller import GimbalPIDController
except ImportError:  # script import
    from event_bus import Event
    from gimbal_pid_controller import GimbalPIDController


class PidSenderShell(SenderShell):
    """SenderShell extended with absolute-angle PID hold commands."""

    def __init__(self, sender, controller):
        super().__init__(sender)
        self.controller = controller

    def do_pitch_deg(self, line):
        """Hold pitch at an absolute angle via PID: pitch_deg <0-90>  (run 'start' first)"""
        try:
            deg = float(line)
        except ValueError:
            print("Usage: pitch_deg <0-90>")
            return
        if not (0.0 <= deg <= 90.0):
            print("Pitch angle must be between 0 and 90 degrees")
            return
        self.controller.set_pitch_deg(deg)
        print(f"🎯 Holding pitch at {deg:.2f}°")

    def do_roll_deg(self, line):
        """Hold roll at an absolute angle via PID: roll_deg <-180-180>  (run 'start' first)"""
        try:
            deg = float(line)
        except ValueError:
            print("Usage: roll_deg <-180-180>")
            return
        if not (-180.0 <= deg <= 180.0):
            print("Roll angle must be between -180 and 180 degrees")
            return
        self.controller.set_roll_deg(deg)
        print(f"🎯 Holding roll at {deg:.2f}°")


def _parse_args(argv):
    host = ColibriSender.DEFAULT_HOST
    port = ColibriSender.DEFAULT_PORT
    i = 1
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
        elif argv[i] == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                print(f"❌ Error: Invalid port '{argv[i + 1]}'")
                sys.exit(1)
            i += 2
        elif argv[i] in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"❌ Error: Unknown option '{argv[i]}'")
            sys.exit(1)
    return host, port


def main():
    host, port = _parse_args(sys.argv)

    sender = ColibriSender(host, port)

    feedback_event = Event()
    command_event = Event()

    # Feedback (camera -> PID): sender fires this on every rx_status.
    sender.feedback_event = feedback_event

    # Command (PID -> camera): route (axis, speed) to the existing rate commands.
    def _send_rate(axis, speed):
        if axis == "pitch":
            sender.pitch(speed)
        elif axis == "roll":
            sender.roll(speed)

    command_event.subscribe(_send_rate)

    controller = GimbalPIDController(feedback_event, command_event)

    if not sender.connect():
        sys.exit(1)

    controller.start()
    try:
        PidSenderShell(sender, controller).cmdloop()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.stop()
        sender.disconnect()


if __name__ == "__main__":
    main()
