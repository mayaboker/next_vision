import socket
import os
import json
class FeedbackDriver:
    DIV_VALUE = 16384.0
    MAX_DEGREE = 180.0
    LOOP = 360.0

    def __init__(self, ip, port):
        
        self.ccp_ip = ip
        self.ccp_port = port


        self.current_parameters = None

    @staticmethod
    def _cam_mode(byte):
        return "Thermal" if byte else "VIS"

    @staticmethod
    def _gimbal_status(byte):
        return "OK" if byte == 0 else "ERROR"

    def _cam_total_pitch(self, hex_data):
        total_pitch = ((hex_data[7] << 6) | ((hex_data[9] & 0xF0) >> 2) | (
                    (hex_data[4] & 0x30) >> 4)) * self.LOOP / self.DIV_VALUE
        elec_pitch = ((hex_data[11] << 6) | ((hex_data[12] & 0x0F) << 2) | (
                    hex_data[4] & 0x03)) * self.LOOP / self.DIV_VALUE
        return self._compute_moves(total_pitch, elec_pitch)

    def _cam_total_roll(self, hex_data):
        total_roll = ((hex_data[8] << 6) | ((hex_data[9] & 0x0F) << 2) | (
                    (hex_data[4] & 0xC0) >> 6)) * self.LOOP / self.DIV_VALUE
        elec_roll = ((hex_data[10] << 6) | ((hex_data[12] & 0xF0) >> 2) | (
                    (hex_data[4] & 0x0C) >> 2)) * self.LOOP / self.DIV_VALUE
        return self._compute_moves(total_roll, elec_roll)

    def _compute_moves(self, total, elec):
        elec = elec - self.LOOP if elec > self.MAX_DEGREE else elec
        mech = total - elec
        mech = mech - self.LOOP if mech > self.MAX_DEGREE else mech
        total = total - self.LOOP if total > self.MAX_DEGREE else total

        return total, elec, mech

    @staticmethod
    def _cam_FOV(byte):
        h = 100.0 / pow(1.03, float(byte))
        v = h * 9.0 / 16.0
        return h, v

    def _get_packet(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ccp_ip, self.ccp_port))
        sock.settimeout(5.0)
        data, addr = sock.recvfrom(1024)
        hex_data = ""
        try:
            processed_data = data.decode('utf-8').strip().replace("\n", "")
            end_index = processed_data.find('}') + 1
            message = json.loads(processed_data[:end_index])
            # print(message)
            # print()
            msg_type = message.get("type", "")
            # Process both tx and rx messages for camera data
            
            if msg_type in ["rx_raw"]:
                hex_string = message.get("data", "")
                #print(f"Raw hex string: {hex_string}")
                
                # Convert hex string to bytes
                # Remove spaces and convert to bytes
                hex_clean = hex_string.replace(" ", "")
                hex_data = bytes.fromhex(hex_clean)
                
                #print(f"Converted to bytes: {hex_data}")
                #print(f"Byte length: {len(hex_data)}")
                #print(f"First 10 bytes: {list(hex_data[:10])}")

        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            print(f"Raw data: {data}")
        except Exception as e:
            print(f"❌ Error processing message: {e}")
            print(f"Raw data: {data}")

        return hex_data

    def get_current_parameters(self):
        return self.current_parameters

    def listen(self):
        while True:
            hex_data = self._get_packet()
            if hex_data == "":
                continue

            # 0,1,2 - header
            # 3 - bit 7 - Camera Mode

            cam_mode = self._cam_mode(hex_data[3] & 0x80)
            gimbal_satus = self._gimbal_status(hex_data[14])
            camera_total_pitch = self._cam_total_pitch(hex_data)
            camera_total_roll = self._cam_total_roll(hex_data)
            camera_FOV = self._cam_FOV(hex_data[5])

            self.current_parameters = cam_mode, gimbal_satus, camera_total_pitch, camera_total_roll, camera_FOV
            
            # os.system('clear')
            # print("Camera: " + cam_mode)
            # print("Gimbal: " + gimbal_satus)
            # print(f"PITCH  total: {camera_total_pitch[0]} deg, elec: {camera_total_pitch[1]} deg, mech: {camera_total_pitch[2]} deg")     
            # print(f"ROLL   total: {camera_total_roll[0]} deg, elec: {camera_total_roll[1]} deg, mech: {camera_total_roll[2]} deg")
            # print(f"FOV    H: {camera_FOV[0]} deg, V: {camera_FOV[1]} deg")
            
            # print("1. day")
            # print("2. IR")
            # print("'d' start Roll +")
            # print("'a' start Roll -")
            # print("'w' start Pitch +")
            # print("'x' start Pitch -")
            # print("'+' start Zoom +")
            # print("'-' start Zoom -")
            # print("'s' scan")
            # print("9. nuc")

            #for b in hex_data:
            #   print(f"{b:02x}")
