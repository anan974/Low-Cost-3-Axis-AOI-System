# uart.py
import serial
import time
import os
import serial.tools.list_ports
import threading
from queue import Queue, Empty

class UARTManager:
    def __init__(self, port=None, baudrate=115200, timeout=1):
        self.port = port if port else ('/dev/ttyAMA0' if os.name != 'nt' else 'COM11')
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self._read_thread = None
        self._stop_event = threading.Event()
        # Queue để gửi lệnh và chờ phản hồi (thay cho pause_reading)
        self._cmd_queue = Queue()
        self._response_events = {}  # mapping command_id -> threading.Event
        self._response_data = {}    # mapping command_id -> response string
        self._next_cmd_id = 0
        self._cmd_lock = threading.Lock()
        # Tín hiệu state (cho receive_state)
        self._state_queue = Queue(maxsize=50)

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(2)
            self._stop_event.clear()
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
            return True
        except Exception as e:
            print(f"[UART] Connect fail: {e}")
            return False

    def disconnect(self):
        self._stop_event.set()
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1)
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def _read_loop(self):
        """Luồng đọc liên tục, không bao giờ pause."""
        while not self._stop_event.is_set():
            if not self.ser or not self.ser.is_open:
                time.sleep(0.1)
                continue
            try:
                if self.ser.in_waiting:
                    raw = self.ser.readline()
                    line = raw.decode('utf-8', errors='ignore').strip().lower()
                    line = line.replace('\r', '').replace('\n', '').replace('\x00', '')
                    if line:
                        print(f"[UART_RX] {line}")
                        # Gửi vào queue state cho receive_state
                        try:
                            self._state_queue.put_nowait(line)
                        except:
                            pass
                        # Kiểm tra xem có command nào đang chờ phản hồi này không
                        self._match_response(line)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"[UART] Read error: {e}")
                time.sleep(0.1)

    def _match_response(self, line):
        """Duyệt các event đang chờ, nếu khớp thì set."""
        with self._cmd_lock:
            to_remove = []
            for cmd_id, (event, expected_patterns, timeout_time) in list(self._response_events.items()):
                for pat in expected_patterns:
                    if pat in line:
                        self._response_data[cmd_id] = line
                        event.set()
                        to_remove.append(cmd_id)
                        break
                # Nếu timeout, cũng xóa
                if time.time() > timeout_time:
                    event.set()  # đánh thức với timeout
                    to_remove.append(cmd_id)
            for cmd_id in to_remove:
                del self._response_events[cmd_id]

    def send_command_with_confirm(self, cmd, expected_confirm="cmd received",
                                   expected_done_patterns=None, timeout=10):
        """
        Gửi lệnh và chờ confirm + done (nếu có). Dùng Event thay vì busy loop.
        Trả về (success, response_string).
        """
        if not self.is_connected():
            return False, "Not connected"

        with self._cmd_lock:
            cmd_id = self._next_cmd_id
            self._next_cmd_id += 1
            # Tạo event riêng cho lệnh này
            event = threading.Event()
            # Chờ confirm
            self._response_events[cmd_id] = (event, [expected_confirm], time.time() + timeout)
        # Gửi lệnh
        full_cmd = cmd.strip() + "\n"
        self.ser.write(full_cmd.encode())
        print(f"[UART] -> {full_cmd.strip()}")
        # Chờ event
        event.wait(timeout)
        with self._cmd_lock:
            if cmd_id not in self._response_data:
                return False, f"Timeout waiting for '{expected_confirm}'"
            confirm_line = self._response_data.pop(cmd_id)
            # Xóa event khỏi dict (đã được xóa trong _match_response, nhưng đảm bảo)
            self._response_events.pop(cmd_id, None)

        # Nếu cần chờ thêm done patterns
        if expected_done_patterns:
            with self._cmd_lock:
                event2 = threading.Event()
                cmd_id2 = self._next_cmd_id
                self._next_cmd_id += 1
                self._response_events[cmd_id2] = (event2, expected_done_patterns, time.time() + timeout)
            event2.wait(timeout)
            with self._cmd_lock:
                if cmd_id2 not in self._response_data:
                    return False, f"Timeout waiting for done patterns {expected_done_patterns}"
                done_line = self._response_data.pop(cmd_id2)
                self._response_events.pop(cmd_id2, None)
                return True, done_line
        return True, confirm_line

    def send_gcode(self, gcode, wait_for_done=True, timeout=10):
        """Giữ nguyên interface cũ, gọi send_command_with_confirm"""
        if wait_for_done:
            return self.send_command_with_confirm(gcode,
                                                   expected_confirm="cmd received",
                                                   expected_done_patterns=["done", "ok"],
                                                   timeout=timeout)
        else:
            if not self.is_connected():
                return False, "Not connected"
            self.ser.write((gcode.strip() + "\n").encode())
            return True, "sent"

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
        """
        Lấy trạng thái từ queue (non-blocking nếu timeout=0, blocking nếu timeout>0)
        Trả về (state_string, line) với state là tên rút gọn như cũ.
        """
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
        try:
            line = self._state_queue.get(timeout=timeout if timeout is not None else 0.1)
        except Empty:
            return None, None
        for state, pat in patterns.items():
            if isinstance(pat, list):
                if any(p in line for p in pat):
                    return state, line
            else:
                if pat in line:
                    return state, line
        return None, line

    # Các hàm cũ được giữ nguyên (home, move_to, run_rotation_sequence, scan_responding_ports, auto_connect)
    def home(self):
        return self.send_gcode("G0", wait_for_done=True)

    def move_to(self, angle_deg):
        return self.send_gcode(f"G1 Z{angle_deg}", wait_for_done=True)

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