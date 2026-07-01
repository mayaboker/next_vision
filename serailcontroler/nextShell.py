#!/usr/bin/env python3
"""
Colibri Camera Controller Shell - Interactive command interface
Uses driver.py for all serial communication and protocol handling
"""

import cmd
import sys
from typing import Optional

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
    ColibCamRateCalculationMode,
    ColibCamFreezeMode,
    ColibCamTextOSDMode,
    ColibCamGraphicsOSDMode,
)


class ColibriShell(cmd.Cmd):
    """Interactive command shell for Colibri camera control"""
    
    intro = """
╔═══════════════════════════════════════════════════════════════╗
║           Colibri Camera Controller - Interactive Shell       ║
║                                                               ║
║  Type 'help' or '?' to list commands                          ║
║  Type 'start' to begin transmission                           ║
║  Type 'status' to view current settings                       ║
║  Type 'quit' or 'exit' to close                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    prompt = 'colibri> '
    
    def __init__(self, port_name: str):
        super().__init__()
        self.driver: Optional[ColibriDriver] = None
        self.port_name = port_name
        self.verbose_rx = True  # Show parsed RX data
        self.show_raw = True    # Show raw hex TX/RX
        
        self._connect()
    
    def _connect(self):
        """Connect to the camera"""
        try:
            self.driver = ColibriDriver(
                port_name=self.port_name,
                on_rx_callback=self._on_rx_parsed,
                on_tx_callback=self._on_tx,
                on_raw_rx_callback=self._on_rx_raw
            )
            print(f"✓ Connected to {self.port_name}")
        except Exception as e:
            print(f"✗ Failed to connect: {e}")
            raise
    
    def _on_tx(self, data: bytes):
        """Callback when message is transmitted"""
        if self.show_raw:
            hex_str = MessageBuilder.format_hex(data)
            print(f"TX: {hex_str}")
    
    def _on_rx_raw(self, data: bytes):
        """Callback when raw packet is received"""
        if self.show_raw:
            hex_str = MessageParser.format_hex(data)
            print(f"RX: {hex_str}")
    
    def _on_rx_parsed(self, status: CameraStatus):
        """Callback when parsed status is available"""
        if self.verbose_rx:
            print(f"Camera Status:")
            print(f"  Mode: {status.mode}, Sensor: {status.sensor}")
            print(f"  Pitch - Total: {status.total_pitch_deg:.2f}°, "
                  f"Mech: {status.mech_pitch_deg:.2f}°, Elec: {status.elec_pitch_deg:.2f}°")
            print(f"  Roll  - Total: {status.total_roll_deg:.2f}°, "
                  f"Mech: {status.mech_roll_deg:.2f}°, Elec: {status.elec_roll_deg:.2f}°")
            print(f"  FOV   - H: {status.hfov_deg:.2f}°, V: {status.vfov_deg:.2f}°")
    
    # =========================================================================
    # Transmission Control Commands
    # =========================================================================
    
    def do_start(self, line):
        """Start transmission to camera (25Hz)"""
        if self.driver:
            self.driver.start_transmission()
            print("✓ Started transmission (25Hz)")
    
    def do_stop(self, line):
        """Stop transmission to camera"""
        if self.driver:
            self.driver.stop_transmission()
            print("✓ Stopped transmission")
    
    def do_send(self, line):
        """Send a single command (useful when transmission is stopped)"""
        if self.driver:
            self.driver.send_command()
            print("✓ Sent single command")
    
    # =========================================================================
    # Camera Mode Commands
    # =========================================================================
    
    def do_mode(self, line):
        """Set camera mode: mode <rate|pilot|stow|park|gyro|ext>"""
        modes = {
            'rate': ColibCamModes.RATE,
            'pilot': ColibCamModes.PILOT,
            'stow': ColibCamModes.STOW,
            'park': ColibCamModes.PARK,
            'gyro': ColibCamModes.GYRO_CALIBRATION,
            'ext': ColibCamModes.EXT
        }
        
        if not line or line.lower() not in modes:
            print(f"Usage: mode <{' | '.join(modes.keys())}>")
            print(f"Current: {self.driver.settings.cam_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_mode(modes[line.lower()])
            print(f"✓ Mode set to: {line.upper()}")
    
    def do_sensor(self, line):
        """Set camera sensor: sensor <visible|ir>"""
        sensors = {
            'visible': ColibCamSensor.VISIBLE,
            'ir': ColibCamSensor.IR
        }
        
        if not line or line.lower() not in sensors:
            print(f"Usage: sensor <{' | '.join(sensors.keys())}>")
            print(f"Current: {self.driver.settings.sensor.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_sensor(sensors[line.lower()])
            print(f"✓ Sensor set to: {line.upper()}")
    
    # =========================================================================
    # Laser Commands
    # =========================================================================
    
    def do_laser(self, line):
        """Set laser state: laser <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: laser <on | off>")
            print(f"Current: {self.driver.settings.laser_enable.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_laser_enable(states[line.lower()])
            print(f"✓ Laser set to: {line.upper()}")
    
    def do_laser_mode(self, line):
        """Set laser mode: laser_mode <always|2hz|6hz|30hz>"""
        modes = {
            'always': ColibCamLaserMode.LASER_ALWAYS_ON,
            '2hz': ColibCamLaserMode.LASER_2HZ,
            '6hz': ColibCamLaserMode.LASER_6HZ,
            '30hz': ColibCamLaserMode.LASER_30HZ
        }
        
        if not line or line.lower() not in modes:
            print(f"Usage: laser_mode <{' | '.join(modes.keys())}>")
            print(f"Current: {self.driver.settings.laser_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_laser_mode(modes[line.lower()])
            print(f"✓ Laser mode set to: {line.upper()}")
    
    # =========================================================================
    # Gimbal Control Commands
    # =========================================================================
    
    def do_zoom(self, line):
        """Set zoom: zoom <in|out|stop>"""
        zooms = {
            'in': ColibCamZoom.ZOOM_IN,
            'out': ColibCamZoom.ZOOM_OUT,
            'stop': ColibCamZoom.NO_ZOOM
        }
        
        if not line or line.lower() not in zooms:
            print(f"Usage: zoom <{' | '.join(zooms.keys())}>")
            print(f"Current: {self.driver.settings.zoom_state.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_zoom(zooms[line.lower()])
            print(f"✓ Zoom set to: {line.upper()}")
    
    def do_pitch(self, line):
        """Set pitch value: pitch <0-4095> (2048 = center)"""
        try:
            value = int(line)
            if self.driver:
                self.driver.set_pitch(value)
                print(f"✓ Pitch set to: {self.driver.settings.gimbal_pitch_value}")
        except ValueError:
            print(f"Usage: pitch <0-4095>")
            print(f"Current: {self.driver.settings.gimbal_pitch_value if self.driver else 'N/A'}")
    
    def do_roll(self, line):
        """Set roll value: roll <0-4095> (2048 = center)"""
        try:
            value = int(line)
            if self.driver:
                self.driver.set_roll(value)
                print(f"✓ Roll set to: {self.driver.settings.gimbal_roll_value}")
        except ValueError:
            print(f"Usage: roll <0-4095>")
            print(f"Current: {self.driver.settings.gimbal_roll_value if self.driver else 'N/A'}")
    
    def do_center(self, line):
        """Center both pitch and roll (set to 2048)"""
        if self.driver:
            self.driver.set_pitch(ColibriProtocol.RATE_MIDDLE_VAL)
            self.driver.set_roll(ColibriProtocol.RATE_MIDDLE_VAL)
            print("✓ Pitch and Roll centered (2048)")
    
    # =========================================================================
    # IR/Image Commands
    # =========================================================================
    
    def do_nuc(self, line):
        """Toggle NUC (Non-Uniformity Correction)"""
        if self.driver:
            self.driver.toggle_nuc()
            print(f"✓ NUC toggled (value: 0x{self.driver.settings.nuc_value:02X})")
    
    def do_polarity(self, line):
        """Set IR polarity: polarity <white|black>"""
        polarities = {
            'white': ColibCamIRPolarityMode.WHITE_HOT,
            'black': ColibCamIRPolarityMode.BLACK_HOT
        }
        
        if not line or line.lower() not in polarities:
            print(f"Usage: polarity <white | black>")
            print(f"Current: {self.driver.settings.ir_polarity_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_ir_polarity(polarities[line.lower()])
            print(f"✓ IR polarity set to: {line.upper()} HOT")
    
    def do_palette(self, line):
        """Set color palette: palette <grey|color1|color2|color3>"""
        palettes = {
            'grey': ColibCamColorPalette.GREY,
            'color1': ColibCamColorPalette.COLOR1,
            'color2': ColibCamColorPalette.COLOR2,
            'color3': ColibCamColorPalette.COLOR3
        }
        
        if not line or line.lower() not in palettes:
            print(f"Usage: palette <{' | '.join(palettes.keys())}>")
            print(f"Current: {self.driver.settings.color_palette.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_color_palette(palettes[line.lower()])
            print(f"✓ Color palette set to: {line.upper()}")
    
    def do_freeze(self, line):
        """Set freeze mode: freeze <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: freeze <on | off>")
            print(f"Current: {self.driver.settings.freeze_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_freeze(states[line.lower()])
            print(f"✓ Freeze set to: {line.upper()}")
    
    # =========================================================================
    # OSD Commands
    # =========================================================================
    
    def do_text_osd(self, line):
        """Set text OSD: text_osd <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: text_osd <on | off>")
            print(f"Current: {self.driver.settings.text_osd_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_text_osd(states[line.lower()])
            print(f"✓ Text OSD set to: {line.upper()}")
    
    def do_graphics_osd(self, line):
        """Set graphics OSD: graphics_osd <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: graphics_osd <on | off>")
            print(f"Current: {self.driver.settings.graphics_osd_mode.name if self.driver else 'N/A'}")
            return
        
        if self.driver:
            self.driver.set_graphics_osd(states[line.lower()])
            print(f"✓ Graphics OSD set to: {line.upper()}")
    
    # =========================================================================
    # Display Control Commands
    # =========================================================================
    
    def do_verbose(self, line):
        """Toggle verbose RX display (parsed camera status): verbose <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: verbose <on | off>")
            print(f"Current: {'ON' if self.verbose_rx else 'OFF'}")
            return
        
        self.verbose_rx = states[line.lower()]
        print(f"✓ Verbose RX display: {'ON' if self.verbose_rx else 'OFF'}")
    
    def do_raw(self, line):
        """Toggle raw hex TX/RX display: raw <on|off>"""
        states = {'on': True, 'off': False}
        
        if not line or line.lower() not in states:
            print(f"Usage: raw <on | off>")
            print(f"Current: {'ON' if self.show_raw else 'OFF'}")
            return
        
        self.show_raw = states[line.lower()]
        print(f"✓ Raw hex display: {'ON' if self.show_raw else 'OFF'}")
    
    # =========================================================================
    # Status and Info Commands
    # =========================================================================
    
    def do_status(self, line):
        """Show current camera settings"""
        if not self.driver:
            print("Not connected")
            return
        
        s = self.driver.settings
        print("┌─────────────────────────────────────────┐")
        print("│          Current Camera Settings        │")
        print("├─────────────────────────────────────────┤")
        print(f"│  Mode:           {s.cam_mode.name:<22}│")
        print(f"│  Sensor:         {s.sensor.name:<22}│")
        print(f"│  Laser:          {s.laser_enable.name:<22}│")
        print(f"│  Laser Mode:     {s.laser_mode.name:<22}│")
        print(f"│  Zoom:           {s.zoom_state.name:<22}│")
        print(f"│  Pitch:          {s.gimbal_pitch_value:<22}│")
        print(f"│  Roll:           {s.gimbal_roll_value:<22}│")
        print(f"│  IR Polarity:    {s.ir_polarity_mode.name:<22}│")
        print(f"│  Color Palette:  {s.color_palette.name:<22}│")
        print(f"│  NUC Value:      0x{s.nuc_value:02X}{'':<19}│")
        print(f"│  Freeze:         {s.freeze_mode.name:<22}│")
        print(f"│  Text OSD:       {s.text_osd_mode.name:<22}│")
        print(f"│  Graphics OSD:   {s.graphics_osd_mode.name:<22}│")
        print("├─────────────────────────────────────────┤")
        tx_status = 'ACTIVE' if self.driver.is_transmitting() else 'STOPPED'
        conn_status = 'CONNECTED' if self.driver.is_connected() else 'DISCONNECTED'
        print(f"│  Transmission:   {tx_status:<22}│")
        print(f"│  Connection:     {conn_status:<22}│")
        print("└─────────────────────────────────────────┘")
    
    def do_help_all(self, line):
        """Show all available commands grouped by category"""
        print("""
┌─────────────────────────────────────────────────────────────┐
│                    Available Commands                        │
├─────────────────────────────────────────────────────────────┤
│ TRANSMISSION CONTROL:                                        │
│   start        - Start transmission (25Hz)                   │
│   stop         - Stop transmission                           │
│   send         - Send single command                         │
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
│                                                              │
│ IMAGE:                                                       │
│   nuc          - Toggle NUC                                  │
│   polarity     - Set IR polarity (white|black)              │
│   palette      - Set palette (grey|color1|color2|color3)    │
│   freeze       - Freeze image (on|off)                       │
│                                                              │
│ OSD:                                                         │
│   text_osd     - Enable/disable text OSD (on|off)           │
│   graphics_osd - Enable/disable graphics OSD (on|off)       │
│                                                              │
│ DISPLAY:                                                     │
│   verbose      - Toggle parsed RX display (on|off)          │
│   raw          - Toggle raw hex TX/RX display (on|off)      │
│   status       - Show current settings                       │
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
        if self.driver:
            self.driver.disconnect()
        return True
    
    def do_exit(self, line):
        """Exit the application"""
        return self.do_quit(line)
    
    def do_EOF(self, line):
        """Handle Ctrl+D"""
        print()
        return self.do_quit(line)


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python nextShell.py <tty_device>")
        print("Example: python nextShell.py /dev/ttyUSB0")
        sys.exit(1)
    
    tty_device = sys.argv[1]
    
    try:
        shell = ColibriShell(tty_device)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
