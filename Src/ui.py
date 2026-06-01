import os
import cv2
import numpy as np
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import serial.tools.list_ports
import copy

# =========================================
# IMPORTS MODULES
# =========================================
from uart import UARTManager
from camera import CameraManager
from litho import CDAnalyzer

try:
    from model import ErrorDetector
except ImportError:
    messagebox.showerror("Error", "model.py not found or ultralytics not installed!")
    class ErrorDetector:
        def __init__(self, path=None): pass
        def detect(self, img): return []

# =========================================
# MAIN APP CLASS
# =========================================
class LithoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Litho & Deep Learning Inspection System")
        # Kích thước cửa sổ mặc định
        self.root.geometry("1400x900")

        # State variables
        self.history = []
        self.show_boxes = tk.BooleanVar(value=True)
        self.focused_box_id = None
        self.focused_error_id = None
        self.current_mode = "Manual"
        self.auto_timer_id = None
        self.last_snapshot_key = None

        self.photo_live = None
        self.photo_static = None

        # Process logic & image data
        self.current_image_bgr = None
        self.current_gray = None
        self.current_measurements = []
        self.current_error_boxes = []
        self.current_preprocessed_img = None
        self.current_preprocessed_mask = None
        self.calib_ratio = 1.0

        self.uart_read_thread = None
        self.stop_uart_thread = False

        # HW Initialization
        self.cam = CameraManager()
        self.uart = UARTManager()
        self.cd_analyzer = CDAnalyzer()
        self.err_detector = ErrorDetector()

        self.setup_ui()
        self._update_controls_by_mode()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

        # --- SCROLLABLE MAIN WINDOW SETUP ---
        self.main_canvas = tk.Canvas(self.root, borderwidth=0, highlightthickness=0)
        self.main_scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
        self.main_frame = ttk.Frame(self.main_canvas)

        self.main_frame.bind(
            "<Configure>",
            lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        )
        self.main_canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_scrollbar.pack(side="right", fill="y")
        self.main_canvas.pack(side="left", fill="both", expand=True)

        # Mousewheel binding
        def _on_mousewheel(event):
            if event.delta:
                self.main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            else:
                if event.num == 5:
                    self.main_canvas.yview_scroll(1, "units")
                elif event.num == 4:
                    self.main_canvas.yview_scroll(-1, "units")
        self.main_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ========== LAYOUT: SIDEBAR (LEFT) + MAIN CONTENT (RIGHT) ==========
        # Sidebar frame
        self.sidebar = ttk.Frame(self.main_frame, width=260, relief=tk.RAISED)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self.sidebar.pack_propagate(False)

        # Main content frame
        self.content = ttk.Frame(self.main_frame)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ---------------- SIDEBAR PANELS ----------------
        # 1. Connection Panel
        conn_frame = ttk.LabelFrame(self.sidebar, text="Connection", padding=8)
        conn_frame.pack(fill=tk.X, pady=5)

        ttk.Label(conn_frame, text="UART Port:").pack(anchor=tk.W)
        self.combo_ports = ttk.Combobox(conn_frame, state="readonly")
        self.combo_ports.pack(fill=tk.X, pady=2)

        self.btn_refresh_ports = ttk.Button(conn_frame, text="Refresh Ports", command=self.refresh_ports)
        self.btn_refresh_ports.pack(fill=tk.X, pady=2)

        self.btn_cam_conn = ttk.Button(conn_frame, text="Connect Camera", command=self.toggle_camera)
        self.btn_cam_conn.pack(fill=tk.X, pady=2)

        self.btn_uart_conn = ttk.Button(conn_frame, text="Connect UART", command=self.toggle_uart)
        self.btn_uart_conn.pack(fill=tk.X, pady=2)

        # 2. Camera Panel
        cam_frame = ttk.LabelFrame(self.sidebar, text="Camera", padding=8)
        cam_frame.pack(fill=tk.X, pady=5)

        self.btn_upload = ttk.Button(cam_frame, text="Load Image", command=self.upload_image)
        self.btn_upload.pack(fill=tk.X, pady=2)

        self.btn_capture = ttk.Button(cam_frame, text="Snapshot", command=self.capture_image)
        self.btn_capture.pack(fill=tk.X, pady=2)

        self.btn_live = ttk.Button(cam_frame, text="Live OFF", command=self.toggle_live, state=tk.DISABLED)
        self.btn_live.pack(fill=tk.X, pady=2)

        # 3. Analysis Panel
        ana_frame = ttk.LabelFrame(self.sidebar, text="Analysis", padding=8)
        ana_frame.pack(fill=tk.X, pady=5)

        self.btn_measure = ttk.Button(ana_frame, text="Measure CD", command=self.measure_cd)
        self.btn_measure.pack(fill=tk.X, pady=2)

        self.btn_detect = ttk.Button(ana_frame, text="Detect Defects", command=self.detect_errors)
        self.btn_detect.pack(fill=tk.X, pady=2)

        self.btn_clear = ttk.Button(ana_frame, text="Clear All", command=self.clear_data)
        self.btn_clear.pack(fill=tk.X, pady=2)

        self.show_boxes_cb = ttk.Checkbutton(ana_frame, text="Show Boxes", variable=self.show_boxes, command=self._draw_boxes_on_static)
        self.show_boxes_cb.pack(anchor=tk.W, pady=5)

        scale_frame = ttk.Frame(ana_frame)
        scale_frame.pack(fill=tk.X, pady=2)
        self.entry_ratio = ttk.Entry(scale_frame, width=8)
        self.entry_ratio.insert(0, "1.0")
        self.entry_ratio.pack(side=tk.LEFT, padx=2)
        ttk.Label(scale_frame, text="µm/px").pack(side=tk.LEFT, padx=2)
        self.btn_update_ratio = ttk.Button(scale_frame, text="Set", width=5, command=self.update_ratio)
        self.btn_update_ratio.pack(side=tk.LEFT, padx=2)

        ttk.Label(ana_frame, text="Mode:").pack(anchor=tk.W, pady=(5,0))
        self.combo_mode = ttk.Combobox(ana_frame, values=["Manual", "Auto 1m30s", "Auto 2m"], state="readonly")
        self.combo_mode.current(0)
        self.combo_mode.bind("<<ComboboxSelected>>", self.on_mode_changed)
        self.combo_mode.pack(fill=tk.X, pady=2)

        # 4. Motion Control Panel
        motion_frame = ttk.LabelFrame(self.sidebar, text="Motion Control", padding=8)
        motion_frame.pack(fill=tk.X, pady=5)

        btn_grid = ttk.Frame(motion_frame)
        btn_grid.pack(pady=5)

        self.btn_up = ttk.Button(btn_grid, text="↑", width=5, command=lambda: self.move_axis('Y-'))
        self.btn_down = ttk.Button(btn_grid, text="↓", width=5, command=lambda: self.move_axis('Y+'))
        self.btn_left = ttk.Button(btn_grid, text="←", width=5, command=lambda: self.move_axis('X-'))
        self.btn_right = ttk.Button(btn_grid, text="→", width=5, command=lambda: self.move_axis('X+'))
        self.btn_z_up = ttk.Button(btn_grid, text="Z+", width=5, command=lambda: self.move_axis('Z+'))
        self.btn_z_down = ttk.Button(btn_grid, text="Z-", width=5, command=lambda: self.move_axis('Z-'))
        self.btn_home = ttk.Button(btn_grid, text="Home", width=5, command=lambda: self.move_axis('home'))

        self.btn_up.grid(row=0, column=1, pady=2)
        self.btn_left.grid(row=1, column=0, padx=2)
        self.btn_home.grid(row=1, column=1, padx=2)
        self.btn_right.grid(row=1, column=2, padx=2)
        self.btn_down.grid(row=2, column=1, pady=2)
        self.btn_z_up.grid(row=0, column=3, padx=(12,2))
        self.btn_z_down.grid(row=2, column=3, padx=(12,2))

        # Step frames
        step_x_frame = ttk.Frame(motion_frame)
        step_x_frame.pack(fill=tk.X, pady=2)
        ttk.Label(step_x_frame, text="Step X:").pack(side=tk.LEFT)
        self.entry_step_x = ttk.Entry(step_x_frame, width=8)
        self.entry_step_x.insert(0, "10.0")
        self.entry_step_x.pack(side=tk.RIGHT, padx=5)

        step_y_frame = ttk.Frame(motion_frame)
        step_y_frame.pack(fill=tk.X, pady=2)
        ttk.Label(step_y_frame, text="Step Y:").pack(side=tk.LEFT)
        self.entry_step_y = ttk.Entry(step_y_frame, width=8)
        self.entry_step_y.insert(0, "10.0")
        self.entry_step_y.pack(side=tk.RIGHT, padx=5)

        step_z_frame = ttk.Frame(motion_frame)
        step_z_frame.pack(fill=tk.X, pady=2)
        ttk.Label(step_z_frame, text="Step Z:").pack(side=tk.LEFT)
        self.entry_step_z = ttk.Entry(step_z_frame, width=8)
        self.entry_step_z.insert(0, "1.0")
        self.entry_step_z.pack(side=tk.RIGHT, padx=5)

        # ---------------- MAIN CONTENT ----------------
        # Row 1: Two canvases (Live + Static) with fixed size 640x480
        row_canvases = ttk.Frame(self.content)
        row_canvases.pack(fill=tk.BOTH, expand=True, pady=5)

        frame_live = ttk.LabelFrame(row_canvases, text="Live View")
        frame_live.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.canvas_live = tk.Canvas(frame_live, bg="black", width=640, height=480)
        self.canvas_live.pack(anchor=tk.CENTER, padx=5, pady=5)

        frame_static = ttk.LabelFrame(row_canvases, text="Static View")
        frame_static.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.canvas_static = tk.Canvas(frame_static, bg="black", width=640, height=480)
        self.canvas_static.pack(anchor=tk.CENTER, padx=5, pady=5)

        # Row 2: Comparison Table
        self.tree_stats = ttk.Treeview(self.content, columns=("Metric", "Original", "Processed"), show='headings', height=3)
        self.tree_stats.heading("Metric", text="Metric")
        self.tree_stats.heading("Original", text="Original (pixel)")
        self.tree_stats.heading("Processed", text="Processed (subpixel)")
        self.tree_stats.column("Metric", width=200, anchor=tk.W)
        self.tree_stats.column("Original", width=150, anchor=tk.CENTER)
        self.tree_stats.column("Processed", width=150, anchor=tk.CENTER)
        self.tree_stats.pack(fill=tk.X, pady=5)
        self._reset_stats_table()

        # Row 3: Notebook (Original, Processed, Defects)
        self.notebook = ttk.Notebook(self.content)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=5)

        f_orig = ttk.Frame(self.notebook)
        self.notebook.add(f_orig, text="Original")
        self.tree_orig = self._create_tree(f_orig, ("ID", "CD (pixel)", "CD (µm)", "Status"))
        self.tree_orig.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_box(self.tree_orig))

        f_pre = ttk.Frame(self.notebook)
        self.notebook.add(f_pre, text="Processed")
        self.tree_pre = self._create_tree(f_pre, ("ID", "CD (subpixel)", "CD (µm)", "Status"))
        self.tree_pre.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_box(self.tree_pre))

        f_err = ttk.Frame(self.notebook)
        self.notebook.add(f_err, text="Defects")
        self.tree_err = self._create_tree(f_err, ("Error ID", "Affected Box ID", "Coordinates", "Class"))
        self.tree_err.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_err(self.tree_err))

        # Row 4: History
        frame_hist = ttk.LabelFrame(self.content, text="History (double-click to restore)")
        frame_hist.pack(fill=tk.X, pady=5)
        self.list_history = tk.Listbox(frame_hist, height=4)
        sb = ttk.Scrollbar(frame_hist, orient=tk.VERTICAL, command=self.list_history.yview)
        self.list_history.config(yscrollcommand=sb.set)
        self.list_history.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_history.bind("<Double-Button-1>", self.on_history_restore)

        # Status bar
        self.lbl_status = ttk.Label(self.main_frame, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.lbl_status.pack(side=tk.BOTTOM, fill=tk.X)

        self.refresh_ports()

    def _create_tree(self, parent, cols):
        tree = ttk.Treeview(parent, columns=cols, show='headings', height=5)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, anchor=tk.CENTER)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return tree

    # =========================================
    # CORE LOGIC: HARDWARE (giữ nguyên)
    # =========================================
    def refresh_ports(self):
        all_ports = [port.device for port in serial.tools.list_ports.comports()]
        self.combo_ports['values'] = all_ports
        if all_ports:
            self.combo_ports.current(0)
            self.set_status(f"Found {len(all_ports)} port(s). Scanning for active device...")
            threading.Thread(target=self._scan_and_auto_select, daemon=True).start()
        else:
            self.set_status("No serial ports found.")

    def _scan_and_auto_select(self):
        try:
            responding = UARTManager.scan_responding_ports(baudrate=115200, timeout=0.5)
            if responding:
                port = responding[0]
                self.root.after(0, lambda: self._select_active_port(port))
            else:
                self.root.after(0, lambda: self.set_status("No responding UART device found."))
        except Exception as e:
            print(f"[UI_DEBUG] Scan error: {e}")

    def _select_active_port(self, port):
        self.combo_ports.set(port)
        self.set_status(f"Active device at {port}. Click 'Connect UART'.")

    def toggle_uart(self):
        if self.uart.is_connected():
            self.uart.disconnect()
            self.btn_uart_conn.config(text="Connect UART")
            self.stop_uart_thread = True
            self.set_status("UART Disconnected.")
        else:
            port = self.combo_ports.get()
            if not port:
                messagebox.showerror("Error", "Select a COM port!")
                return
            self.uart.port = port
            if self.uart.connect():
                self.btn_uart_conn.config(text="Disconnect UART")
                self.stop_uart_thread = False
                self.uart_read_thread = threading.Thread(target=self._uart_read_loop, daemon=True)
                self.uart_read_thread.start()
                self.set_status(f"UART Connected to {port}.")
            else:
                messagebox.showerror("Error", "Failed to connect UART!")

    def _uart_read_loop(self):
        while not self.stop_uart_thread and self.uart.is_connected():
            try:
                if self.uart.ser and self.uart.ser.in_waiting:
                    line = self.uart.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line.startswith("MODE:"):
                        mode_str = line.split(":", 1)[1].strip()
                        self.root.after(0, lambda m=mode_str: self._sync_mode_from_uart(m))
            except Exception:
                pass

    def _sync_mode_from_uart(self, mode_str):
        if "Manual" in mode_str:
            self.combo_mode.current(0)
        elif "1m30s" in mode_str:
            self.combo_mode.current(1)
        elif "2m" in mode_str:
            self.combo_mode.current(2)
        self.on_mode_changed(None, send_uart=False)

    def toggle_camera(self):
        if self.btn_cam_conn.cget("text") == "Connect Camera":
            if self.cam.refresh_devices() > 0 and self.cam.connect(0):
                self.btn_cam_conn.config(text="Disconnect Camera")
                self.btn_live.config(state=tk.NORMAL)
                self.set_status("Camera Connected.")
            else:
                messagebox.showerror("Error", "Camera not found!")
        else:
            if self.cam.is_live:
                self.toggle_live()
            self.cam.disconnect()
            self.btn_cam_conn.config(text="Connect Camera")
            self.btn_live.config(state=tk.DISABLED)
            self.set_status("Camera Disconnected.")

    def toggle_live(self):
        if not self.cam.is_live:
            self.cam.start_live(self._live_callback)
            self.btn_live.config(text="Live ON")
        else:
            self.cam.stop_live()
            self.btn_live.config(text="Live OFF")
            self.canvas_live.delete("all")

    def _live_callback(self, frame):
        self.root.after(0, self._show_image_on_canvas, frame, self.canvas_live)

    def move_axis(self, direction):
        if self.current_mode != "Manual":
            return
        if not self.uart.is_connected():
            messagebox.showerror("Error", "UART not connected!")
            return
        try:
            step_x = float(self.entry_step_x.get())
            step_y = float(self.entry_step_y.get())
            step_z = float(self.entry_step_z.get())
        except ValueError:
            step_x = step_y = 10.0
            step_z = 1.0

        cmd = ""
        if direction == 'X+':
            cmd = f"G1 X{step_x}"
        elif direction == 'X-':
            cmd = f"G1 X-{step_x}"
        elif direction == 'Y+':
            cmd = f"G1 Y{step_y}"
        elif direction == 'Y-':
            cmd = f"G1 Y-{step_y}"
        elif direction == 'Z+':
            cmd = f"G1 Z{step_z}"
        elif direction == 'Z-':
            cmd = f"G1 Z-{step_z}"
        elif direction == 'home':
            self.uart.home()
            return

        if cmd:
            self.set_status(f"Moving {direction}...")
            threading.Thread(target=self._send_uart_cmd, args=(cmd,), daemon=True).start()

    def _send_uart_cmd(self, cmd):
        if self.uart.is_connected():
            success, response = self.uart.send_gcode(cmd, wait_for_done=False)
            msg = f"Moved: {response}" if success else f"UART error: {response}"
            self.root.after(0, lambda: self.set_status(msg))
        else:
            self.root.after(0, lambda: self.set_status("UART not connected."))

    def on_mode_changed(self, event=None, send_uart=True):
        self.current_mode = self.combo_mode.get()
        if send_uart and self.uart.is_connected():
            code = 0 if self.current_mode == "Manual" else (1 if "1m30s" in self.current_mode else 2)
            self.uart.send_gcode(f"M99 P{code}", wait_for_done=False)
        self._update_controls_by_mode()
        if self.current_mode == "Manual":
            if self.auto_timer_id:
                self.root.after_cancel(self.auto_timer_id)
                self.auto_timer_id = None
            self.set_status("Manual Mode selected.")

    def _update_controls_by_mode(self):
        state = tk.NORMAL if self.current_mode == "Manual" else tk.DISABLED
        for btn in [self.btn_measure, self.btn_detect, self.btn_upload, self.btn_capture]:
            btn.config(state=state)
        for btn in [self.btn_up, self.btn_down, self.btn_left, self.btn_right,
                    self.btn_z_up, self.btn_z_down, self.btn_home]:
            btn.config(state=state)

    # =========================================
    # CORE LOGIC: IMAGE & PROCESSING (giữ nguyên)
    # =========================================
    def upload_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.png *.bmp")])
        if path:
            img = cv2.imread(path)
            if img is not None:
                self._set_current_image(img)

    def capture_image(self):
        def _task():
            success, img = False, None
            if self.cam.is_live:
                img = self.cam.get_last_frame()
                success = img is not None
            else:
                success, img = self.cam.capture_single()
            if success and img is not None:
                self.root.after(0, self._on_capture_success, img)
            else:
                self.root.after(0, lambda: messagebox.showerror("Error", "Failed to capture image!"))
        threading.Thread(target=_task, daemon=True).start()

    def _on_capture_success(self, img_bgr):
        self._set_current_image(img_bgr)
        self.set_status("Capture success.")
        if self.current_mode != "Manual":
            self.root.after(500, self._auto_sequence_measure)

    def _set_current_image(self, img_bgr):
        self.current_image_bgr = img_bgr.copy()
        if len(img_bgr.shape) == 3:
            self.current_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        else:
            self.current_gray = img_bgr.copy()
            self.current_image_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
        self.current_measurements = []
        self.current_error_boxes = []
        self.current_preprocessed_mask = None
        self.focused_box_id = None
        self.focused_error_id = None
        self.last_snapshot_key = None
        self.tree_orig.delete(*self.tree_orig.get_children())
        self.tree_pre.delete(*self.tree_pre.get_children())
        self.tree_err.delete(*self.tree_err.get_children())
        self._reset_stats_table()
        self._draw_boxes_on_static()

    def measure_cd(self):
        if self.current_gray is None:
            return
        self.set_status("Analyzing Litho...")
        def _task():
            res = self.cd_analyzer.analyze(self.current_gray)
            self.root.after(0, self._on_measure_done, res)
        threading.Thread(target=_task, daemon=True).start()

    def _on_measure_done(self, res):
        if res.get('success', False):
            self.current_measurements = copy.deepcopy(res['measurements'])
            self.current_preprocessed_img = res.get('preprocessed_img')
            self.current_preprocessed_mask = res.get('mask_clean')
            self._update_measurements_status()
            self._update_ui_after_processing()
            self._add_to_history()
            self.set_status("CD measurement complete.")
        else:
            self.set_status("CD measurement failed.")

    def detect_errors(self):
        if self.current_gray is None:
            return
        self.set_status("Detecting defects using AI...")
        def _task():
            boxes = self.err_detector.detect(self.current_gray)
            self.root.after(0, self._on_detect_done, boxes)
        threading.Thread(target=_task, daemon=True).start()

    def _on_detect_done(self, boxes):
        self.current_error_boxes = copy.deepcopy(boxes)
        self._update_measurements_status()
        self._update_ui_after_processing()
        self._add_to_history()
        self.set_status(f"Detected {len(boxes)} defect(s).")

    def _auto_sequence_measure(self):
        if self.current_mode == "Manual":
            return
        def _task():
            res = self.cd_analyzer.analyze(self.current_gray)
            self.root.after(0, self._auto_sequence_detect, res)
        threading.Thread(target=_task, daemon=True).start()

    def _auto_sequence_detect(self, res_litho):
        if self.current_mode == "Manual":
            return
        if res_litho.get('success'):
            self.current_measurements = res_litho['measurements']
            self.current_preprocessed_mask = res_litho.get('mask_clean')
        def _task():
            err = self.err_detector.detect(self.current_gray)
            self.root.after(0, self._auto_sequence_finish, err)
        threading.Thread(target=_task, daemon=True).start()

    def _auto_sequence_finish(self, err_boxes):
        if self.current_mode == "Manual":
            return
        self.current_error_boxes = err_boxes
        self._update_measurements_status()
        self._update_ui_after_processing()
        self._add_to_history()
        delay = 90000 if "1m30s" in self.current_mode else 120000
        self.set_status(f"Auto mode: Next capture in {delay//1000}s...")
        self.auto_timer_id = self.root.after(delay, self.capture_image)

    # =========================================
    # LOGIC: STATUS, IOU, DRAWING & TABLES
    # =========================================
    def _update_measurements_status(self):
        if self.current_image_bgr is None:
            return
        H, W = self.current_image_bgr.shape[:2]
        def iou_overlap(b1, b2):
            xl, yt = max(b1[0], b2[0]), max(b1[1], b2[1])
            xr, yb = min(b1[0]+b1[2], b2[0]+b2[2]), min(b1[1]+b1[3], b2[1]+b2[3])
            return max(0, xr - xl) * max(0, yb - yt) > 0
        for m in self.current_measurements:
            m['is_valid'] = True
            m['status'] = "Ok"
            m['affected_by'] = []
            pt1, pt2 = m.get('pt1'), m.get('pt2')
            if pt1 and pt2:
                for pt in [pt1, pt2]:
                    if pt[0] < 1 or pt[1] < 1 or pt[0] > W-2 or pt[1] > H-2:
                        m['is_valid'] = False
                        m['status'] = "Fail (Boundary)"
            box_m = m.get('bbox')
            if box_m:
                for i, err in enumerate(self.current_error_boxes):
                    box_e = err[:4]
                    if iou_overlap(box_m, box_e):
                        m['is_valid'] = False
                        m['status'] = "Fail (Defect)"
                        m['affected_by'].append(i)

    def _update_ui_after_processing(self):
        self.tree_orig.delete(*self.tree_orig.get_children())
        self.tree_pre.delete(*self.tree_pre.get_children())
        self.tree_err.delete(*self.tree_err.get_children())
        for i, m in enumerate(self.current_measurements):
            cd_px = m.get('cd_pixel', 0)
            sub_px = m.get('subpixel_cd', cd_px)
            cd_um_orig = cd_px * self.calib_ratio
            cd_um_pre = sub_px * self.calib_ratio
            stat = m.get('status', 'Ok')
            self.tree_orig.insert('', tk.END, values=(i, cd_px, f"{cd_um_orig:.3f}", stat))
            self.tree_pre.insert('', tk.END, values=(i, f"{sub_px:.3f}", f"{cd_um_pre:.3f}", stat))
        for i, err in enumerate(self.current_error_boxes):
            box = err[:4]
            aff = [str(mid) for mid, m in enumerate(self.current_measurements) if i in m.get('affected_by', [])]
            aff_str = ",".join(aff) if aff else "None"
            cls_id = err[5] if len(err) > 5 else 0
            self.tree_err.insert('', tk.END, values=(i, aff_str, f"({box[0]},{box[1]},{box[2]},{box[3]})", cls_id))
        self.tree_stats.delete(*self.tree_stats.get_children())
        valid_m = [m for m in self.current_measurements if m.get('is_valid')]
        tot_boxes = len(self.current_measurements)
        avg_orig = np.mean([m.get('cd_pixel', 0) for m in valid_m]) * self.calib_ratio if valid_m else 0
        avg_pre = np.mean([m.get('subpixel_cd', m.get('cd_pixel', 0)) for m in valid_m]) * self.calib_ratio if valid_m else 0
        area = 0
        if self.current_preprocessed_mask is not None:
            area = np.count_nonzero(self.current_preprocessed_mask) * (self.calib_ratio ** 2)
        self.tree_stats.insert('', tk.END, values=("Total Boxes (valid/total)", f"{len(valid_m)} / {tot_boxes}", f"{len(valid_m)} / {tot_boxes}"))
        self.tree_stats.insert('', tk.END, values=("Avg CD Width (µm)", f"{avg_orig:.3f}", f"{avg_pre:.3f}"))
        self.tree_stats.insert('', tk.END, values=("Total Litho Area (µm²)", f"{area:.3f}", f"{area:.3f}"))
        self._draw_boxes_on_static()

    def update_ratio(self):
        try:
            val = float(self.entry_ratio.get())
            if val <= 0:
                raise ValueError
            self.calib_ratio = val
            self.cd_analyzer.calibration = val
            if self.current_measurements:
                self._update_ui_after_processing()
            messagebox.showinfo("Success", "Scale updated!")
        except ValueError:
            messagebox.showerror("Error", "Invalid scale value!")

    def on_tree_click_box(self, tree):
        sel = tree.selection()
        if not sel:
            return
        item = tree.item(sel[0])
        self.focused_box_id = int(item['values'][0])
        self.focused_error_id = None
        self._draw_boxes_on_static()

    def on_tree_click_err(self, tree):
        sel = tree.selection()
        if not sel:
            return
        item = tree.item(sel[0])
        self.focused_error_id = int(item['values'][0])
        self.focused_box_id = None
        self._draw_boxes_on_static()

    def _draw_boxes_on_static(self):
        if self.current_image_bgr is None:
            return
        img_draw = self.current_image_bgr.copy()
        if self.show_boxes.get():
            for i, m in enumerate(self.current_measurements):
                if self.focused_box_id is not None and self.focused_box_id != i:
                    continue
                if self.focused_error_id is not None and self.focused_error_id not in m.get('affected_by', []):
                    continue
                box = m.get('bbox')
                if box:
                    x, y, w, h = box
                    color = (0, 255, 0) if m.get('is_valid') else (0, 255, 255)
                    cv2.rectangle(img_draw, (x, y), (x+w, y+h), color, 2)
                    cv2.putText(img_draw, str(i), (x, max(10, y-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                pt1, pt2 = m.get('pt1'), m.get('pt2')
                if pt1 and pt2:
                    cv2.line(img_draw, (int(pt1[0]), int(pt1[1])), (int(pt2[0]), int(pt2[1])), (0, 0, 255), 2)
            for i, err in enumerate(self.current_error_boxes):
                if self.focused_error_id is not None and self.focused_error_id != i:
                    continue
                if self.focused_box_id is not None:
                    m_focused = self.current_measurements[self.focused_box_id]
                    if i not in m_focused.get('affected_by', []):
                        continue
                x, y, w, h = err[:4]
                cv2.rectangle(img_draw, (int(x), int(y)), (int(x+w), int(y+h)), (0, 0, 255), 2)
                cv2.putText(img_draw, f"ERR {i}", (int(x), max(10, int(y)-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        self._show_image_on_canvas(img_draw, self.canvas_static)

    def _show_image_on_canvas(self, img_bgr, canvas, max_w=640, max_h=480):
        h, w = img_bgr.shape[:2]
        scale = min(max_w / max(w, 1), max_h / max(h, 1))
        new_w, new_h = int(w * scale), int(h * scale)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img_res = cv2.resize(img_rgb, (new_w, new_h))
        photo = ImageTk.PhotoImage(image=Image.fromarray(img_res))
        canvas.delete("all")
        canvas.create_image(max_w//2, max_h//2, anchor=tk.CENTER, image=photo)
        if canvas == self.canvas_live:
            self.photo_live = photo
        else:
            self.photo_static = photo

    # =========================================
    # HISTORY & UTILITIES
    # =========================================
    def _add_to_history(self):
        if not self.current_measurements:
            return
        n_meas = len(self.current_measurements)
        n_err = len(self.current_error_boxes)
        current_key = (n_meas, n_err)
        if self.last_snapshot_key == current_key:
            return
        self.last_snapshot_key = current_key
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        valid_m = [m for m in self.current_measurements if m.get('is_valid')]
        avg_o = np.mean([m.get('cd_pixel', 0) for m in valid_m]) * self.calib_ratio if valid_m else 0
        avg_p = np.mean([m.get('subpixel_cd', m.get('cd_pixel', 0)) for m in valid_m]) * self.calib_ratio if valid_m else 0
        err_c = len(self.current_error_boxes)
        snap = {
            'timestamp': ts,
            'image_bgr': self.current_image_bgr.copy(),
            'gray': self.current_gray.copy(),
            'measurements': copy.deepcopy(self.current_measurements),
            'error_boxes': copy.deepcopy(self.current_error_boxes),
            'mask': self.current_preprocessed_mask.copy() if self.current_preprocessed_mask is not None else None,
            'calib_ratio': self.calib_ratio,
            'avg_o': avg_o,
            'avg_p': avg_p,
            'err_c': err_c
        }
        self.history.append(snap)
        display_str = f"{ts} | Orig CD: {avg_o:.3f}µm | Pre CD: {avg_p:.3f}µm | Defects: {err_c}"
        self.list_history.insert(tk.END, display_str)
        self.list_history.yview(tk.END)

    def on_history_restore(self, event):
        sel = self.list_history.curselection()
        if not sel:
            return
        idx = sel[0]
        snap = self.history[idx]
        self.current_image_bgr = snap['image_bgr'].copy()
        self.current_gray = snap['gray'].copy()
        self.current_measurements = copy.deepcopy(snap['measurements'])
        self.current_error_boxes = copy.deepcopy(snap['error_boxes'])
        self.current_preprocessed_mask = snap['mask'].copy() if snap['mask'] is not None else None
        self.calib_ratio = snap['calib_ratio']
        self.entry_ratio.delete(0, tk.END)
        self.entry_ratio.insert(0, str(self.calib_ratio))
        self.cd_analyzer.calibration = self.calib_ratio
        self.focused_box_id = None
        self.focused_error_id = None
        self._update_ui_after_processing()
        self.set_status(f"Restored from {snap['timestamp']}.")

    def _reset_stats_table(self):
        self.tree_stats.delete(*self.tree_stats.get_children())
        self.tree_stats.insert('', tk.END, values=("Total Boxes (valid/total)", "0 / 0", "0 / 0"))
        self.tree_stats.insert('', tk.END, values=("Avg CD Width (µm)", "0.000", "0.000"))
        self.tree_stats.insert('', tk.END, values=("Total Litho Area (µm²)", "0.000", "0.000"))

    def clear_data(self):
        if messagebox.askyesno("Confirm", "Clear all working data?"):
            self.current_image_bgr = None
            self.current_gray = None
            self.current_measurements = []
            self.current_error_boxes = []
            self.current_preprocessed_mask = None
            self.history = []
            self.last_snapshot_key = None
            self.list_history.delete(0, tk.END)
            self.canvas_static.delete("all")
            self.tree_orig.delete(*self.tree_orig.get_children())
            self.tree_pre.delete(*self.tree_pre.get_children())
            self.tree_err.delete(*self.tree_err.get_children())
            self._reset_stats_table()
            if self.auto_timer_id:
                self.root.after_cancel(self.auto_timer_id)
                self.auto_timer_id = None
            self.set_status("Data cleared.")

    def set_status(self, msg):
        self.lbl_status.config(text=msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = LithoApp(root)
    root.mainloop()