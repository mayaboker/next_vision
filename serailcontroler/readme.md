# Colibri Camera Controller

A Python toolkit for controlling Colibri camera systems over serial and network interfaces.

## Modules Overview

| Module | Description |
|--------|-------------|
| `driver.py` | Core driver - serial communication, protocol handling, message building/parsing |
| `nextShell.py` | Interactive shell for direct hardware control |
| `decoder.py` | Packet analyzer - decodes and displays packet field breakdown |
| `injector.py` | Packet injector - sends raw packets at specified intervals |
| `proxy.py` | Network server - bridges ethernet commands to hardware |
| `sender.py` | Network client - sends commands to proxy from local or remote machine |

## Requirements

```bash
pip install pyserial
```

## Module Details

### driver.py

Core library used by all other modules. Provides:

- `ColibriDriver` - Serial communication with TX/RX callbacks
- `MessageBuilder` - Constructs command packets from settings
- `MessageParser` - Validates and parses received packets
- `CameraSettings` / `CameraStatus` - Data structures
- All protocol enums (`ColibCamModes`, `ColibCamZoom`, etc.)

```python
from driver import ColibriDriver, ColibCamModes

driver = ColibriDriver("/dev/ttyUSB0", on_rx_callback=my_handler)
driver.set_mode(ColibCamModes.RATE)
driver.set_zoom(ColibCamZoom.ZOOM_IN)
driver.start_transmission()  # 25Hz
```

---

### nextShell.py

Interactive command shell for direct camera control.

```bash
python nextShell.py /dev/ttyUSB0
```

```
colibri> start              # Begin 25Hz transmission
colibri> mode rate          # Set camera mode
colibri> sensor ir          # Switch to IR sensor
colibri> laser on           # Enable laser
colibri> zoom in            # Zoom in
colibri> pitch 2500         # Set pitch value
colibri> roll 1500          # Set roll value
colibri> center             # Center gimbal
colibri> nuc                # Toggle NUC
colibri> status             # Show current settings
colibri> stop               # Stop transmission
colibri> quit               # Exit
```

**Display controls:**
- `verbose on/off` - Toggle parsed RX status display
- `raw on/off` - Toggle raw hex TX/RX display

---

### decoder.py

Analyzes packet bytes and displays detailed field breakdown.

```bash
python decoder.py 'B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49'
```

Supports multiple hex formats:
```bash
python decoder.py 'B0 3B 77 06...'           # Space-separated
python decoder.py B0-3B-77-06-...            # Hyphen-separated
python decoder.py B03B7706...                # Continuous
```

Output includes:
- Packet validation (header, checksum)
- Field breakdown (mode, sensor, laser, zoom, etc.)
- Gimbal position analysis
- Parsed camera status

---

### injector.py

Sends raw packets to hardware at specified intervals.

```bash
# Continuous at 25Hz (default)
python injector.py /dev/ttyUSB0 'B0 3B 77 06 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 49'

# Custom interval (10Hz = 100ms)
python injector.py /dev/ttyUSB0 'B0 3B...' --interval 100

# Single packet
python injector.py /dev/ttyUSB0 'B0 3B...' --single
```

---

### proxy.py

Network server that bridges TCP commands to camera hardware.

```bash
# Start on default port 12345
python proxy.py /dev/ttyUSB0

# Custom host/port
python proxy.py /dev/ttyUSB0 --host 192.168.1.100 --port 5000
```

**Protocol:** JSON messages over TCP, newline-delimited.

**Supported commands:**
```json
{"cmd": "ping"}
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "mode", "value": "rate"}
{"cmd": "zoom", "value": "in"}
{"cmd": "pitch", "value": 2500}
{"cmd": "move", "direction": "up", "amount": 100}
{"cmd": "raw", "data": "B0 3B 77 06..."}
{"cmd": "get_settings"}
```

**Broadcasts to clients:**
```json
{"type": "tx", "data": "B0 3B...", "timestamp": 1234567890.123}
{"type": "rx_raw", "data": "B0 3B...", "timestamp": 1234567890.123}
{"type": "rx_status", "status": {...}, "timestamp": 1234567890.123}
```

---

### sender.py

Network client for sending commands to proxy server.

**Interactive mode:**
```bash
python sender.py
python sender.py --host 192.168.1.100 --port 5000
```

```
sender> ping                # Test connection
sender> start               # Start transmission
sender> up 200              # Move up by 200
sender> down                # Move down by 100 (default)
sender> left 150            # Move left by 150
sender> zoom in             # Zoom in
sender> laser on            # Enable laser
sender> settings            # Get current settings
sender> quiet               # Disable RX display
sender> loud                # Enable all displays
sender> quit                # Exit
```

**Single command mode:**
```bash
python sender.py --cmd ping
python sender.py --cmd start
python sender.py --cmd mode --value rate
python sender.py --cmd pitch --value 2500
python sender.py --cmd raw --data 'B0 3B 77 06...'
python sender.py --host 192.168.1.100 --cmd zoom --value in
```

---

## Typical Workflows

### Direct Control (Local)

```bash
python nextShell.py /dev/ttyUSB0
```

### Remote Control (Network)

**On device with camera:**
```bash
python proxy.py /dev/ttyUSB0 --host 0.0.0.0 --port 12345
```

**On remote machine:**
```bash
python sender.py --host 192.168.1.100 --port 12345
```

### Packet Analysis

```bash
# Capture a packet from camera, then decode it
python decoder.py 'B0 3B 77 86 00 00 00 00 00 01 00 00 00 00 00 80 80 80 00 C9'
```

### Stress Testing

```bash
# Inject packets at 50Hz
python injector.py /dev/ttyUSB0 'B0 3B...' --interval 20
```

---

## Command Reference

| Command | Shell | Sender | Description |
|---------|-------|--------|-------------|
| `start` | ✓ | ✓ | Start 25Hz transmission |
| `stop` | ✓ | ✓ | Stop transmission |
| `send` | ✓ | ✓ | Send single packet |
| `mode <m>` | ✓ | ✓ | Set mode: rate, pilot, stow, park, gyro, ext |
| `sensor <s>` | ✓ | ✓ | Set sensor: visible, ir |
| `laser <on/off>` | ✓ | ✓ | Enable/disable laser |
| `laser_mode <m>` | ✓ | ✓ | Set laser mode: always, 2hz, 6hz, 30hz |
| `zoom <z>` | ✓ | ✓ | Set zoom: in, out, stop |
| `pitch <0-4095>` | ✓ | ✓ | Set pitch value |
| `roll <0-4095>` | ✓ | ✓ | Set roll value |
| `center` | ✓ | ✓ | Center gimbal (2048, 2048) |
| `up/down [n]` | - | ✓ | Move gimbal vertically |
| `left/right [n]` | - | ✓ | Move gimbal horizontally |
| `nuc` | ✓ | ✓ | Toggle NUC |
| `polarity <p>` | ✓ | ✓ | Set IR polarity: white, black |
| `palette <p>` | ✓ | ✓ | Set palette: grey, color1, color2, color3 |
| `freeze <on/off>` | ✓ | ✓ | Freeze image |
| `status` | ✓ | ✓ | Show current status |
| `raw <hex>` | - | ✓ | Send raw hex bytes |

---

## Protocol Notes

- **Baud rate:** 19200
- **Parity:** Even
- **Packet length:** 20 bytes
- **Header:** `0xB0 0x3B`
- **Checksum:** Sum of bytes 0-18, masked to 8 bits
- **TX rate:** 25Hz (40ms intervals)

---

