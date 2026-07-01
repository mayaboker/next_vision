#!/usr/bin/env python3
"""
Colibri Camera Driver - Handles serial communication and message protocol
"""

import serial
import threading
import time
from enum import IntEnum
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass


# =============================================================================
# Enumerations for Camera Settings
# =============================================================================

class ColibCamModes(IntEnum):
    RATE = 0
    PILOT = 3
    STOW = 4
    PARK = 8
    GYRO_CALIBRATION = 10
    RATE_GYRO_FROM_FLASH = 30
    EXT = 31


class ColibCamLaserEn(IntEnum):
    LASER_ON = 0x40
    LASER_OFF = 0x00


class ColibCamSensor(IntEnum):
    VISIBLE = 0x00
    IR = 0x80


class ColibCamIRPolarityMode(IntEnum):
    WHITE_HOT = 0x00
    BLACK_HOT = 0x10


class ColibCamColorPalette(IntEnum):
    GREY = 0x00
    COLOR1 = 0x40
    COLOR2 = 0x80
    COLOR3 = 0xC0


class ColibCamLaserMode(IntEnum):
    LASER_ALWAYS_ON = 0x00
    LASER_2HZ = 0x20
    LASER_6HZ = 0x40
    LASER_30HZ = 0x60


class ColibCamZoom(IntEnum):
    NO_ZOOM = 0x00
    ZOOM_IN = 0x80
    ZOOM_OUT = 0x40


class ColibCamRateCalculationMode(IntEnum):
    RATE_NOT_DEPEND_ON_ZOOM = 0x00
    RATE_DEPEND_ON_ZOOM = 0x01


class ColibCamFreezeMode(IntEnum):
    NORMAL = 0x00
    FREEZE = 0x02


class ColibCamTextOSDMode(IntEnum):
    ENABLE_TEXT_OSD = 0x00
    DISABLE_TEXT_OSD = 0x40


class ColibCamGraphicsOSDMode(IntEnum):
    ENABLE_GRAPHICS_OSD = 0x00
    DISABLE_GRAPHICS_OSD = 0x20


# =============================================================================
# Data Classes for Parsed Messages
# =============================================================================

@dataclass
class CameraStatus:
    """Parsed camera status from received packet"""
    mode: int
    sensor: str
    total_pitch_deg: float
    total_roll_deg: float
    mech_pitch_deg: float
    mech_roll_deg: float
    elec_pitch_deg: float
    elec_roll_deg: float
    hfov_deg: float
    vfov_deg: float
    raw_packet: bytes


@dataclass
class CameraSettings:
    """Current camera settings for transmission"""
    cam_mode: ColibCamModes = ColibCamModes.RATE
    laser_enable: ColibCamLaserEn = ColibCamLaserEn.LASER_OFF
    sensor: ColibCamSensor = ColibCamSensor.VISIBLE
    ir_polarity_mode: ColibCamIRPolarityMode = ColibCamIRPolarityMode.WHITE_HOT
    color_palette: ColibCamColorPalette = ColibCamColorPalette.GREY
    laser_mode: ColibCamLaserMode = ColibCamLaserMode.LASER_ALWAYS_ON
    rate_calc_mode: ColibCamRateCalculationMode = ColibCamRateCalculationMode.RATE_NOT_DEPEND_ON_ZOOM
    freeze_mode: ColibCamFreezeMode = ColibCamFreezeMode.NORMAL
    text_osd_mode: ColibCamTextOSDMode = ColibCamTextOSDMode.ENABLE_TEXT_OSD
    graphics_osd_mode: ColibCamGraphicsOSDMode = ColibCamGraphicsOSDMode.ENABLE_GRAPHICS_OSD
    nuc_value: int = 0x00
    zoom_state: ColibCamZoom = ColibCamZoom.NO_ZOOM
    gimbal_pitch_value: int = 2048  # RATE_MIDDLE_VAL
    gimbal_roll_value: int = 2048   # RATE_MIDDLE_VAL


# =============================================================================
# Protocol Constants
# =============================================================================

class ColibriProtocol:
    """Protocol constants and message templates"""
    PACKET_LEN = 20
    HEADER_1 = 0xB0
    HEADER_2 = 0x3B
    NUC_TOGGLE = 0x20
    RATE_MIN_VAL = 0
    RATE_MIDDLE_VAL = 2048
    RATE_MAX_VAL = 4095
    
    # Default TX message template
    DEFAULT_TX_TEMPLATE = bytearray([
        0xB0, 0x3B, 0x77, 0x06, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80,
        0x80, 0x80, 0x00, 0x49
    ])


# =============================================================================
# Message Builder
# =============================================================================

class MessageBuilder:
    """Builds TX messages from camera settings"""
    
    @staticmethod
    def build_message(settings: CameraSettings) -> bytearray:
        """
        Construct a complete TX message from current settings
        
        Args:
            settings: CameraSettings object with current configuration
            
        Returns:
            Complete message bytearray ready for transmission
        """
        msg = bytearray(ColibriProtocol.DEFAULT_TX_TEMPLATE)
        
        # Construct byte 3: mode | laser_enable | sensor
        msg[3] = (
            int(settings.cam_mode) |
            int(settings.laser_enable) |
            int(settings.sensor)
        )
        
        # Construct byte 4: freeze | rate_calc | text_osd | graphics_osd
        msg[4] = (
            int(settings.freeze_mode) |
            int(settings.rate_calc_mode) |
            int(settings.text_osd_mode) |
            int(settings.graphics_osd_mode)
        )
        
        # Construct byte 5: color_palette | nuc | ir_polarity
        msg[5] = (
            int(settings.color_palette) |
            settings.nuc_value |
            int(settings.ir_polarity_mode)
        )
        
        # Construct byte 7: laser_mode
        msg[7] = int(settings.laser_mode)
        
        # Clamp pitch & roll values to valid range
        pitch = max(ColibriProtocol.RATE_MIN_VAL,
                   min(ColibriProtocol.RATE_MAX_VAL, settings.gimbal_pitch_value))
        roll = max(ColibriProtocol.RATE_MIN_VAL,
                  min(ColibriProtocol.RATE_MAX_VAL, settings.gimbal_roll_value))
        
        # Construct zoom value (byte 14)
        msg[14] = int(settings.zoom_state)
        
        # Clear roll & pitch bits in bytes 14 and 18
        msg[14] &= 0xC3
        msg[18] &= 0xC3
        
        # Construct pitch value (bytes 14, 15, 18)
        msg[15] = (pitch >> 4) & 0xFF
        msg[14] |= ((pitch & 0x0C) << 2) & 0xFF
        msg[18] |= ((pitch & 0x03) << 4) & 0xFF
        
        # Construct roll value (bytes 14, 16, 18)
        msg[16] = (roll >> 4) & 0xFF
        msg[14] |= (roll & 0x0C) & 0xFF
        msg[18] |= ((roll & 0x03) << 2) & 0xFF
        
        # Calculate and set checksum
        msg[-1] = sum(msg[:-1]) & 0xFF
        
        return msg
    
    @staticmethod
    def format_hex(data: bytes) -> str:
        """Format bytes as hex string for display"""
        return ' '.join(f'{b:02X}' for b in data)


# =============================================================================
# Message Parser
# =============================================================================

class MessageParser:
    """Parses RX messages into camera status"""
    
    @staticmethod
    def validate_packet(packet: bytes) -> bool:
        """
        Validate a received packet
        
        Args:
            packet: Received bytes
            
        Returns:
            True if packet is valid
        """
        if len(packet) != ColibriProtocol.PACKET_LEN:
            return False
        
        # Check header bytes
        if packet[0] != ColibriProtocol.HEADER_1 or packet[1] != ColibriProtocol.HEADER_2:
            return False
        
        # Calculate and validate checksum
        checksum = sum(packet[:-1]) & 0xFF
        return packet[-1] == checksum
    
    @staticmethod
    def parse_packet(packet: bytes) -> CameraStatus:
        """
        Parse a received packet into CameraStatus
        
        Args:
            packet: Valid received packet bytes
            
        Returns:
            CameraStatus with parsed values
        """
        # Extract sensor and mode
        cam_sensor = packet[3] & 0x80
        cam_mode = packet[3] & 0x1F
        
        # Extract total pitch (14-bit value)
        cam_total_pitch_report = (
            (packet[7] << 6) |
            ((packet[9] & 0xF0) >> 2) |
            ((packet[4] & 0x30) >> 4)
        )
        cam_total_pitch_deg = (cam_total_pitch_report * 360.0) / 16384.0
        
        # Extract total roll (14-bit value)
        cam_total_roll_report = (
            (packet[8] << 6) |
            ((packet[9] & 0x0F) << 2) |
            ((packet[4] & 0xC0) >> 6)
        )
        cam_total_roll_deg = (cam_total_roll_report * 360.0) / 16384.0
        
        # Extract electronic roll (14-bit value)
        cam_elec_roll_report = (
            (packet[10] << 6) |
            ((packet[12] & 0xF0) >> 2) |
            ((packet[4] & 0x0C) >> 2)
        )
        cam_elec_roll_deg = (cam_elec_roll_report * 360.0) / 16384.0
        
        # Extract electronic pitch (14-bit value)
        cam_elec_pitch_report = (
            (packet[11] << 6) |
            ((packet[12] & 0x0F) << 2) |
            (packet[4] & 0x03)
        )
        cam_elec_pitch_deg = (cam_elec_pitch_report * 360.0) / 16384.0
        
        # Wrap electronic values to [-180, 180]
        if cam_elec_roll_deg > 180.0:
            cam_elec_roll_deg -= 360.0
        if cam_elec_pitch_deg > 180.0:
            cam_elec_pitch_deg -= 360.0
        
        # Calculate mechanical values
        cam_mech_roll_deg = cam_total_roll_deg - cam_elec_roll_deg
        cam_mech_pitch_deg = cam_total_pitch_deg - cam_elec_pitch_deg
        
        # Wrap mechanical values to [-180, 180]
        if cam_mech_roll_deg > 180.0:
            cam_mech_roll_deg -= 360.0
        if cam_mech_pitch_deg > 180.0:
            cam_mech_pitch_deg -= 360.0
        if cam_total_pitch_deg > 180.0:
            cam_total_pitch_deg -= 360.0
        if cam_total_roll_deg > 180.0:
            cam_total_roll_deg -= 360.0
        
        # Calculate FOV from zoom byte
        cam_hfov_deg = 100.0 / (1.03 ** packet[5])
        cam_vfov_deg = (cam_hfov_deg * 9.0) / 16.0
        
        return CameraStatus(
            mode=cam_mode,
            sensor='IR' if cam_sensor else 'Visible',
            total_pitch_deg=cam_total_pitch_deg,
            total_roll_deg=cam_total_roll_deg,
            mech_pitch_deg=cam_mech_pitch_deg,
            mech_roll_deg=cam_mech_roll_deg,
            elec_pitch_deg=cam_elec_pitch_deg,
            elec_roll_deg=cam_elec_roll_deg,
            hfov_deg=cam_hfov_deg,
            vfov_deg=cam_vfov_deg,
            raw_packet=packet
        )
    
    @staticmethod
    def format_hex(data: bytes) -> str:
        """Format bytes as hex string for display"""
        return ' '.join(f'{b:02X}' for b in data)


# =============================================================================
# Serial Driver
# =============================================================================

class ColibriDriver:
    """
    Main driver class for Colibri camera communication
    
    Handles:
    - Serial port connection/disconnection
    - Receiving and validating packets
    - Transmitting command messages
    - Periodic transmission at 25Hz
    """
    
    def __init__(self, port_name: str,
                 on_rx_callback: Optional[Callable[[CameraStatus], None]] = None,
                 on_tx_callback: Optional[Callable[[bytes], None]] = None,
                 on_raw_rx_callback: Optional[Callable[[bytes], None]] = None):
        """
        Initialize the Colibri driver
        
        Args:
            port_name: Serial port device path (e.g., /dev/ttyUSB0)
            on_rx_callback: Called with parsed CameraStatus on valid packet receive
            on_tx_callback: Called with raw bytes when message is transmitted
            on_raw_rx_callback: Called with raw bytes when valid packet received
        """
        self.port_name = port_name
        self.on_rx_callback = on_rx_callback
        self.on_tx_callback = on_tx_callback
        self.on_raw_rx_callback = on_raw_rx_callback
        
        self.serial_port: Optional[serial.Serial] = None
        self.running = False
        self.tx_active = False
        
        self.receive_thread: Optional[threading.Thread] = None
        self.tx_thread: Optional[threading.Thread] = None
        
        self.window_buffer = bytearray(ColibriProtocol.PACKET_LEN)
        self.settings = CameraSettings()
        
        self._connect()
    
    def _connect(self):
        """Establish serial connection"""
        try:
            self.serial_port = serial.Serial(
                port=self.port_name,
                baudrate=19200,
                parity=serial.PARITY_EVEN,
                timeout=1.0
            )
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.port_name}: {e}")
    
    def disconnect(self):
        """Close the serial connection"""
        self.stop_transmission()
        self.running = False
        
        if self.receive_thread:
            self.receive_thread.join(timeout=1.0)
        
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
    
    def _receive_loop(self):
        """Background thread for receiving data"""
        while self.running and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    byte_data = self.serial_port.read(1)
                    if byte_data:
                        rx_byte = byte_data[0]
                        
                        # Shift window buffer and add new byte
                        self.window_buffer = self.window_buffer[1:] + bytearray([rx_byte])
                        
                        # Check if we have a valid packet
                        if MessageParser.validate_packet(self.window_buffer):
                            packet = bytes(self.window_buffer)
                            
                            # Call raw RX callback
                            if self.on_raw_rx_callback:
                                self.on_raw_rx_callback(packet)
                            
                            # Parse and call RX callback
                            if self.on_rx_callback:
                                status = MessageParser.parse_packet(packet)
                                self.on_rx_callback(status)
                else:
                    time.sleep(0.001)
            except Exception as e:
                if self.running:
                    print(f"Error in receive loop: {e}")
                break
    
    def _tx_loop(self):
        """Background thread for transmitting at 25Hz (40ms intervals)"""
        while self.tx_active:
            self.send_command()
            time.sleep(0.04)
    
    def start_transmission(self):
        """Start periodic transmission at 25Hz"""
        if not self.tx_active:
            self.tx_active = True
            self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
            self.tx_thread.start()
    
    def stop_transmission(self):
        """Stop periodic transmission"""
        self.tx_active = False
        if self.tx_thread:
            self.tx_thread.join(timeout=1.0)
    
    def send_command(self):
        """Build and send a command message based on current settings"""
        msg = MessageBuilder.build_message(self.settings)
        self._send_raw(msg)
    
    def _send_raw(self, data: bytearray):
        """Send raw bytes to serial port"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.write(data)
                if self.on_tx_callback:
                    self.on_tx_callback(bytes(data))
        except Exception as e:
            print(f"Error sending data: {e}")
    
    # =========================================================================
    # Settings Modification Methods
    # =========================================================================
    
    def set_mode(self, mode: ColibCamModes):
        """Set camera operating mode"""
        self.settings.cam_mode = mode
    
    def set_sensor(self, sensor: ColibCamSensor):
        """Set active sensor (visible/IR)"""
        self.settings.sensor = sensor
    
    def set_laser_enable(self, enabled: bool):
        """Enable or disable laser"""
        self.settings.laser_enable = ColibCamLaserEn.LASER_ON if enabled else ColibCamLaserEn.LASER_OFF
    
    def set_laser_mode(self, mode: ColibCamLaserMode):
        """Set laser blinking mode"""
        self.settings.laser_mode = mode
    
    def set_zoom(self, zoom: ColibCamZoom):
        """Set zoom state (in/out/stop)"""
        self.settings.zoom_state = zoom
    
    def set_pitch(self, value: int):
        """Set gimbal pitch value (0-4095)"""
        self.settings.gimbal_pitch_value = max(ColibriProtocol.RATE_MIN_VAL,
                                               min(ColibriProtocol.RATE_MAX_VAL, value))
    
    def set_roll(self, value: int):
        """Set gimbal roll value (0-4095)"""
        self.settings.gimbal_roll_value = max(ColibriProtocol.RATE_MIN_VAL,
                                              min(ColibriProtocol.RATE_MAX_VAL, value))
    
    def set_ir_polarity(self, polarity: ColibCamIRPolarityMode):
        """Set IR polarity (white hot/black hot)"""
        self.settings.ir_polarity_mode = polarity
    
    def set_color_palette(self, palette: ColibCamColorPalette):
        """Set color palette"""
        self.settings.color_palette = palette
    
    def set_freeze(self, freeze: bool):
        """Set freeze mode"""
        self.settings.freeze_mode = ColibCamFreezeMode.FREEZE if freeze else ColibCamFreezeMode.NORMAL
    
    def set_text_osd(self, enabled: bool):
        """Enable or disable text OSD"""
        self.settings.text_osd_mode = (ColibCamTextOSDMode.ENABLE_TEXT_OSD if enabled 
                                       else ColibCamTextOSDMode.DISABLE_TEXT_OSD)
    
    def set_graphics_osd(self, enabled: bool):
        """Enable or disable graphics OSD"""
        self.settings.graphics_osd_mode = (ColibCamGraphicsOSDMode.ENABLE_GRAPHICS_OSD if enabled 
                                           else ColibCamGraphicsOSDMode.DISABLE_GRAPHICS_OSD)
    
    def toggle_nuc(self):
        """Toggle NUC (Non-Uniformity Correction)"""
        self.settings.nuc_value ^= ColibriProtocol.NUC_TOGGLE
    
    def get_settings(self) -> CameraSettings:
        """Get current settings"""
        return self.settings
    
    def is_transmitting(self) -> bool:
        """Check if periodic transmission is active"""
        return self.tx_active
    
    def is_connected(self) -> bool:
        """Check if serial port is connected"""
        return self.serial_port is not None and self.serial_port.is_open

