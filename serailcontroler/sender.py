#!/usr/bin/env python3
"""
Colibri Camera Sender Client
Sends commands over ethernet to proxy.py and receives RX data back.
Can run on same machine or over the network.
"""

import socket
import threading
import json
import time
import sys
import signal
import cmd
from typing import Optional, Dict, Any


class ColibriSender:
    """
    Network client for sending commands to Colibri proxy server.
    Receives and displays RX data from the camera.
    """
    
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_PORT = 12345
    
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.receive_thread: Optional[threading.Thread] = None
        
        # Display options
        self.show_tx = True
        self.show_rx_raw = True
        self.show_rx_status = True
        self.verbose = False

        # Optional control2 hook: fired with (pitch_deg, roll_deg) on every
        # rx_status so an external PID controller can consume feedback.
        self.feedback_event = None
    
    def connect(self) -> bool:
        """Connect to proxy server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(0.5)
            
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            print(f"✅ Connected to proxy at {self.host}:{self.port}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect to {self.host}:{self.port}: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from proxy server"""
        self.running = False
        
        if self.receive_thread:
            self.receive_thread.join(timeout=1.0)
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        print("Disconnected from proxy")
    
    def _receive_loop(self):
        """Background thread for receiving data from proxy"""
        buffer = ""
        
        while self.running:
            try:
                data = self.socket.recv(4096)
                if not data:
                    print("\n❌ Connection closed by server")
                    self.running = False
                    break
                
                buffer += data.decode('utf-8')
                
                # Process complete messages
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self._handle_message(json.loads(line))
                        
            except socket.timeout:
                continue
            except json.JSONDecodeError as e:
                if self.verbose:
                    print(f"⚠️  Invalid JSON received: {e}")
            except Exception as e:
                if self.running:
                    print(f"❌ Receive error: {e}")
                break
    
    def _handle_message(self, msg: Dict):
        """Handle received message from proxy"""
        msg_type = msg.get("type", "")
        
        if msg_type == "tx":
            if self.show_tx:
                print(f"📤 TX: {msg.get('data', '')}")
                
        elif msg_type == "rx_raw":
            if self.show_rx_raw:
                print(f"📥 RX: {msg.get('data', '')}")
                
        elif msg_type == "rx_status":
            status = msg.get("status", {})

            # Feed the latest measured angles to any subscribed controller,
            # independent of the display toggle.
            if self.feedback_event is not None:
                self.feedback_event.fire(
                    status.get("total_pitch_deg", 0.0),
                    status.get("total_roll_deg", 0.0),
                )

            if self.show_rx_status:
                print(f"📊 Camera Status:")
                print(f"   Mode: {status.get('mode')}, Sensor: {status.get('sensor')}")
                print(f"   Pitch - Total: {status.get('total_pitch_deg', 0):.2f}°, "
                      f"Mech: {status.get('mech_pitch_deg', 0):.2f}°, "
                      f"Elec: {status.get('elec_pitch_deg', 0):.2f}°")
                print(f"   Roll  - Total: {status.get('total_roll_deg', 0):.2f}°, "
                      f"Mech: {status.get('mech_roll_deg', 0):.2f}°, "
                      f"Elec: {status.get('elec_roll_deg', 0):.2f}°")
                print(f"   FOV   - H: {status.get('hfov_deg', 0):.2f}°, "
                      f"V: {status.get('vfov_deg', 0):.2f}°")
        else:
            # Command response
            if self.verbose or msg.get("status") == "error":
                print(f"📨 Response: {json.dumps(msg, indent=2)}")
            elif "message" in msg:
                status_icon = "✅" if msg.get("status") == "ok" else "❌"
                print(f"{status_icon} {msg.get('message', '')}")
    
    def send_command(self, cmd: Dict) -> bool:
        """Send a command to the proxy"""
        if not self.socket:
            print("❌ Not connected")
            return False
        
        try:
            data = (json.dumps(cmd) + '\n').encode('utf-8')
            if self.verbose:
                print(f"data to sendall = {data}")
            self.socket.sendall(data)
            return True
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False
    
    # =========================================================================
    # Convenience methods for common commands
    # =========================================================================
    
    def ping(self):
        """Send ping command"""
        return self.send_command({"cmd": "ping"})
    
    def status(self):
        """Get proxy status"""
        return self.send_command({"cmd": "status"})
    
    def start(self):
        """Start transmission"""
        return self.send_command({"cmd": "start"})
    
    def stop(self):
        """Stop transmission"""
        return self.send_command({"cmd": "stop"})
    
    def send(self):
        """Send single command"""
        return self.send_command({"cmd": "send"})
    
    def raw(self, hex_data: str):
        """Send raw hex data"""
        return self.send_command({"cmd": "raw", "data": hex_data})
    
    def mode(self, value: str):
        """Set camera mode"""
        return self.send_command({"cmd": "mode", "value": value})
    
    def sensor(self, value: str):
        """Set sensor type"""
        return self.send_command({"cmd": "sensor", "value": value})
    
    def laser(self, value: str):
        """Set laser on/off"""
        return self.send_command({"cmd": "laser", "value": value})
    
    def laser_mode(self, value: str):
        """Set laser mode"""
        return self.send_command({"cmd": "laser_mode", "value": value})
    
    def zoom(self, value: str):
        """Set zoom"""
        return self.send_command({"cmd": "zoom", "value": value})
    
    def pitch(self, value: int):
        """Set pitch value"""
        return self.send_command({"cmd": "pitch", "value": value})
    
    def roll(self, value: int):
        """Set roll value"""
        return self.send_command({"cmd": "roll", "value": value})
    
    def center(self):
        """Center gimbal"""
        return self.send_command({"cmd": "center"})
    
    def nuc(self):
        """Toggle NUC"""
        return self.send_command({"cmd": "nuc"})
    
    def polarity(self, value: str):
        """Set IR polarity"""
        return self.send_command({"cmd": "polarity", "value": value})
    
    def palette(self, value: str):
        """Set color palette"""
        return self.send_command({"cmd": "palette", "value": value})
    
    def freeze(self, value: str):
        """Set freeze mode"""
        return self.send_command({"cmd": "freeze", "value": value})
    
    def move(self, direction: str, amount: int = 100):
        """Move gimbal"""
        return self.send_command({"cmd": "move", "direction": direction, "amount": amount})
    
    def get_settings(self):
        """Get current settings"""
        return self.send_command({"cmd": "get_settings"})


class SenderShell(cmd.Cmd):
    """Interactive command shell for Colibri sender"""
    
    intro = """
╔═══════════════════════════════════════════════════════════════╗
║           Colibri Camera Sender - Network Client              ║
║                                                               ║
║  Type 'help' or '?' to list commands                          ║
║  Type 'start' to begin transmission                           ║
║  Type 'quit' or 'exit' to close                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    prompt = 'sender> '
    
    def __init__(self, sender: ColibriSender):
        super().__init__()
        self.sender = sender
    
    # =========================================================================
    # Transmission Control
    # =========================================================================
    
    def do_ping(self, line):
        """Ping the proxy server"""
        self.sender.ping()
    
    def do_status(self, line):
        """Get proxy status"""
        self.sender.status()
    
    def do_start(self, line):
        """Start transmission to camera"""
        self.sender.start()
    
    def do_stop(self, line):
        """Stop transmission to camera"""
        self.sender.stop()
    
    def do_send(self, line):
        """Send a single command"""
        self.sender.send()
    
    def do_raw(self, line):
        """Send raw hex data: raw <hex_bytes>
        Example: raw B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49"""
        if not line:
            print("Usage: raw <hex_bytes>")
            return
        self.sender.raw(line)
    
    # =========================================================================
    # Camera Mode Commands
    # =========================================================================
    
    def do_mode(self, line):
        """Set camera mode: mode <rate|pilot|stow|park|gyro|ext>"""
        if not line:
            print("Usage: mode <rate|pilot|stow|park|gyro|ext>")
            return
        self.sender.mode(line)
    
    def do_sensor(self, line):
        """Set camera sensor: sensor <visible|ir>"""
        if not line:
            print("Usage: sensor <visible|ir>")
            return
        self.sender.sensor(line)
    
    # =========================================================================
    # Laser Commands
    # =========================================================================
    
    def do_laser(self, line):
        """Set laser state: laser <on|off>"""
        if not line:
            print("Usage: laser <on|off>")
            return
        self.sender.laser(line)
    
    def do_laser_mode(self, line):
        """Set laser mode: laser_mode <always|2hz|6hz|30hz>"""
        if not line:
            print("Usage: laser_mode <always|2hz|6hz|30hz>")
            return
        self.sender.laser_mode(line)
    
    # =========================================================================
    # Gimbal Control
    # =========================================================================
    
    def do_zoom(self, line):
        """Set zoom: zoom <in|out|stop>"""
        if not line:
            print("Usage: zoom <in|out|stop>")
            return
        self.sender.zoom(line)
    
    def do_pitch(self, line):
        """Set pitch value: pitch <0-4095>"""
        try:
            value = int(line)
            self.sender.pitch(value)
        except ValueError:
            print("Usage: pitch <0-4095>")
    
    def do_roll(self, line):
        """Set roll value: roll <0-4095>"""
        try:
            value = int(line)
            self.sender.roll(value)
        except ValueError:
            print("Usage: roll <0-4095>")
    
    def do_center(self, line):
        """Center gimbal"""
        self.sender.center()
    
    def do_up(self, line):
        """Move gimbal up: up [amount]"""
        amount = int(line) if line else 100
        self.sender.move("up", amount)
    
    def do_down(self, line):
        """Move gimbal down: down [amount]"""
        amount = int(line) if line else 100
        self.sender.move("down", amount)
    
    def do_left(self, line):
        """Move gimbal left: left [amount]"""
        amount = int(line) if line else 100
        self.sender.move("left", amount)
    
    def do_right(self, line):
        """Move gimbal right: right [amount]"""
        amount = int(line) if line else 100
        self.sender.move("right", amount)
    
    # =========================================================================
    # Image Settings
    # =========================================================================
    
    def do_nuc(self, line):
        """Toggle NUC"""
        self.sender.nuc()
    
    def do_polarity(self, line):
        """Set IR polarity: polarity <white|black>"""
        if not line:
            print("Usage: polarity <white|black>")
            return
        self.sender.polarity(line)
    
    def do_palette(self, line):
        """Set color palette: palette <grey|color1|color2|color3>"""
        if not line:
            print("Usage: palette <grey|color1|color2|color3>")
            return
        self.sender.palette(line)
    
    def do_freeze(self, line):
        """Set freeze mode: freeze <on|off>"""
        if not line:
            print("Usage: freeze <on|off>")
            return
        self.sender.freeze(line)
    
    # =========================================================================
    # Display Control
    # =========================================================================
    
    def do_show_tx(self, line):
        """Toggle TX display: show_tx <on|off>"""
        if line.lower() in ['on', '1', 'true']:
            self.sender.show_tx = True
            print("✅ TX display enabled")
        elif line.lower() in ['off', '0', 'false']:
            self.sender.show_tx = False
            print("✅ TX display disabled")
        else:
            print(f"TX display: {'ON' if self.sender.show_tx else 'OFF'}")
    
    def do_show_rx(self, line):
        """Toggle raw RX display: show_rx <on|off>"""
        if line.lower() in ['on', '1', 'true']:
            self.sender.show_rx_raw = True
            print("✅ Raw RX display enabled")
        elif line.lower() in ['off', '0', 'false']:
            self.sender.show_rx_raw = False
            print("✅ Raw RX display disabled")
        else:
            print(f"Raw RX display: {'ON' if self.sender.show_rx_raw else 'OFF'}")
    
    def do_show_status(self, line):
        """Toggle parsed status display: show_status <on|off>"""
        if line.lower() in ['on', '1', 'true']:
            self.sender.show_rx_status = True
            print("✅ Status display enabled")
        elif line.lower() in ['off', '0', 'false']:
            self.sender.show_rx_status = False
            print("✅ Status display disabled")
        else:
            print(f"Status display: {'ON' if self.sender.show_rx_status else 'OFF'}")
    
    def do_verbose(self, line):
        """Toggle verbose mode: verbose <on|off>"""
        if line.lower() in ['on', '1', 'true']:
            self.sender.verbose = True
            print("✅ Verbose mode enabled")
        elif line.lower() in ['off', '0', 'false']:
            self.sender.verbose = False
            print("✅ Verbose mode disabled")
        else:
            print(f"Verbose: {'ON' if self.sender.verbose else 'OFF'}")
    
    def do_quiet(self, line):
        """Disable all RX display"""
        self.sender.show_tx = False
        self.sender.show_rx_raw = False
        self.sender.show_rx_status = False
        print("✅ All displays disabled")
    
    def do_loud(self, line):
        """Enable all RX display"""
        self.sender.show_tx = True
        self.sender.show_rx_raw = True
        self.sender.show_rx_status = True
        print("✅ All displays enabled")
    
    # =========================================================================
    # Info Commands
    # =========================================================================
    
    def do_settings(self, line):
        """Get current camera settings from proxy"""
        self.sender.get_settings()
    
    def do_help_all(self, line):
        """Show all available commands"""
        print("""
┌─────────────────────────────────────────────────────────────┐
│                    Available Commands                        │
├─────────────────────────────────────────────────────────────┤
│ CONNECTION:                                                  │
│   ping         - Ping proxy server                          │
│   status       - Get proxy status                           │
│   settings     - Get current camera settings                │
│                                                              │
│ TRANSMISSION:                                                │
│   start        - Start transmission (25Hz)                   │
│   stop         - Stop transmission                           │
│   send         - Send single command                         │
│   raw          - Send raw hex bytes                          │
│                                                              │
│ CAMERA MODE:                                                 │
│   mode         - Set mode (rate|pilot|stow|park|gyro|ext)   │
│   sensor       - Set sensor (visible|ir)                     │
│                                                              │
│ LASER:                                                       │
│   laser        - Enable/disable laser (on|off)               │
│   laser_mode   - Set laser mode (always|2hz|6hz|30hz)       │
│                                                              │
│ GIMBAL:                                                      │
│   pitch        - Set pitch (0-4095)                         │
│   roll         - Set roll (0-4095)                          │
│   zoom         - Set zoom (in|out|stop)                     │
│   center       - Center pitch and roll                       │
│   up/down      - Move gimbal up/down [amount]               │
│   left/right   - Move gimbal left/right [amount]            │
│                                                              │
│ IMAGE:                                                       │
│   nuc          - Toggle NUC                                  │
│   polarity     - Set IR polarity (white|black)              │
│   palette      - Set palette (grey|color1|color2|color3)    │
│   freeze       - Freeze image (on|off)                       │
│                                                              │
│ DISPLAY:                                                     │
│   show_tx      - Toggle TX display (on|off)                 │
│   show_rx      - Toggle raw RX display (on|off)             │
│   show_status  - Toggle parsed status display (on|off)      │
│   verbose      - Toggle verbose JSON responses (on|off)     │
│   quiet        - Disable all displays                        │
│   loud         - Enable all displays                         │
│                                                              │
│ SYSTEM:                                                      │
│   quit/exit    - Exit application                            │
│   help         - Show command help                           │
│   help_all     - Show this command reference                 │
└─────────────────────────────────────────────────────────────┘
""")
    
    # =========================================================================
    # Exit Commands
    # =========================================================================
    
    def do_quit(self, line):
        """Exit the application"""
        print("Shutting down...")
        self.sender.disconnect()
        return True
    
    def do_exit(self, line):
        """Exit the application"""
        return self.do_quit(line)
    
    def do_EOF(self, line):
        """Handle Ctrl+D"""
        print()
        return self.do_quit(line)


def send_single_command(host: str, port: int, cmd: Dict) -> bool:
    """Send a single command and wait for response (non-interactive mode)"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.settimeout(5.0)
        
        # Send command
        data = (json.dumps(cmd) + '\n').encode('utf-8')
        print(f"sent data = {data} {host} {port}")
        sock.sendall(data)
        
        # Wait for response
        buffer = ""
        while '\n' not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk.decode('utf-8')
        
        if buffer:
            response = json.loads(buffer.split('\n')[0])
            print(json.dumps(response, indent=2))
            return response.get("status") == "ok"
        
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        sock.close()


def print_usage():
    """Print usage information"""
    print("Colibri Camera Sender Client")
    print("=" * 50)
    print("Usage:")
    print("  Interactive mode:")
    print("    python sender.py [options]")
    print()
    print("  Single command mode:")
    print("    python sender.py [options] --cmd <command> [--value <value>]")
    print()
    print("Options:")
    print("  --host <ip>     - Proxy address (default: 127.0.0.1)")
    print("  --port <port>   - Proxy port (default: 12345)")
    print("  --cmd <command> - Send single command and exit")
    print("  --value <value> - Value for command (if required)")
    print("  --data <hex>    - Hex data for raw command")
    print()
    print("Examples:")
    print("  # Interactive mode")
    print("  python sender.py")
    print("  python sender.py --host 192.168.1.100 --port 5000")
    print()
    print("  # Single commands")
    print("  python sender.py --cmd ping")
    print("  python sender.py --cmd start")
    print("  python sender.py --cmd mode --value rate")
    print("  python sender.py --cmd zoom --value in")
    print("  python sender.py --cmd raw --data 'B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49'")
    print()
    print("Available commands:")
    print("  ping, status, start, stop, send, raw, mode, sensor, laser,")
    print("  laser_mode, zoom, pitch, roll, center, nuc, polarity, palette,")
    print("  freeze, move, get_settings")


def main():
    """Main entry point"""
    host = ColibriSender.DEFAULT_HOST
    port = ColibriSender.DEFAULT_PORT
    single_cmd = None
    single_value = None
    single_data = None
    
    # Parse options
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--host' and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--port' and i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
                i += 2
            except ValueError:
                print(f"❌ Error: Invalid port '{sys.argv[i + 1]}'")
                sys.exit(1)
        elif sys.argv[i] == '--cmd' and i + 1 < len(sys.argv):
            single_cmd = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--value' and i + 1 < len(sys.argv):
            single_value = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--data' and i + 1 < len(sys.argv):
            single_data = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] in ['--help', '-h']:
            print_usage()
            sys.exit(0)
        else:
            print(f"❌ Error: Unknown option '{sys.argv[i]}'")
            print_usage()
            sys.exit(1)
    
    # Single command mode
    if single_cmd:
        cmd = {"cmd": single_cmd}
        if single_value:
            cmd["value"] = single_value
        if single_data:
            cmd["data"] = single_data
        
        success = send_single_command(host, port, cmd)
        sys.exit(0 if success else 1)
    
    # Interactive mode
    sender = ColibriSender(host, port)
    
    if not sender.connect():
        sys.exit(1)
    
    try:
        shell = SenderShell(sender)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        sender.disconnect()


if __name__ == "__main__":
    main()
