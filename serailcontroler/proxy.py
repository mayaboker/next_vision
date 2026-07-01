#!/usr/bin/env python3
"""
Colibri Camera Proxy Server
Receives commands over ethernet and uses driver.py to communicate with hardware.
Sends RX data back to connected clients.
"""

import socket
import threading
import json
import time
import sys
import signal
from typing import Optional, Dict, Set, Any
from dataclasses import asdict

from driver import (
    ColibriDriver,
    CameraStatus,
    CameraSettings,
    ColibriProtocol,
    MessageBuilder,
    MessageParser,
    # Enums
    ColibCamModes,
    ColibCamLaserEn,
    ColibCamSensor,
    ColibCamIRPolarityMode,
    ColibCamColorPalette,
    ColibCamLaserMode,
    ColibCamZoom,
    ColibCamFreezeMode,
)


class ColibriProxy:
    """
    Proxy server that bridges network commands to Colibri camera hardware.
    
    Protocol:
    - Commands are JSON messages terminated by newline
    - Responses are JSON messages terminated by newline
    - RX data from camera is broadcast to all connected clients
    """
    
    DEFAULT_HOST = '0.0.0.0'
    DEFAULT_PORT = 12345
    
    def __init__(self, tty_device: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.tty_device = tty_device
        self.host = host
        self.port = port
        
        self.driver: Optional[ColibriDriver] = None
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        
        # Connected clients
        self.clients: Set[socket.socket] = set()
        self.clients_lock = threading.Lock()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("\n🛑 Received shutdown signal...")
        self.stop()
        sys.exit(0)
    
    def start(self):
        """Start the proxy server"""
        # Connect to hardware
        print(f"🔌 Connecting to hardware on {self.tty_device}...")
        try:
            self.driver = ColibriDriver(
                port_name=self.tty_device,
                on_rx_callback=self._on_camera_rx,
                on_tx_callback=self._on_camera_tx,
                on_raw_rx_callback=self._on_camera_raw_rx
            )
            print(f"✅ Connected to hardware")
        except Exception as e:
            print(f"❌ Failed to connect to hardware: {e}")
            return False
        
        # Start network server
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            
            self.running = True
            print(f"🌐 Proxy server listening on {self.host}:{self.port}")
            print(f"   Press Ctrl+C to stop")
            print()
            
            # Accept connections
            while self.running:
                try:
                    client_socket, client_addr = self.server_socket.accept()
                    print(f"📥 Client connected: {client_addr}")
                    
                    with self.clients_lock:
                        self.clients.add(client_socket)
                    
                    # Handle client in separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"❌ Error accepting connection: {e}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start server: {e}")
            return False
    
    def stop(self):
        """Stop the proxy server"""
        self.running = False
        
        # Close all client connections
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
            self.clients.clear()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        # Disconnect from hardware
        if self.driver:
            self.driver.disconnect()
        
        print("✅ Proxy server stopped")
    
    def _handle_client(self, client_socket: socket.socket, client_addr):
        """Handle a connected client"""
        buffer = ""
        
        try:
            client_socket.settimeout(0.5)
            
            while self.running:
                try:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    
                    buffer += data.decode('utf-8')
                    
                    # Process complete messages (newline-delimited)
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            response = self._process_command(line.strip())
                            self._send_to_client(client_socket, response)
                            
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"❌ Error receiving from {client_addr}: {e}")
                    break
                    
        finally:
            print(f"📤 Client disconnected: {client_addr}")
            with self.clients_lock:
                self.clients.discard(client_socket)
            try:
                client_socket.close()
            except:
                pass
    
    def _process_command(self, message: str) -> Dict[str, Any]:
        """Process a command message and return response"""
        try:
            cmd = json.loads(message)
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"Invalid JSON: {e}"}
        
        cmd_type = cmd.get("cmd", "").lower()
        
        # Command handlers
        handlers = {
            "ping": self._cmd_ping,
            "status": self._cmd_status,
            "start": self._cmd_start,
            "stop": self._cmd_stop,
            "send": self._cmd_send,
            "raw": self._cmd_raw,
            "mode": self._cmd_mode,
            "sensor": self._cmd_sensor,
            "laser": self._cmd_laser,
            "laser_mode": self._cmd_laser_mode,
            "zoom": self._cmd_zoom,
            "pitch": self._cmd_pitch,
            "roll": self._cmd_roll,
            "center": self._cmd_center,
            "nuc": self._cmd_nuc,
            "polarity": self._cmd_polarity,
            "palette": self._cmd_palette,
            "freeze": self._cmd_freeze,
            "move": self._cmd_move,
            "get_settings": self._cmd_get_settings,
        }
        
        handler = handlers.get(cmd_type)
        if handler:
            return handler(cmd)
        else:
            return {"status": "error", "message": f"Unknown command: {cmd_type}"}
    
    # =========================================================================
    # Command Handlers
    # =========================================================================
    
    def _cmd_ping(self, cmd: Dict) -> Dict:
        """Handle ping command"""
        return {"status": "ok", "message": "pong", "timestamp": time.time()}
    
    def _cmd_status(self, cmd: Dict) -> Dict:
        """Handle status command"""
        return {
            "status": "ok",
            "connected": self.driver.is_connected() if self.driver else False,
            "transmitting": self.driver.is_transmitting() if self.driver else False,
            "tty_device": self.tty_device
        }
    
    def _cmd_start(self, cmd: Dict) -> Dict:
        """Start transmission"""
        if self.driver:
            self.driver.start_transmission()
            return {"status": "ok", "message": "Transmission started"}
        return {"status": "error", "message": "Driver not connected"}
    
    def _cmd_stop(self, cmd: Dict) -> Dict:
        """Stop transmission"""
        if self.driver:
            self.driver.stop_transmission()
            return {"status": "ok", "message": "Transmission stopped"}
        return {"status": "error", "message": "Driver not connected"}
    
    def _cmd_send(self, cmd: Dict) -> Dict:
        """Send single command"""
        if self.driver:
            self.driver.send_command()
            return {"status": "ok", "message": "Command sent"}
        return {"status": "error", "message": "Driver not connected"}
    
    def _cmd_raw(self, cmd: Dict) -> Dict:
        """Send raw byte data"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        hex_data = cmd.get("data", "")
        if not hex_data:
            return {"status": "error", "message": "No data provided"}
        
        try:
            # Parse hex string
            hex_clean = hex_data.replace(' ', '').replace('-', '').replace(':', '')
            raw_bytes = bytearray.fromhex(hex_clean)
            
            self.driver._send_raw(raw_bytes)
            
            return {
                "status": "ok",
                "message": "Raw data sent",
                "bytes": len(raw_bytes),
                "data": MessageBuilder.format_hex(raw_bytes)
            }
        except ValueError as e:
            return {"status": "error", "message": f"Invalid hex data: {e}"}
    
    def _cmd_mode(self, cmd: Dict) -> Dict:
        """Set camera mode"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        modes = {
            'rate': ColibCamModes.RATE,
            'pilot': ColibCamModes.PILOT,
            'stow': ColibCamModes.STOW,
            'park': ColibCamModes.PARK,
            'gyro': ColibCamModes.GYRO_CALIBRATION,
            'ext': ColibCamModes.EXT
        }
        
        mode = cmd.get("value", "").lower()
        if mode not in modes:
            return {"status": "error", "message": f"Invalid mode. Options: {list(modes.keys())}"}
        
        self.driver.set_mode(modes[mode])
        return {"status": "ok", "message": f"Mode set to {mode}"}
    
    def _cmd_sensor(self, cmd: Dict) -> Dict:
        """Set sensor type"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        sensors = {
            'visible': ColibCamSensor.VISIBLE,
            'ir': ColibCamSensor.IR
        }
        
        sensor = cmd.get("value", "").lower()
        if sensor not in sensors:
            return {"status": "error", "message": f"Invalid sensor. Options: {list(sensors.keys())}"}
        
        self.driver.set_sensor(sensors[sensor])
        return {"status": "ok", "message": f"Sensor set to {sensor}"}
    
    def _cmd_laser(self, cmd: Dict) -> Dict:
        """Enable/disable laser"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        value = cmd.get("value", "").lower()
        if value not in ['on', 'off', 'true', 'false', '1', '0']:
            return {"status": "error", "message": "Invalid value. Options: on, off"}
        
        enabled = value in ['on', 'true', '1']
        self.driver.set_laser_enable(enabled)
        return {"status": "ok", "message": f"Laser {'enabled' if enabled else 'disabled'}"}
    
    def _cmd_laser_mode(self, cmd: Dict) -> Dict:
        """Set laser mode"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        modes = {
            'always': ColibCamLaserMode.LASER_ALWAYS_ON,
            '2hz': ColibCamLaserMode.LASER_2HZ,
            '6hz': ColibCamLaserMode.LASER_6HZ,
            '30hz': ColibCamLaserMode.LASER_30HZ
        }
        
        mode = cmd.get("value", "").lower()
        if mode not in modes:
            return {"status": "error", "message": f"Invalid laser mode. Options: {list(modes.keys())}"}
        
        self.driver.set_laser_mode(modes[mode])
        return {"status": "ok", "message": f"Laser mode set to {mode}"}
    
    def _cmd_zoom(self, cmd: Dict) -> Dict:
        """Set zoom"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        zooms = {
            'in': ColibCamZoom.ZOOM_IN,
            'out': ColibCamZoom.ZOOM_OUT,
            'stop': ColibCamZoom.NO_ZOOM
        }
        
        zoom = cmd.get("value", "").lower()
        if zoom not in zooms:
            return {"status": "error", "message": f"Invalid zoom. Options: {list(zooms.keys())}"}
        
        self.driver.set_zoom(zooms[zoom])
        return {"status": "ok", "message": f"Zoom set to {zoom}"}
    
    def _cmd_pitch(self, cmd: Dict) -> Dict:
        """Set pitch value"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        try:
            value = int(cmd.get("value", ColibriProtocol.RATE_MIDDLE_VAL))
            self.driver.set_pitch(value)
            return {"status": "ok", "message": f"Pitch set to {self.driver.settings.gimbal_pitch_value}"}
        except (ValueError, TypeError):
            return {"status": "error", "message": "Invalid pitch value"}
    
    def _cmd_roll(self, cmd: Dict) -> Dict:
        """Set roll value"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        try:
            value = int(cmd.get("value", ColibriProtocol.RATE_MIDDLE_VAL))
            self.driver.set_roll(value)
            return {"status": "ok", "message": f"Roll set to {self.driver.settings.gimbal_roll_value}"}
        except (ValueError, TypeError):
            return {"status": "error", "message": "Invalid roll value"}
    
    def _cmd_center(self, cmd: Dict) -> Dict:
        """Center pitch and roll"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        self.driver.set_pitch(ColibriProtocol.RATE_MIDDLE_VAL)
        self.driver.set_roll(ColibriProtocol.RATE_MIDDLE_VAL)
        return {"status": "ok", "message": "Pitch and roll centered"}
    
    def _cmd_nuc(self, cmd: Dict) -> Dict:
        """Toggle NUC"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        self.driver.toggle_nuc()
        return {"status": "ok", "message": f"NUC toggled (value: 0x{self.driver.settings.nuc_value:02X})"}
    
    def _cmd_polarity(self, cmd: Dict) -> Dict:
        """Set IR polarity"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        polarities = {
            'white': ColibCamIRPolarityMode.WHITE_HOT,
            'black': ColibCamIRPolarityMode.BLACK_HOT
        }
        
        polarity = cmd.get("value", "").lower()
        if polarity not in polarities:
            return {"status": "error", "message": f"Invalid polarity. Options: {list(polarities.keys())}"}
        
        self.driver.set_ir_polarity(polarities[polarity])
        return {"status": "ok", "message": f"IR polarity set to {polarity} hot"}
    
    def _cmd_palette(self, cmd: Dict) -> Dict:
        """Set color palette"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        palettes = {
            'grey': ColibCamColorPalette.GREY,
            'color1': ColibCamColorPalette.COLOR1,
            'color2': ColibCamColorPalette.COLOR2,
            'color3': ColibCamColorPalette.COLOR3
        }
        
        palette = cmd.get("value", "").lower()
        if palette not in palettes:
            return {"status": "error", "message": f"Invalid palette. Options: {list(palettes.keys())}"}
        
        self.driver.set_color_palette(palettes[palette])
        return {"status": "ok", "message": f"Color palette set to {palette}"}
    
    def _cmd_freeze(self, cmd: Dict) -> Dict:
        """Set freeze mode"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        value = cmd.get("value", "").lower()
        if value not in ['on', 'off', 'true', 'false', '1', '0']:
            return {"status": "error", "message": "Invalid value. Options: on, off"}
        
        enabled = value in ['on', 'true', '1']
        self.driver.set_freeze(enabled)
        return {"status": "ok", "message": f"Freeze {'enabled' if enabled else 'disabled'}"}
    
    def _cmd_move(self, cmd: Dict) -> Dict:
        """Move gimbal - convenience command"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        direction = cmd.get("direction", "").lower()
        amount = int(cmd.get("amount", 100))
        
        current_pitch = self.driver.settings.gimbal_pitch_value
        current_roll = self.driver.settings.gimbal_roll_value
        
        if direction == "up":
            self.driver.set_pitch(current_pitch + amount)
        elif direction == "down":
            self.driver.set_pitch(current_pitch - amount)
        elif direction == "left":
            self.driver.set_roll(current_roll - amount)
        elif direction == "right":
            self.driver.set_roll(current_roll + amount)
        else:
            return {"status": "error", "message": "Invalid direction. Options: up, down, left, right"}
        
        return {
            "status": "ok",
            "message": f"Moved {direction} by {amount}",
            "pitch": self.driver.settings.gimbal_pitch_value,
            "roll": self.driver.settings.gimbal_roll_value
        }
    
    def _cmd_get_settings(self, cmd: Dict) -> Dict:
        """Get current settings"""
        if not self.driver:
            return {"status": "error", "message": "Driver not connected"}
        
        s = self.driver.settings
        return {
            "status": "ok",
            "settings": {
                "cam_mode": s.cam_mode.name,
                "sensor": s.sensor.name,
                "laser_enable": s.laser_enable.name,
                "laser_mode": s.laser_mode.name,
                "zoom_state": s.zoom_state.name,
                "gimbal_pitch_value": s.gimbal_pitch_value,
                "gimbal_roll_value": s.gimbal_roll_value,
                "ir_polarity_mode": s.ir_polarity_mode.name,
                "color_palette": s.color_palette.name,
                "nuc_value": s.nuc_value,
                "freeze_mode": s.freeze_mode.name,
            },
            "transmitting": self.driver.is_transmitting()
        }
    
    # =========================================================================
    # Camera Callbacks
    # =========================================================================
    
    def _on_camera_tx(self, data: bytes):
        """Called when data is sent to camera"""
        # Broadcast TX to all clients
        msg = {
            "type": "tx",
            "data": MessageBuilder.format_hex(data),
            "timestamp": time.time()
        }
        self._broadcast(msg)
    
    def _on_camera_raw_rx(self, data: bytes):
        """Called when raw data received from camera"""
        # Broadcast raw RX to all clients
        msg = {
            "type": "rx_raw",
            "data": MessageParser.format_hex(data),
            "timestamp": time.time()
        }
        self._broadcast(msg)
    
    def _on_camera_rx(self, status: CameraStatus):
        """Called when parsed status received from camera"""
        # Broadcast parsed status to all clients
        msg = {
            "type": "rx_status",
            "status": {
                "mode": status.mode,
                "sensor": status.sensor,
                "total_pitch_deg": status.total_pitch_deg,
                "total_roll_deg": status.total_roll_deg,
                "mech_pitch_deg": status.mech_pitch_deg,
                "mech_roll_deg": status.mech_roll_deg,
                "elec_pitch_deg": status.elec_pitch_deg,
                "elec_roll_deg": status.elec_roll_deg,
                "hfov_deg": status.hfov_deg,
                "vfov_deg": status.vfov_deg,
            },
            "timestamp": time.time()
        }
        self._broadcast(msg)
    
    def _broadcast(self, msg: Dict):
        """Broadcast message to all connected clients"""
        data = (json.dumps(msg) + '\n').encode('utf-8')
        
        with self.clients_lock:
            dead_clients = set()
            for client in self.clients:
                try:
                    client.sendall(data)
                except:
                    dead_clients.add(client)
            
            # Remove dead clients
            for client in dead_clients:
                self.clients.discard(client)
    
    def _send_to_client(self, client: socket.socket, msg: Dict):
        """Send message to specific client"""
        try:
            data = (json.dumps(msg) + '\n').encode('utf-8')
            client.sendall(data)
        except Exception as e:
            print(f"❌ Error sending to client: {e}")


def print_usage():
    """Print usage information"""
    print("Colibri Camera Proxy Server")
    print("=" * 50)
    print("Usage: python proxy.py <tty_device> [options]")
    print()
    print("Arguments:")
    print("  tty_device    - Serial device (e.g., /dev/ttyUSB0)")
    print()
    print("Options:")
    print("  --host <ip>   - Listen address (default: 0.0.0.0)")
    print("  --port <port> - Listen port (default: 12345)")
    print()
    print("Examples:")
    print("  python proxy.py /dev/ttyUSB0")
    print("  python proxy.py /dev/ttyUSB0 --port 5000")
    print("  python proxy.py /dev/ttyUSB0 --host 192.168.1.100 --port 5000")


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    tty_device = sys.argv[1]
    host = ColibriProxy.DEFAULT_HOST
    port = ColibriProxy.DEFAULT_PORT
    
    # Parse options
    i = 2
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
        else:
            print(f"❌ Error: Unknown option '{sys.argv[i]}'")
            sys.exit(1)
    
    # Create and start proxy
    proxy = ColibriProxy(tty_device, host, port)
    
    if not proxy.start():
        sys.exit(1)


if __name__ == "__main__":
    main()
