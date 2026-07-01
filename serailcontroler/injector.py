#!/usr/bin/env python3
"""
Colibri Camera Packet Injector
Sends raw packet bytes to TTY device at correct timing intervals
Uses driver.py for serial communication and protocol validation
"""

import time
import sys
import signal
import threading
from typing import Optional

from driver import (
    ColibriDriver,
    ColibriProtocol,
    MessageParser,
    MessageBuilder,
    CameraSettings,
)


class PacketInjector:
    """Injects packets into serial port at specified intervals using ColibriDriver"""
    
    def __init__(self, tty_device: str):
        self.tty_device = tty_device
        self.driver: Optional[ColibriDriver] = None
        self.running = False
        self.inject_thread: Optional[threading.Thread] = None
        self.packet_data: Optional[bytes] = None
        self.interval = 0.04  # 40ms = 25Hz (default Colibri rate)
        
        # Statistics
        self.packet_count = 0
        self.start_time = 0.0
        
        # Setup signal handlers for clean exit
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully"""
        print("\nReceived interrupt signal, stopping...")
        self.stop()
        sys.exit(0)
    
    def _on_tx(self, data: bytes):
        """Callback when packet is transmitted"""
        self.packet_count += 1
        
        # Print status every 25 packets (1 second at 25Hz)
        if self.packet_count % 25 == 0:
            elapsed = time.time() - self.start_time
            actual_rate = self.packet_count / elapsed if elapsed > 0 else 0
            print(f"   📊 Sent {self.packet_count} packets, Rate: {actual_rate:.1f}Hz")
    
    def _on_rx(self, data: bytes):
        """Callback when packet is received (for monitoring)"""
        hex_display = MessageParser.format_hex(data)
        print(f"📥 RX: {hex_display}")
        
    def connect(self):
        """Connect to the TTY device using ColibriDriver"""
        try:
            # Create driver with TX callback for statistics
            # We use a minimal driver setup - just for raw serial access
            self.driver = ColibriDriver(
                port_name=self.tty_device,
                on_tx_callback=self._on_tx,
                on_raw_rx_callback=self._on_rx
            )
            print(f"✅ Connected to {self.tty_device}")
            print(f"   Baud: 19200, Parity: Even")
            return True
        except Exception as e:
            print(f"❌ Failed to connect to {self.tty_device}: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from TTY device"""
        if self.driver:
            self.driver.disconnect()
            print(f"Disconnected from {self.tty_device}")
    
    def set_packet(self, hex_string: str):
        """Set the packet data to inject"""
        # Remove spaces, hyphens, colons and convert to bytes
        hex_clean = hex_string.replace(' ', '').replace('-', '').replace(':', '')
        
        if len(hex_clean) % 2 != 0:
            print(f"❌ Error: Odd number of hex characters ({len(hex_clean)})")
            return False
            
        try:
            self.packet_data = bytes.fromhex(hex_clean)
            print(f"✅ Packet loaded: {len(self.packet_data)} bytes")
            hex_display = MessageBuilder.format_hex(self.packet_data)
            print(f"   Data: {hex_display}")
            
            # Use MessageParser to validate if it's a Colibri packet
            if len(self.packet_data) == ColibriProtocol.PACKET_LEN:
                if MessageParser.validate_packet(self.packet_data):
                    print(f"   ✅ Valid Colibri packet detected")
                else:
                    # Check what's wrong
                    if (self.packet_data[0] != ColibriProtocol.HEADER_1 or 
                        self.packet_data[1] != ColibriProtocol.HEADER_2):
                        print(f"   ⚠️  Header doesn't match Colibri format "
                              f"(expected {ColibriProtocol.HEADER_1:02X} {ColibriProtocol.HEADER_2:02X})")
                    else:
                        calc_checksum = sum(self.packet_data[:-1]) & 0xFF
                        print(f"   ⚠️  Checksum mismatch "
                              f"(got 0x{self.packet_data[-1]:02X}, expected 0x{calc_checksum:02X})")
            else:
                print(f"   ⚠️  Length is {len(self.packet_data)} bytes "
                      f"(Colibri expects {ColibriProtocol.PACKET_LEN})")
            
            return True
        except ValueError as e:
            print(f"❌ Error: Invalid hex string - {e}")
            return False
    
    def set_packet_from_settings(self, settings: CameraSettings):
        """Build packet from CameraSettings object"""
        self.packet_data = bytes(MessageBuilder.build_message(settings))
        hex_display = MessageBuilder.format_hex(self.packet_data)
        print(f"✅ Packet built from settings: {len(self.packet_data)} bytes")
        print(f"   Data: {hex_display}")
        return True
    
    def set_interval(self, interval_ms: float):
        """Set injection interval in milliseconds"""
        self.interval = interval_ms / 1000.0
        freq = 1.0 / self.interval
        print(f"✅ Interval set to {interval_ms:.1f}ms ({freq:.1f}Hz)")
    
    def start_injection(self):
        """Start injecting packets"""
        if not self.packet_data:
            print("❌ Error: No packet data loaded")
            return False
            
        if not self.driver or not self.driver.is_connected():
            print("❌ Error: Not connected to TTY device")
            return False
        
        if self.running:
            print("⚠️  Injection already running")
            return True
        
        # Reset statistics
        self.packet_count = 0
        self.start_time = time.time()
        
        self.running = True
        self.inject_thread = threading.Thread(target=self._injection_loop, daemon=True)
        self.inject_thread.start()
        
        freq = 1.0 / self.interval
        print(f"🚀 Started injection at {freq:.1f}Hz ({self.interval*1000:.1f}ms intervals)")
        print("   Press Ctrl+C to stop")
        
        return True
    
    def stop(self):
        """Stop injection"""
        if self.running:
            self.running = False
            if self.inject_thread:
                self.inject_thread.join(timeout=1.0)
            
            # Print final statistics
            elapsed = time.time() - self.start_time
            actual_rate = self.packet_count / elapsed if elapsed > 0 else 0
            print(f"⏹️  Injection stopped")
            print(f"📈 Final stats: {self.packet_count} packets in {elapsed:.1f}s (avg {actual_rate:.1f}Hz)")
        
    def _injection_loop(self):
        """Main injection loop running in background thread"""
        try:
            while self.running:
                if self.driver and self.driver.is_connected():
                    # Send packet using driver's internal send method
                    self.driver._send_raw(bytearray(self.packet_data))
                    
                    # Wait for next interval
                    time.sleep(self.interval)
                else:
                    print("❌ Lost connection to TTY device")
                    break
                    
        except Exception as e:
            print(f"❌ Error during injection: {e}")
    
    def send_single(self):
        """Send a single packet"""
        if not self.packet_data:
            print("❌ Error: No packet data loaded")
            return False
            
        if not self.driver or not self.driver.is_connected():
            print("❌ Error: Not connected to TTY device")
            return False
        
        try:
            # Reset count for single shot
            self.packet_count = 0
            self.start_time = time.time()
            
            self.driver._send_raw(bytearray(self.packet_data))
            hex_display = MessageBuilder.format_hex(self.packet_data)
            print(f"📤 Sent: {hex_display}")
            return True
        except Exception as e:
            print(f"❌ Error sending packet: {e}")
            return False


def print_usage():
    """Print usage information"""
    print("Colibri Camera Packet Injector")
    print("=" * 50)
    print("Usage: python injector.py <tty_device> <hex_packet> [options]")
    print()
    print("Arguments:")
    print("  tty_device    - Serial device (e.g., /dev/ttyUSB0, COM3)")
    print("  hex_packet    - Packet data in hex format")
    print()
    print("Options:")
    print("  --interval <ms>  - Injection interval in milliseconds (default: 40ms = 25Hz)")
    print("  --single         - Send single packet and exit")
    print("  --continuous     - Send continuously (default)")
    print()
    print("Examples:")
    print("  # Send Colibri packet at 25Hz")
    print("  python injector.py /dev/ttyUSB0 \\")
    print("    'B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49'")
    print()
    print("  # Send at 10Hz (100ms intervals)")
    print("  python injector.py /dev/ttyUSB0 'B0 3B 77 06...' --interval 100")
    print()
    print("  # Send single packet")
    print("  python injector.py /dev/ttyUSB0 'B0 3B 77 06...' --single")


def main():
    """Main function with command line interface"""
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(1)
    
    tty_device = sys.argv[1]
    hex_packet = sys.argv[2]
    
    # Parse options
    interval_ms = 40.0  # Default 25Hz
    single_shot = False
    
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--interval' and i + 1 < len(sys.argv):
            try:
                interval_ms = float(sys.argv[i + 1])
                i += 2
            except ValueError:
                print(f"❌ Error: Invalid interval value '{sys.argv[i + 1]}'")
                sys.exit(1)
        elif sys.argv[i] == '--single':
            single_shot = True
            i += 1
        elif sys.argv[i] == '--continuous':
            single_shot = False
            i += 1
        else:
            print(f"❌ Error: Unknown option '{sys.argv[i]}'")
            sys.exit(1)
    
    # Create injector
    injector = PacketInjector(tty_device)
    
    # Connect to device
    if not injector.connect():
        sys.exit(1)
    
    try:
        # Load packet data
        if not injector.set_packet(hex_packet):
            sys.exit(1)
        
        # Set interval if not single shot
        if not single_shot:
            injector.set_interval(interval_ms)
        
        if single_shot:
            # Send single packet
            if injector.send_single():
                print("✅ Single packet sent successfully")
            else:
                sys.exit(1)
        else:
            # Start continuous injection
            if injector.start_injection():
                # Keep main thread alive
                try:
                    while injector.running:
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    print("\n🛑 Stopping injection...")
                    injector.stop()
            else:
                sys.exit(1)
                
    finally:
        injector.disconnect()


if __name__ == "__main__":
    main()
