#!/usr/bin/env python3
"""
Colibri Camera Packet Decoder
Analyzes raw packet bytes and displays detailed breakdown of all fields
Uses driver.py for protocol constants and validation
"""

import sys
from typing import Optional

from driver import (
    ColibriProtocol,
    MessageParser,
    MessageBuilder,
    CameraStatus,
    # Enums for name lookups
    ColibCamModes,
    ColibCamLaserEn,
    ColibCamSensor,
    ColibCamIRPolarityMode,
    ColibCamColorPalette,
    ColibCamLaserMode,
    ColibCamZoom,
    ColibCamFreezeMode,
    ColibCamTextOSDMode,
    ColibCamGraphicsOSDMode,
)


class PacketDecoder:
    """Decodes and analyzes Colibri camera packets"""
    
    # Lookup tables for field names
    MODE_NAMES = {
        ColibCamModes.RATE: "Rate",
        ColibCamModes.PILOT: "Pilot",
        ColibCamModes.STOW: "Stow",
        ColibCamModes.PARK: "Park",
        ColibCamModes.GYRO_CALIBRATION: "Gyro Calibration",
        ColibCamModes.RATE_GYRO_FROM_FLASH: "Rate Gyro From Flash",
        ColibCamModes.EXT: "External",
    }
    
    PALETTE_NAMES = {
        0: "Grey",
        1: "Color1", 
        2: "Color2",
        3: "Color3",
    }
    
    LASER_MODE_NAMES = {
        0: "Always On",
        1: "2Hz",
        2: "6Hz",
        3: "30Hz",
    }
    
    ZOOM_NAMES = {
        0: "No Zoom",
        1: "Zoom Out",
        2: "Zoom In",
        3: "Reserved",
    }
    
    def __init__(self):
        pass
    
    def parse_hex_string(self, hex_string: str) -> Optional[bytes]:
        """Parse hex string into bytes"""
        # Remove spaces, hyphens, colons
        hex_clean = hex_string.replace(' ', '').replace('-', '').replace(':', '')
        
        if len(hex_clean) != ColibriProtocol.PACKET_LEN * 2:
            print(f"Error: Expected {ColibriProtocol.PACKET_LEN * 2} hex characters "
                  f"({ColibriProtocol.PACKET_LEN} bytes), got {len(hex_clean)}")
            return None
        
        try:
            return bytes.fromhex(hex_clean)
        except ValueError as e:
            print(f"Error: Invalid hex string - {e}")
            return None
    
    def decode_packet(self, hex_string: str):
        """Decode a Colibri packet from hex string"""
        
        packet = self.parse_hex_string(hex_string)
        if packet is None:
            return
        
        print("=" * 80)
        print("COLIBRI CAMERA PACKET ANALYSIS")
        print("=" * 80)
        
        # Display raw packet
        print(f"Raw Packet ({len(packet)} bytes):")
        hex_display = MessageBuilder.format_hex(packet)
        print(f"  {hex_display}")
        print()
        
        # Validate packet using driver's MessageParser
        self._print_validation(packet)
        
        # Decode all fields
        self._print_field_breakdown(packet)
        
        # Gimbal analysis
        self._print_gimbal_analysis(packet)
        
        # Reserved bytes
        self._print_reserved_bytes(packet)
        
        # If valid, also show parsed status
        if MessageParser.validate_packet(packet):
            self._print_parsed_status(packet)
        
        print("=" * 80)
    
    def _print_validation(self, packet: bytes):
        """Print packet validation results"""
        print("PACKET VALIDATION:")
        print("-" * 40)
        
        # Check length
        if len(packet) != ColibriProtocol.PACKET_LEN:
            print(f"❌ Length: {len(packet)} bytes (expected {ColibriProtocol.PACKET_LEN})")
            return
        else:
            print(f"✅ Length: {len(packet)} bytes")
        
        # Check headers
        header_valid = (packet[0] == ColibriProtocol.HEADER_1 and 
                       packet[1] == ColibriProtocol.HEADER_2)
        if header_valid:
            print(f"✅ Header: {packet[0]:02X} {packet[1]:02X}")
        else:
            print(f"❌ Header: {packet[0]:02X} {packet[1]:02X} "
                  f"(expected {ColibriProtocol.HEADER_1:02X} {ColibriProtocol.HEADER_2:02X})")
        
        # Check checksum
        calculated_checksum = sum(packet[:-1]) & 0xFF
        checksum_valid = packet[-1] == calculated_checksum
        if checksum_valid:
            print(f"✅ Checksum: {packet[-1]:02X}")
        else:
            print(f"❌ Checksum: {packet[-1]:02X} (calculated: {calculated_checksum:02X})")
        
        # Overall validation using driver
        if MessageParser.validate_packet(packet):
            print(f"✅ Packet is VALID")
        else:
            print(f"❌ Packet is INVALID")
        
        print()
    
    def _print_field_breakdown(self, packet: bytes):
        """Print detailed field breakdown"""
        print("FIELD BREAKDOWN:")
        print("-" * 40)
        
        # Byte 2: Message Type
        print(f"Message Type (Byte 2): 0x{packet[2]:02X}")
        print()
        
        # Byte 3: Camera Mode + Laser + Sensor
        byte3 = packet[3]
        sensor = (byte3 & 0x80) >> 7
        laser_enable = (byte3 & 0x40) >> 6
        camera_mode = byte3 & 0x1F
        
        print(f"Camera Control (Byte 3): 0x{byte3:02X} = {byte3:08b}")
        print(f"  Sensor:       {'IR' if sensor else 'Visible'} (bit 7 = {sensor})")
        print(f"  Laser Enable: {'On' if laser_enable else 'Off'} (bit 6 = {laser_enable})")
        
        mode_name = self.MODE_NAMES.get(camera_mode, f"Unknown ({camera_mode})")
        print(f"  Camera Mode:  {mode_name} (bits 4:0 = {camera_mode})")
        print()
        
        # Byte 4: Control Flags
        byte4 = packet[4]
        graphics_osd = (byte4 & 0x20) >> 5
        text_osd = (byte4 & 0x40) >> 6
        freeze_mode = (byte4 & 0x02) >> 1
        rate_calc = byte4 & 0x01
        
        print(f"Control Flags (Byte 4): 0x{byte4:02X} = {byte4:08b}")
        print(f"  Graphics OSD: {'Disabled' if graphics_osd else 'Enabled'} (bit 5 = {graphics_osd})")
        print(f"  Text OSD:     {'Disabled' if text_osd else 'Enabled'} (bit 6 = {text_osd})")
        print(f"  Freeze Mode:  {'Freeze' if freeze_mode else 'Normal'} (bit 1 = {freeze_mode})")
        print(f"  Rate Calc:    {'Zoom Dependent' if rate_calc else 'Zoom Independent'} (bit 0 = {rate_calc})")
        print()
        
        # Byte 5: Color/NUC/Polarity
        byte5 = packet[5]
        color_palette = (byte5 & 0xC0) >> 6
        nuc_toggle = (byte5 & ColibriProtocol.NUC_TOGGLE) >> 5
        ir_polarity = (byte5 & 0x10) >> 4
        
        print(f"Color/IR Settings (Byte 5): 0x{byte5:02X} = {byte5:08b}")
        
        palette_name = self.PALETTE_NAMES.get(color_palette, f"Unknown ({color_palette})")
        print(f"  Color Palette: {palette_name} (bits 7:6 = {color_palette})")
        print(f"  NUC Toggle:    {nuc_toggle} (bit 5 = {nuc_toggle})")
        print(f"  IR Polarity:   {'Black Hot' if ir_polarity else 'White Hot'} (bit 4 = {ir_polarity})")
        print()
        
        # Byte 7: Laser Mode
        byte7 = packet[7]
        laser_mode = (byte7 & 0x60) >> 5
        
        print(f"Laser Mode (Byte 7): 0x{byte7:02X} = {byte7:08b}")
        
        laser_mode_name = self.LASER_MODE_NAMES.get(laser_mode, f"Unknown ({laser_mode})")
        print(f"  Laser Mode: {laser_mode_name} (bits 6:5 = {laser_mode})")
        print()
        
        # Gimbal Control (Bytes 14, 15, 16, 18)
        byte14 = packet[14]
        byte15 = packet[15]
        byte16 = packet[16]
        byte18 = packet[18]
        
        # Zoom control
        zoom_control = (byte14 & 0xC0) >> 6
        zoom_name = self.ZOOM_NAMES.get(zoom_control, f"Unknown ({zoom_control})")
        
        print(f"Gimbal Control:")
        print(f"  Zoom (Byte 14 bits 7:6): {zoom_name} ({zoom_control})")
        
        # Reconstruct pitch value
        pitch_high = byte15  # bits 11:4
        pitch_mid = (byte14 & 0x30) >> 2  # bits 3:2
        pitch_low = (byte18 & 0x30) >> 4  # bits 1:0
        pitch_value = (pitch_high << 4) | (pitch_mid << 2) | pitch_low
        
        # Reconstruct roll value
        roll_high = byte16  # bits 11:4
        roll_mid = byte14 & 0x0C  # bits 3:2
        roll_low = (byte18 & 0x0C) >> 2  # bits 1:0
        roll_value = (roll_high << 4) | roll_mid | roll_low
        
        print(f"  Pitch Value: {pitch_value} (0x{pitch_value:03X})")
        print(f"    High byte (15): {byte15} (0x{byte15:02X})")
        print(f"    Mid bits (14):  {pitch_mid} from bits 5:4")
        print(f"    Low bits (18):  {pitch_low} from bits 5:4")
        
        print(f"  Roll Value:  {roll_value} (0x{roll_value:03X})")
        print(f"    High byte (16): {byte16} (0x{byte16:02X})")
        print(f"    Mid bits (14):  {(byte14 & 0x0C) >> 2} from bits 3:2")
        print(f"    Low bits (18):  {(byte18 & 0x0C) >> 2} from bits 3:2")
        print()
    
    def _print_gimbal_analysis(self, packet: bytes):
        """Print gimbal position analysis"""
        print("GIMBAL POSITION ANALYSIS:")
        print("-" * 40)
        
        byte14 = packet[14]
        byte15 = packet[15]
        byte16 = packet[16]
        byte18 = packet[18]
        
        # Reconstruct pitch value
        pitch_high = byte15
        pitch_mid = (byte14 & 0x30) >> 2
        pitch_low = (byte18 & 0x30) >> 4
        pitch_value = (pitch_high << 4) | (pitch_mid << 2) | pitch_low
        
        # Reconstruct roll value
        roll_high = byte16
        roll_mid = byte14 & 0x0C
        roll_low = (byte18 & 0x0C) >> 2
        roll_value = (roll_high << 4) | roll_mid | roll_low
        
        center_value = ColibriProtocol.RATE_MIDDLE_VAL
        max_value = ColibriProtocol.RATE_MAX_VAL
        
        # Calculate percentages
        pitch_percent = (pitch_value / max_value) * 100
        roll_percent = (roll_value / max_value) * 100
        
        # Calculate relative to center
        pitch_from_center = pitch_value - center_value
        roll_from_center = roll_value - center_value
        
        print(f"Pitch: {pitch_value:4d} / {max_value} ({pitch_percent:5.1f}%)")
        print(f"       {pitch_from_center:+5d} from center ({center_value})")
        if pitch_value == center_value:
            print(f"       *** CENTERED ***")
        elif pitch_value < center_value:
            print(f"       Direction: DOWN")
        else:
            print(f"       Direction: UP")
        
        print(f"Roll:  {roll_value:4d} / {max_value} ({roll_percent:5.1f}%)")
        print(f"       {roll_from_center:+5d} from center ({center_value})")
        if roll_value == center_value:
            print(f"       *** CENTERED ***")
        elif roll_value < center_value:
            print(f"       Direction: LEFT")
        else:
            print(f"       Direction: RIGHT")
        print()
    
    def _print_reserved_bytes(self, packet: bytes):
        """Print reserved bytes analysis"""
        print("RESERVED BYTES:")
        print("-" * 40)
        
        reserved_bytes = [6, 8, 9, 10, 11, 12, 13, 17]
        for byte_idx in reserved_bytes:
            value = packet[byte_idx]
            status = "✅ Default" if value in [0x00, 0x01, 0x80] else "⚠️  Non-standard"
            print(f"  Byte {byte_idx:2d}: 0x{value:02X} ({value:3d}) {status}")
        print()
    
    def _print_parsed_status(self, packet: bytes):
        """Print parsed camera status using driver's MessageParser"""
        print("PARSED CAMERA STATUS (via MessageParser):")
        print("-" * 40)
        
        status = MessageParser.parse_packet(packet)
        
        print(f"  Mode:   {status.mode}")
        print(f"  Sensor: {status.sensor}")
        print()
        print(f"  Pitch:")
        print(f"    Total:      {status.total_pitch_deg:8.2f}°")
        print(f"    Mechanical: {status.mech_pitch_deg:8.2f}°")
        print(f"    Electronic: {status.elec_pitch_deg:8.2f}°")
        print()
        print(f"  Roll:")
        print(f"    Total:      {status.total_roll_deg:8.2f}°")
        print(f"    Mechanical: {status.mech_roll_deg:8.2f}°")
        print(f"    Electronic: {status.elec_roll_deg:8.2f}°")
        print()
        print(f"  FOV:")
        print(f"    Horizontal: {status.hfov_deg:8.2f}°")
        print(f"    Vertical:   {status.vfov_deg:8.2f}°")
        print()


def print_usage():
    """Print usage information"""
    print("Colibri Camera Packet Decoder")
    print("=" * 50)
    print("Usage: python decoder.py <hex_string>")
    print()
    print("Hex string formats supported:")
    print("  - Space separated: 'B0 3B 77 06 ...'")
    print("  - Hyphen separated: 'B0-3B-77-06-...'")
    print("  - Colon separated: 'B0:3B:77:06:...'")
    print("  - Continuous: 'B03B7706...'")
    print()
    print("Examples:")
    print("  python decoder.py 'B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49'")
    print("  python decoder.py B0-3B-77-06-00-00-00-00-00-01-00-00-00-00-00-80-80-80-00-49")
    print("  python decoder.py B03B7706000000000001000000008080800049")


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    # Join all arguments to handle spaces
    hex_string = ' '.join(sys.argv[1:])
    
    decoder = PacketDecoder()
    decoder.decode_packet(hex_string)


if __name__ == "__main__":
    main()
