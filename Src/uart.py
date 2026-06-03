# uart.py
import serial
import time
import os
import serial.tools.list_ports
import threading

class UARTManager:
    def __init__(self, port=None, baudrate=115200, timeout=1):
        self.port = port if port else ('/dev/ttyAMA0' if os.name != 'nt' else 'COM11')
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.read_paused = False
        self.read_lock = threading.Lock()

    # ------------------ Các hàm cũ ------------------
    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[UART] Connect fail: {e}")
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def pause_reading(self):
        with self.read_lock:
            self.read_paused = True

    def resume_reading(self):
        with self.read_lock:
            self.read_paused = False

    def send_gcode(self, gcode, wait_for_done=True, timeout=10):
        if not self.is_connected():
            return False, "Not connected"
        cmd = gcode.strip() + "\n"
        self.ser.write(cmd.encode())
        print(f"[UART] -> {cmd.strip()}")
        if not wait_for_done:
            return True, "ok"
        # Tạm dừng luồng đọc để tránh xung đột
        self.pause_reading()
        try:
            start = time.time()
            while time.time() - start < timeout:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode().strip().lower()
                    if "done" in line or "ok" in line:
                        print(f"[UART] <- {line}")
                        return True, line
                time.sleep(0.05)
            return False, "Timeout waiting 'done' or 'ok'"
        finally:
            self.resume_reading()

    def home(self):
        return self.send_gcode("G0")

    def move_to(self, angle_deg):
        return self.send_gcode(f"G1 Z{angle_deg}")

    def run_rotation_sequence(self, step_angle=10, total_angle=360, wait_time=0, progress_callback=None):
        if not self.home()[0]:
            return ["Homing failed"]
        logs = []
        current = 0
        steps = int(total_angle / step_angle)
        for i in range(1, steps+1):
            current += step_angle
            ok, resp = self.move_to(current)
            if not ok:
                logs.append(f"Failed at {current}°: {resp}")
                break
            logs.append(f"Reached {current}°")
            if progress_callback:
                progress_callback(i, current)
            if wait_time > 0:
                time.sleep(wait_time)
        return logs

    @staticmethod
    def scan_responding_ports(baudrate=115200, timeout=1):
        available_ports = [port.device for port in serial.tools.list_ports.comports()]
        responding_ports = []
        test_cmd = "RMLOCK\n"
        rsp_cmd = "Okay\n"
        expected_responses = ["MSG: Machine Unlocked", "CMD received"]
        for port in available_ports:
            try:
                ser = serial.Serial(port, baudrate, timeout=timeout)
                time.sleep(1.5)
                ser.reset_input_buffer()
                ser.write(test_cmd.encode())
                ser.flush()
                start = time.time()
                found = False
                while time.time() - start < timeout:
                    if ser.in_waiting:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if any(exp in line for exp in expected_responses):
                            ser.write(rsp_cmd.encode())
                            ser.flush()
                            time.sleep(0.1)
                            found = True
                            break
                ser.close()
                if found:
                    responding_ports.append(port)
            except Exception:
                continue
        return responding_ports

    def auto_connect(self, baudrate=115200, timeout=2):
        ports = self.scan_responding_ports(baudrate, timeout)
        if not ports:
            return False, None
        self.port = ports[0]
        self.baudrate = baudrate
        if self.connect():
            return True, self.port
        return False, None

    # ------------------ Hàm mới (chuẩn hóa) ------------------
    def _read_line_normalized(self, timeout=None):
        """Đọc một dòng, trả về string đã lowercase, bỏ \r\n\x00, hoặc None nếu timeout hoặc bị pause."""
        if not self.is_connected():
            return None
        with self.read_lock:
            if self.read_paused:
                return None
        start = time.time()
        while True:
            if timeout is not None and (time.time() - start) > timeout:
                return None
            if self.ser.in_waiting:
                raw = self.ser.readline()
                try:
                    line = raw.decode('utf-8', errors='ignore').strip().lower()
                    line = line.replace('\r', '').replace('\n', '').replace('\x00', '')
                    if line:
                        print(f"[UART_RX] {line}")
                    return line
                except:
                    continue
            time.sleep(0.01)

    def _send_and_wait_for(self, cmd, expected_strings, timeout=10):
        if not self.is_connected():
            return False, None
        if cmd:
            full_cmd = cmd.strip() + "\n"
            self.ser.write(full_cmd.encode())
            print(f"[UART] -> {full_cmd.strip()}")
        start = time.time()
        while time.time() - start < timeout:
            line = self._read_line_normalized(0.05)
            if line is not None:
                for exp in expected_strings:
                    if exp.lower() in line:
                        print(f"[UART] <- {line}")
                        return True, line
        return False, None

    def send_command_with_confirm(self, cmd, expected_confirm="cmd received",
                                   expected_done_patterns=None, timeout=10):
        ok, line = self._send_and_wait_for(cmd, [expected_confirm], timeout)
        if not ok:
            return False, f"Không nhận được '{expected_confirm}' sau {timeout}s"
        if expected_done_patterns:
            ok2, line2 = self._send_and_wait_for("", expected_done_patterns, timeout)
            if not ok2:
                return False, f"Không nhận được bất kỳ pattern nào trong {expected_done_patterns} sau {timeout}s"
            return True, line2
        return True, line

    def send_move_command(self, axis=None, position=None, is_home=False, wait_for_confirm=True, timeout=10):
        if is_home:
            cmd = "G0"
            expected_done_patterns = ["ok: homing done", "ok", "done"]
        else:
            if axis is None or position is None:
                return False, "Missing axis or position"
            cmd = f"G1 {axis}{position}"
            expected_done_patterns = ["ok: move done", "ok", "done"]

        if wait_for_confirm:
            return self.send_command_with_confirm(cmd,
                                                   expected_confirm="cmd received",
                                                   expected_done_patterns=expected_done_patterns,
                                                   timeout=timeout)
        else:
            return self.send_gcode(cmd, wait_for_done=True, timeout=timeout)

    def receive_state(self, timeout=None):
        patterns = {
            "req_homing": "req:homing",
            "req_rmlock": "req:rmlock",
            "req_auto15": "req:auto_1.5s",
            "req_auto30": "req:auto_3s",
            "snap": "snap",
            "ok": "ok",
            "finish": "finish",
            "unlock": "machine unlocked",
            "homing": "ok: homing done",
            "free": ["ok: move done", "ok: arc move done"],
            "error": "error: unknown command"
        }
        start = time.time()
        while True:
            if timeout is not None and (time.time() - start) > timeout:
                return None, None
            line = self._read_line_normalized(0.05)
            if line:
                for state, pat in patterns.items():
                    if isinstance(pat, list):
                        if any(p in line for p in pat):
                            return state, line
                    else:
                        if pat in line:
                            return state, line