import cv2
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import threading
import os
import datetime
import ctypes
import litho
from ultralytics import YOLO 
import os
from MvImport.MvCameraControl_class import *

# ==============================================================================
# HÀM HỖ TRỢ CHUNG (UTILITY FUNCTIONS)
# ==============================================================================
def get_iou(bb1, bb2):
    x_left = max(bb1[0], bb2[0])
    y_top = max(bb1[1], bb2[1])
    x_right = min(bb1[0]+bb1[2], bb2[0]+bb2[2])
    y_bottom = min(bb1[1]+bb1[3], bb2[1]+bb2[3])
    
    if x_right < x_left or y_bottom < y_top:
        return 0.0
        
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    bb1_area = bb1[2] * bb1[3]
    bb2_area = bb2[2] * bb2[3]
    iou = intersection_area / float(bb1_area + bb2_area - intersection_area)
    return iou

# ==============================================================================
# LỚP CHÍNH: INDUSTRIAL INSPECTION UI
# ==============================================================================
class IndustrialInspectionUI:
    def __init__(self, root):
        """
        Khởi tạo các thông số trạng thái, biến quản lý camera và giao diện
        """
        self.root = root
        self.root.title("Hệ thống Kiểm tra Vi mạch (Litho Mode)")
        self.root.state('zoomed')
        
        # --- QUẢN LÝ TRẠNG THÁI (STATE MANAGEMENT) ---
        self.current_img_orig = None
        self.current_img_gray = None
        self.img_balanced = None
        self.processed_mask = None
        self.raw_mask = None 
        self.current_file_path = ""
        
        self.pixel_to_um = 1.0
        
        self.boxes_orig = [] 
        self.boxes_proc = [] 

        # --- QUẢN LÝ MÔ HÌNH PHÁT HIỆN LỖI (YOLO) ---:
        self.model_path = r'runs/content/runs/detect/train-7/weights/best.pt' 
        self.error_model = YOLO(self.model_path)
        self.error_boxes = [] 
        
        # --- QUẢN LÝ CAMERA ---
        self.cam = None
        self.is_live_running = False
        self.latest_frame = None
        
        # Quản lý Tab đang hiển thị (0: Gốc, 1: Tiền xử lý)
        self.current_view_tab = 0
        
        # Quản lý Lịch sử mẫu (History)
        self.sample_history = [] 
        self.current_sample_idx = -1
        
        # Trạng thái hiển thị Canvas
        self.is_showing_all = False
        self.ui_scale_factors = {}
        self.canvas_offsets = {}
        
        self.setup_ui()
        
    # ==============================================================================
    # KHỞI TẠO GIAO DIỆN (UI SETUP)
    # ==============================================================================
    def setup_ui(self):
        """
        Xây dựng toàn bộ giao diện phần mềm bao gồm thanh công cụ bên trái,
        màn hình hiển thị trung tâm, và bảng dữ liệu bên dưới.
        """
        # ==================== 1. SIDEBAR LEFT ====================
        sidebar = ttk.Frame(self.root, padding="10", relief="flat", width=400)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False) 

        ttk.Label(sidebar, text="BẢNG ĐIỀU KHIỂN (LITHO)", font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        
        # --- 1. CHỌN CHẾ ĐỘ HOẠT ĐỘNG ---
        mode_frame = ttk.LabelFrame(sidebar, text="Chế độ hoạt động", padding=5)
        mode_frame.pack(fill=tk.X, pady=5)
        
        self.var_op_mode = tk.StringVar(value="Manual")
        modes = ["Calib mode", "Auto 1s", "Auto 1.5s", "Auto 2s", "Manual"]
        
        for i, mode in enumerate(modes):
            ttk.Radiobutton(mode_frame, text=mode, variable=self.var_op_mode, value=mode, command=self.on_mode_change).grid(row=i//2, column=i%2, sticky=tk.W, padx=5, pady=2)
            
        # --- 2. CÁC NÚT MANUAL (CHỈ ACTIVE KHI Ở MANUAL MODE) ---
        self.manual_btn_frame = ttk.LabelFrame(sidebar, text="Chức năng Thủ công (Manual)", padding=5)
        self.manual_btn_frame.pack(fill=tk.X, pady=5)
        
        # Cụm nút Live & Chụp ảnh
        cam_frame = ttk.Frame(self.manual_btn_frame)
        cam_frame.pack(fill=tk.X, pady=2)
        self.btn_live = ttk.Button(cam_frame, text="🔴 Bật Live Camera", command=self.toggle_live_camera)
        self.btn_live.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_capture = ttk.Button(cam_frame, text="📸 Chụp ảnh", command=self.capture_image)
        self.btn_capture.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))
        
        self.btn_load = ttk.Button(self.manual_btn_frame, text="Tải ảnh từ máy", command=self.load_image)
        self.btn_load.pack(fill=tk.X, pady=2)
        
        self.btn_detect = ttk.Button(self.manual_btn_frame, text="🔍 Xác định vùng mục tiêu", command=self.run_detection)
        self.btn_detect.pack(fill=tk.X, pady=2)
        
        self.btn_measure = ttk.Button(self.manual_btn_frame, text="📏 Đo CD Line Width", command=self.run_measurement)
        self.btn_measure.pack(fill=tk.X, pady=2)

        btn_detect_err = ttk.Button(self.manual_btn_frame, text="🔍 Phát hiện Lỗi", command=self.run_error_detection)
        btn_detect_err.pack(pady=5, fill=tk.X)

        # Cấu hình Tỉ lệ
        f_ratio = ttk.Frame(sidebar)
        f_ratio.pack(fill=tk.X, pady=5)
        ttk.Label(f_ratio, text="Tỉ lệ (um/pixel):", width=15).pack(side=tk.LEFT)
        self.txt_ratio = ttk.Entry(f_ratio, width=10)
        self.txt_ratio.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        self.txt_ratio.insert(0, "1.0")

        # --- 3. BẢNG SO SÁNH GỘP ---
        comp_frame = ttk.LabelFrame(sidebar, text="Bảng So sánh Thông số", padding=5)
        comp_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(comp_frame, text="Thông số", font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=tk.W, padx=2)
        ttk.Label(comp_frame, text="Ảnh Gốc", font=('Arial', 9, 'bold')).grid(row=0, column=1, padx=2)
        ttk.Label(comp_frame, text="Tiền Xử Lý", font=('Arial', 9, 'bold')).grid(row=0, column=2, padx=2)
        
        ttk.Label(comp_frame, text="Tổng số Box:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_box_orig = ttk.Label(comp_frame, text="0", anchor=tk.CENTER)
        self.lbl_box_orig.grid(row=1, column=1, sticky=tk.EW)
        self.lbl_box_proc = ttk.Label(comp_frame, text="0", anchor=tk.CENTER)
        self.lbl_box_proc.grid(row=1, column=2, sticky=tk.EW)
        
        ttk.Label(comp_frame, text="Avg CD (um):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.lbl_cd_orig = ttk.Label(comp_frame, text="0.0", anchor=tk.CENTER)
        self.lbl_cd_orig.grid(row=2, column=1, sticky=tk.EW)
        self.lbl_cd_proc = ttk.Label(comp_frame, text="0.0", anchor=tk.CENTER)
        self.lbl_cd_proc.grid(row=2, column=2, sticky=tk.EW)
        
        ttk.Label(comp_frame, text="Tổng Diện tích:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.lbl_area_orig = ttk.Label(comp_frame, text="0", anchor=tk.CENTER)
        self.lbl_area_orig.grid(row=3, column=1, sticky=tk.EW)
        self.lbl_area_proc = ttk.Label(comp_frame, text="0", anchor=tk.CENTER)
        self.lbl_area_proc.grid(row=3, column=2, sticky=tk.EW)

        # --- 4. DANH SÁCH MẪU ĐÃ ĐO ---
        list_frame = ttk.LabelFrame(sidebar, text="Danh sách mẫu đã xử lý", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.listbox_history = tk.Listbox(list_frame, height=5)
        self.listbox_history.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox_history.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox_history.config(yscrollcommand=scrollbar.set)
        self.listbox_history.bind('<<ListboxSelect>>', self.on_history_select)

        # --- 5. NÚT ĐIỀU KHIỂN CHUNG ---
        btn_row = ttk.Frame(sidebar)
        btn_row.pack(fill=tk.X, pady=(5, 0))
        self.btn_clear = ttk.Button(btn_row, text="Clear Data", command=self.clear_all_data)
        self.btn_clear.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.btn_show_all = ttk.Button(btn_row, text="Hiện Box", command=self.toggle_show_all)
        self.btn_show_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # ==================== 2. CENTER PANEL (CANVAS) ====================
        display_frame = ttk.Frame(self.root, padding="10")
        display_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Cửa sổ Trái: LIVE CAMERA
        frame_live = ttk.LabelFrame(display_frame, text="Camera Live View")
        frame_live.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.BOTH)
        self.canvas_live = tk.Canvas(frame_live, bg="#1e1e1e")
        self.canvas_live.pack(expand=True, fill=tk.BOTH)

        # Cửa sổ Phải: KẾT QUẢ ĐO / CHỤP
        frame_result = ttk.LabelFrame(display_frame, text="Màn hình Kết quả (Ảnh chụp)")
        frame_result.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.BOTH)
        self.canvas_result = tk.Canvas(frame_result, cursor="crosshair", bg="#2b2b2b")
        self.canvas_result.pack(expand=True, fill=tk.BOTH)
        

        # ==================== 3. BOTTOM PANEL ====================
        bottom_frame = ttk.LabelFrame(self.root, text="Bảng dữ liệu chi tiết", padding=5)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.notebook = ttk.Notebook(bottom_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        cols_orig = ("id", "cd_px", "cd_um", "status")
        cols_error = ("id", "Nằm trong ID Box")
        
        tab_orig = ttk.Frame(self.notebook)
        self.notebook.add(tab_orig, text="Sheet: Ảnh Gốc")
        self.tree_orig = ttk.Treeview(tab_orig, columns=cols_orig, show='headings', height=6)
        self.setup_treeview(self.tree_orig, cols_orig)
        self.tree_orig.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        tab_proc = ttk.Frame(self.notebook)
        self.notebook.add(tab_proc, text="Sheet: Tiền Xử Lý")
        self.tree_proc = ttk.Treeview(tab_proc, columns=cols_orig, show='headings', height=6)
        self.setup_treeview(self.tree_proc, cols_orig)
        self.tree_proc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tab_error = ttk.Frame(self.notebook)
        self.notebook.add(tab_error, text="Lỗi Phát hiện")
        self.tree_error_view = ttk.Treeview(tab_error, columns=cols_error, show='headings', height=6)
        self.setup_treeview(self.tree_error_view, cols_error)
        self.tree_error_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        
        self.tree_proc.bind("<<TreeviewSelect>>", self.on_tree_select_proc)
        self.tree_orig.bind("<<TreeviewSelect>>", self.on_tree_select_orig)
        self.tree_error_view.bind("<<TreeviewSelect>>", self.on_tree_select_error)

        self.on_mode_change()

    def setup_treeview(self, tree, columns):
        """
        Định dạng các cột hiển thị trong TreeView dựa trên danh sách columns truyền vào
        """
        for col in columns:
            # Tự động đặt tiêu đề dựa trên tên cột
            header_text = col.replace("_", " ").upper()
            if col == "id": header_text = "ID"
            elif col == "cd_px": header_text = "CD (pixel)"
            elif col == "cd_um": header_text = "CD (um)"
            elif col == "status": header_text = "Trạng thái"
            
            tree.heading(col, text=header_text)
            tree.column(col, width=120, anchor=tk.CENTER)
            
        tree.tag_configure('ok', foreground='green')
        tree.tag_configure('fail', foreground='red')
        
        sb = ttk.Scrollbar(tree.master, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
    def on_closing(self):
        """Xử lý dọn dẹp bộ nhớ trước khi tắt phần mềm"""
        self.is_live_running = False
        self.root.destroy()

    # ==============================================================================
    # XỬ LÝ SỰ KIỆN TABS & MODE
    # ==============================================================================
    def on_mode_change(self):
        """Kích hoạt/vô hiệu hoá các phím chức năng dựa trên mode lựa chọn"""
        mode = self.var_op_mode.get()
        if mode == "Manual":
            for btn in [self.btn_load, self.btn_capture, self.btn_live, self.btn_detect, self.btn_measure]:
                btn.config(state=tk.NORMAL)
        else:
            for btn in [self.btn_load, self.btn_capture, self.btn_live, self.btn_detect, self.btn_measure]:
                btn.config(state=tk.DISABLED)

    def on_tab_changed(self, event):
        """Sự kiện chuyển qua lại giữa các sheet dữ liệu để render lại Canvas"""
        selected_tab = self.notebook.index(self.notebook.select())
        self.current_view_tab = selected_tab # 0: Ảnh gốc, 1: Tiền xử lý
        self.draw_boxes()

    # ==========================================
    # LOGIC CAMERA MVS HIKVISION (STREAM THREAD & CAPTURE)
    # ==========================================
    def toggle_live_camera(self):
        if self.is_live_running:
            self.is_live_running = False
            self.btn_live.config(text="🔴 Bật Live Camera")
        else:
            self.is_live_running = True
            self.btn_live.config(text="⏹ Tắt Live Camera")
            
            # Khởi chạy luồng lấy hình
            threading.Thread(target=self.live_camera_loop, daemon=True).start()
            # Bật luồng cập nhật UI
            self.update_live_ui()

    def update_live_ui(self):
        if self.is_live_running:
            if getattr(self, 'latest_frame', None) is not None:
                try:
                    display_frame = self.latest_frame.copy()
                    display_frame = cv2.resize(display_frame, (640, 480))
                    self.show_image(display_frame, self.canvas_live)
                except Exception as e:
                    print("Lỗi Render Live UI:", e)
            self.root.after(33, self.update_live_ui) # ~30 FPS
        else:
            self.canvas_live.delete("all")

    def live_camera_loop(self):
        try:
            from MvImport.MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, MV_USB_DEVICE, MV_GIGE_DEVICE, MV_CC_DEVICE_INFO, MV_ACCESS_Exclusive, MV_FRAME_OUT
        except ImportError:
            self.is_live_running = False
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi Thư viện", "Không tìm thấy thư viện SDK Hikvision (MvImport)."))
            return

        deviceList = MV_CC_DEVICE_INFO_LIST()
        # Áp dụng logic từ test.py: Tìm cả USB lẫn GIGE
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        
        if deviceList.nDeviceNum == 0:
            self.is_live_running = False
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi", "Không tìm thấy hoặc chưa kết nối Camera Hikvision!"))
            return

        # Áp dụng logic từ test.py: Lấy device đầu tiên
        stDeviceList = ctypes.cast(deviceList.pDeviceInfo[0], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        self.cam = MvCamera()
        
        if self.cam.MV_CC_CreateHandle(stDeviceList) != 0 or self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) != 0:
            self.is_live_running = False
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi", "Không thể mở Handle Camera!"))
            return

        if self.cam.MV_CC_StartGrabbing() != 0:
            self.is_live_running = False
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi", "Lỗi StartGrabbing!"))
            return

        stOutFrame = MV_FRAME_OUT()
        
        while self.is_live_running:
            ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
            ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
            
            if ret == 0:
                # Áp dụng giải pháp Ctypes Buffer từ test.py để không crash
                pData = (ctypes.c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                ctypes.memmove(pData, stOutFrame.pBufAddr, stOutFrame.stFrameInfo.nFrameLen)
                data = np.frombuffer(pData, dtype=np.uint8)
                
                w, h = stOutFrame.stFrameInfo.nWidth, stOutFrame.stFrameInfo.nHeight
                frame = None
                try:
                    if data.size == w * h:
                        frame = data.reshape((h, w))
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    elif data.size == w * h * 3:
                        frame = data.reshape((h, w, 3))
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    print("Lỗi parse frame Numpy:", e)
                    
                if frame is not None:
                    self.latest_frame = frame.copy()
                        
                self.cam.MV_CC_FreeImageBuffer(stOutFrame)

        self.cam.MV_CC_StopGrabbing()
        self.cam.MV_CC_CloseDevice()
        self.cam.MV_CC_DestroyHandle()
        self.cam = None

    def capture_image(self):
        # NẾU ĐANG LIVE: Lấy frame mới nhất đẩy sang kết quả
        if self.is_live_running:
            if getattr(self, 'latest_frame', None) is not None:
                self.clear_all_data(clear_history=False)
                self.current_img_orig = self.latest_frame.copy()
                self.current_img_gray = cv2.cvtColor(self.current_img_orig, cv2.COLOR_BGR2GRAY)
                self.notebook.select(0)
                self.draw_boxes()
            else:
                messagebox.showerror("Lỗi", "Camera chưa lấy được hình ảnh nào, vui lòng đợi!")
            return
            
        # NẾU KHÔNG LIVE: Mở camera lấy 1 ảnh
        try:
            from MvImport.MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, MV_USB_DEVICE, MV_GIGE_DEVICE, MV_CC_DEVICE_INFO, MV_ACCESS_Exclusive, MV_FRAME_OUT
        except ImportError:
            messagebox.showerror("Lỗi Thư viện", "Không tìm thấy thư viện SDK Hikvision (MvImport).")
            return

        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        
        if deviceList.nDeviceNum == 0:
            messagebox.showerror("Lỗi", "Không tìm thấy Camera Hikvision!")
            return

        stDeviceList = ctypes.cast(deviceList.pDeviceInfo[0], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        cam = MvCamera()
        if cam.MV_CC_CreateHandle(stDeviceList) != 0 or cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) != 0: 
            messagebox.showerror("Lỗi", "Không thể mở Handle Camera!")
            return

        if cam.MV_CC_StartGrabbing() != 0:
            cam.MV_CC_CloseDevice()
            cam.MV_CC_DestroyHandle()
            messagebox.showerror("Lỗi", "Không thể StartGrabbing!")
            return

        stOutFrame = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
        ret = cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
        
        if ret == 0:
            # Dùng memmove như test.py
            pData = (ctypes.c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
            ctypes.memmove(pData, stOutFrame.pBufAddr, stOutFrame.stFrameInfo.nFrameLen)
            data = np.frombuffer(pData, dtype=np.uint8)
            
            w, h = stOutFrame.stFrameInfo.nWidth, stOutFrame.stFrameInfo.nHeight
            frame = None
            try:
                if data.size == w * h:
                    frame = data.reshape((h, w))
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                elif data.size == w * h * 3:
                    frame = data.reshape((h, w, 3))
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR) 
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể giải mã Numpy:\n{e}")
                
            if frame is not None:
                self.clear_all_data(clear_history=False)
                self.current_img_orig = frame
                self.current_img_gray = cv2.cvtColor(self.current_img_orig, cv2.COLOR_BGR2GRAY)
                self.notebook.select(0)
                self.draw_boxes()
                
            cam.MV_CC_FreeImageBuffer(stOutFrame)
        else:
            messagebox.showerror("Lỗi Timeout", "Không lấy được hình từ Camera!")

        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()


    def load_image(self):
        """Tải ảnh từ máy tính để phân tích"""
        path = filedialog.askopenfilename()
        if not path: return
        self.current_file_path = path
        self.clear_all_data(clear_history=False)
        self.current_img_orig = cv2.imread(path)
        self.current_img_gray = cv2.cvtColor(self.current_img_orig, cv2.COLOR_BGR2GRAY)
        self.notebook.select(0)
        self.draw_boxes()

    # ==============================================================================
    # QUẢN LÝ DỮ LIỆU & LỊCH SỬ (HISTORY)
    # ==============================================================================
    def save_to_history(self):
        """Lưu lại trạng thái xử lý hiện tại vào danh sách lịch sử bên cột trái"""
        sample_name = f"Mẫu {len(self.sample_history) + 1} - {datetime.datetime.now().strftime('%H:%M:%S')}"
        snapshot = {
            'img_orig': self.current_img_orig.copy() if self.current_img_orig is not None else None,
            'img_gray': self.current_img_gray.copy() if self.current_img_gray is not None else None,
            'img_balanced': self.img_balanced.copy() if self.img_balanced is not None else None,
            'raw_mask': self.raw_mask.copy() if self.raw_mask is not None else None,
            'processed_mask': self.processed_mask.copy() if self.processed_mask is not None else None,
            'boxes_orig': [b.copy() for b in self.boxes_orig],
            'boxes_proc': [b.copy() for b in self.boxes_proc],
        }
        self.sample_history.append(snapshot)
        self.listbox_history.insert(tk.END, sample_name)
        self.current_sample_idx = len(self.sample_history) - 1
        self.listbox_history.selection_clear(0, tk.END)
        self.listbox_history.selection_set(tk.END)
        self.listbox_history.see(tk.END)

    def on_history_select(self, event):
        """Phục hồi lại toàn bộ trạng thái (hình ảnh, bảng biểu) của mẫu ảnh đã chọn"""
        selection = self.listbox_history.curselection()
        if not selection: return
        
        idx = selection[0]
        self.current_sample_idx = idx
        snapshot = self.sample_history[idx]
        
        self.current_img_orig = snapshot['img_orig']
        self.current_img_gray = snapshot['img_gray']
        self.img_balanced = snapshot['img_balanced']
        self.raw_mask = snapshot['raw_mask']
        self.processed_mask = snapshot['processed_mask']
        self.boxes_orig = snapshot['boxes_orig']
        self.boxes_proc = snapshot['boxes_proc']
        self.boxes_error = snapshot['boxes_error']
        self.populate_tree(self.tree_orig, self.boxes_orig, False)
        self.populate_tree(self.tree_proc, self.boxes_proc, True)
        self.update_comparison_table()
        
        self.draw_boxes()

    def clear_tree(self, tree):
        for item in tree.get_children(): tree.delete(item)

    def clear_all_data(self, clear_history=True):
        """Reset giao diện về lại như mới"""
        if clear_history and messagebox.askyesno("Xác nhận", "Bạn có muốn xóa tất cả dữ liệu đã xử lý?"):
            self.sample_history.clear()
            self.listbox_history.delete(0, tk.END)
            self.current_img_orig = None
            self.img_balanced = None
            
        self.boxes_orig.clear()
        self.boxes_proc.clear()
        
        self.clear_tree(self.tree_orig)
        self.clear_tree(self.tree_proc)
        self.clear_tree(self.tree_error_view)
        
        self.lbl_box_orig.config(text="0")
        self.lbl_box_proc.config(text="0")
        self.lbl_cd_orig.config(text="0.0")
        self.lbl_cd_proc.config(text="0.0")
        self.lbl_area_orig.config(text="0")
        self.lbl_area_proc.config(text="0")
            
        self.is_showing_all = False
        self.btn_show_all.config(text="Hiện Box")
        
        self.draw_boxes()

    # ==============================================================================
    # XỬ LÝ LÕI: TÌM BOX & ĐO KÍCH THƯỚC (LITHO)
    # ==============================================================================
    def run_preprocess(self):
        """Hàm phụ trách chạy ảnh qua các màng lọc (threshold, edge, blur...)"""
        if self.current_img_gray is None: return False
        _, self.raw_mask = cv2.threshold(self.current_img_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        self.img_balanced, self.processed_mask = litho.preprocess_image(self.current_img_gray)
        return True

    def run_detection(self):
        """Tìm các vị trí (Bounding Box) khả thi trên hình ảnh"""
        if self.current_img_gray is None:
            messagebox.showwarning("Cảnh báo", "Vui lòng chụp ảnh hoặc tải ảnh trước!")
            return
            
        self.run_preprocess()
        
        def task():
            raw_boxes_o = litho.find_valid_bounding_boxes(self.raw_mask, self.current_img_gray, self.current_img_gray.shape[:2])
            raw_boxes_p = litho.find_valid_bounding_boxes(self.processed_mask, self.current_img_gray, self.current_img_gray.shape[:2])

            self.boxes_orig = self.format_box_data(raw_boxes_o, "O_")
            self.boxes_proc = self.format_box_data(raw_boxes_p, "P_")
            
            self.populate_tree(self.tree_orig, self.boxes_orig, False)
            self.populate_tree(self.tree_proc, self.boxes_proc, True)
            
            self.update_comparison_table()
            self.is_showing_all = True
            self.btn_show_all.config(text="Ẩn Box")
            self.draw_boxes()

        threading.Thread(target=task).start()

    def format_box_data(self, raw_boxes, prefix):
        """Chuẩn hóa dữ liệu box trước khi lưu vào RAM để đẩy xuống bảng"""
        formatted = []
        for i, rb in enumerate(raw_boxes, 1):
            x, y, w, h = rb['bbox']
            formatted.append({
                "id": f"{prefix}{i}", "x": x, "y": y, "w": w, "h": h, 
                "bbox": rb['bbox'],
                "area": rb['area'], "raw_data": rb, "measured": False, "user_accepted": True
            })
        return sorted(formatted, key=lambda b: b['area'], reverse=True)

    # ==============================================================================
    # XỬ LÝ GIAO DIỆN BẢNG DỮ LIỆU (TREEVIEW)
    # ==============================================================================
    def populate_tree(self, tree, box_list, is_proc):
        """Hiển thị các box đã nhận diện và đo lường xuống Treeview phía dưới"""
        self.clear_tree(tree)
        
        # Nếu là sheet Ảnh Gốc (Chỉ xem)
        if not is_proc:
            for b in box_list:
                if b.get('is_valid') and b.get('measured'):
                    tree.insert("", tk.END, values=(b['id'], round(b['subpixel_cd'], 2), round(b['cd_um'], 3), b['status']), tags=('ok',))
                else:
                    tree.insert("", tk.END, values=(b['id'], "N/A", "N/A", b.get('status', 'FAIL')), tags=('error',))
            return
            
        # --- DÀNH CHO SHEET TIỀN XỬ LÝ (is_proc = True) ---
        if box_list:
            for b in box_list:
                # Đã loại bỏ chuỗi "✅ Giữ (+)" vì tính năng Double Click đã được xóa
                if b.get('is_valid') and b.get('measured'):
                    tree.insert("", tk.END, values=(b['id'], round(b['subpixel_cd'], 2), round(b['cd_um'], 3), b['status']), tags=('ok',))
                else:
                    tree.insert("", tk.END, values=(b['id'], "N/A", "N/A", b.get('status', 'FAIL')), tags=('error',))

    # ==============================================================================
    # XỬ LÝ ĐO LƯỜNG (MEASUREMENT)
    # ==============================================================================
    def run_measurement(self):
        """
        Tiến hành tính toán CD Line Width tại các Box đã xác định.
        Sử dụng hàm measure_cd_line_width từ file litho.py.
        """
        # Kiểm tra xem có dữ liệu box để đo hay không
        if not getattr(self, 'boxes_proc', []) and not getattr(self, 'boxes_orig', []):
            messagebox.showwarning("Trống", "Không có đối tượng nào để đo!")
            return
            
        # Lấy tỉ lệ scale từ giao diện người dùng nhập
        try:
            self.pixel_to_um = float(self.txt_ratio.get())
        except ValueError:
            self.pixel_to_um = 1.0
            
        # Hàm nội bộ xử lý danh sách box
        def process_list(box_list, mask, gray, is_proc):
            img_h, img_w = gray.shape[:2]
            
            for b in box_list:
                if is_proc and not b.get('user_accepted', True):
                    continue

                raw_b = b.get('raw_data')
                if raw_b is None: continue 
                
                x, y, w, h = b['bbox']
                
                # Tạo mask và cắt ảnh ROI cục bộ
                local_mask = np.zeros_like(mask)
                cv2.drawContours(local_mask, [raw_b['contour']], -1, 255, -1)
                roi_mask = local_mask[y:y+h, x:x+w]
                roi_gray = gray[y:y+h, x:x+w]
                
                # Đảm bảo có định hướng ngang/dọc
                if 'is_vertical' not in raw_b or 'is_horizontal' not in raw_b:
                    raw_b['is_vertical'] = (h >= w)
                    raw_b['is_horizontal'] = (w > h)

                if not raw_b.get('is_vertical') and not raw_b.get('is_horizontal'):
                    b.update({'status': 'Lệch Trục', 'is_valid': False})
                else:
                    # GỌI HÀM ĐO LƯỜNG TỪ LITHO.PY
                    res = litho.measure_cd_line_width(roi_mask, roi_gray, raw_b)
                    b.update(res) # Cập nhật kết quả vào box
                    
                    if not b.get('is_valid'):
                        b['status'] = "FAIL (Đo)"
                    else:
                        pt1, pt2 = b.get('pt1'), b.get('pt2')
                        if not pt1 or not pt2:
                            b['status'] = "FAIL (Đo)"
                            b['is_valid'] = False
                        else:
                            # =========================================================
                            # RÀNG BUỘC 1: CHẠM VIỀN ẢNH (ĐÃ SỬA LỖI TỌA ĐỘ)
                            # =========================================================
                            # pt1, pt2 đã là tọa độ toàn cục (global) -> KHÔNG CỘNG x, y nữa
                            gx1, gy1 = pt1[0], pt1[1]
                            gx2, gy2 = pt2[0], pt2[1]
                            
                            margin = 1 # Dùng 1 để an toàn hơn với nhiễu viền
                            if (gx1 <= margin or gy1 <= margin or gx1 >= img_w - margin or gy1 >= img_h - margin or
                                gx2 <= margin or gy2 <= margin or gx2 >= img_w - margin or gy2 >= img_h - margin):
                                
                                b['status'] = "FAIL (Viền)"
                                b['is_valid'] = False
                            else:
                                # =========================================================
                                # RÀNG BUỘC 2: OVERLAP ERROR BOX -> FAIL (Logic AABB Collision)
                                # =========================================================
                                overlap = False
                                bx, by, bw, bh = b['bbox']
                                
                                if hasattr(self, 'error_boxes'):
                                    for err in self.error_boxes:
                                        ex, ey, ew, eh = err['bbox']
                                        # Kỹ thuật kiểm tra chồng lấn 2 hình chữ nhật
                                        if not (bx + bw < ex or ex + ew < bx or by + bh < ey or ey + eh < by):
                                            overlap = True
                                            break
                                
                                if overlap:
                                    b['status'] = "FAIL (Lỗi AI)"
                                    b['is_valid'] = False
                                else:
                                    b['status'] = "OK"

                b['measured'] = True
                if b.get('is_valid'):
                    b['cd_um'] = b.get('subpixel_cd', 0) * self.pixel_to_um
                else:
                    b['cd_um'] = 0.0

        # Khởi tạo mask dự phòng nếu người dùng chưa bấm 'Xác định vùng' mà bấm 'Đo' luôn
        if self.raw_mask is None: self.raw_mask = np.zeros_like(self.current_img_gray)
        if self.processed_mask is None: self.processed_mask = np.zeros_like(self.current_img_gray)
        
        img_for_proc = self.img_balanced if self.img_balanced is not None else self.current_img_gray
        
        # 1. Tiến hành đo lường chạy ngầm trên danh sách Box
        process_list(self.boxes_orig, self.raw_mask, self.current_img_gray, False)
        process_list(self.boxes_proc, self.processed_mask, img_for_proc, True)
        
        # 2. Cập nhật lại UI thông qua hàm tập trung
        self.populate_tree(self.tree_orig, self.boxes_orig, False)
        self.populate_tree(self.tree_proc, self.boxes_proc, True)
        
        self.update_comparison_table()
        self.draw_boxes()
        self.save_to_history()

    # ==============================================================================
    # XỬ LÝ PHÁT HIỆN LỖI (ERROR DETECTION)
    # ==============================================================================
    def run_error_detection(self):
        if self.current_img_orig is None:
            messagebox.showwarning("Cảnh báo", "Vui lòng mở ảnh trước khi detect lỗi.")
            return

        # 1. Chạy Model YOLO
        results = self.error_model(self.current_img_orig)
        new_errors = []
        err_id_start = 1 
        
        # Lấy danh sách kết quả từ YOLO
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                w, h = x2 - x1, y2 - y1
                new_errors.append({
                    'id': f"ERR_{err_id_start}", # SỬA LỖI: Thêm key 'id'
                    'bbox': (int(x1), int(y1), int(w), int(h)),
                    'class': self.error_model.names[int(box.cls[0])],
                    'parent_id': "None" 
                })
                err_id_start += 1

        # 2. Xử lý Logic so sánh với Box Litho (self.boxes_proc)
        litho_indices_to_remove = []
        
        for err in new_errors:
            ex, ey, ew, eh = err['bbox']
            err_area = ew * eh
            
            for i, lb in enumerate(self.boxes_proc):
                lx, ly, lw, lh = lb['bbox']
                lb_area = lw * lh
                
                # Tính độ giao nhau (Sử dụng hàm get_iou có sẵn trong file của bạn)
                iou = get_iou(err['bbox'], lb['bbox'])
                
                if iou > 0.02: # Nếu có chạm nhau
                    # ĐIỀU KIỆN: Nếu box lỗi lớn hơn box litho -> Xóa box litho
                    if err_area > lb_area:
                        litho_indices_to_remove.append(i)
                        err['parent_id'] = "None (Đã xóa Litho)"
                    else:
                        # Nếu nhỏ hơn thì ghi nhận là nằm trong khối litho đó
                        err['parent_id'] = lb.get('id', 'N/A')

        # Thực hiện xóa các box Litho bị đè (xóa từ dưới lên để tránh sai index)
        for index in sorted(set(litho_indices_to_remove), reverse=True):
            if index < len(self.boxes_proc):
                self.boxes_proc.pop(index)

        # Cập nhật danh sách lỗi và vẽ lại UI
        self.error_boxes = new_errors
        self.update_error_table()
        
        self.notebook.select(2) # Tự động chuyển qua Tab Lỗi (Tab số 3)
        self.draw_boxes() # Dùng hàm vẽ có sẵn của bạn để render Box lỗi
        
        messagebox.showinfo("Xong", f"Đã phát hiện {len(new_errors)} lỗi.")

    def update_error_table(self):
        """Cập nhật dữ liệu vào bảng Detected Error"""
        # Xóa dữ liệu cũ trong bảng
        for item in self.tree_error_view.get_children():
            self.tree_error_view.delete(item)
            
        # Thêm dữ liệu mới từ danh sách self.error_boxes
        if hasattr(self, 'error_boxes'):
            for i, err in enumerate(self.error_boxes):
                err_id = f"ERR_{i+1}"
                parent = err.get('parent_id', 'N/A')
                self.tree_error_view.insert('', tk.END, values=(err_id, parent))

    # ==============================================================================
    # CẬP NHẬT BẢNG SO SÁNH THÔNG SỐ (GÓC TRÁI)
    # ==============================================================================
    def update_comparison_table(self):
        """Tính toán tổng hợp Diện tích, Số Box, Trung bình CD và Cập nhật lên Cột trái"""
        def calc_stats(box_list):
            valid_cds = []
            accepted_boxes = []
            
            # Lọc các box hợp lệ
            for b in box_list:
                if not b.get('user_accepted', True): continue
                accepted_boxes.append(b)
                if b.get('is_valid') and b.get('measured'):
                    valid_cds.append(b['cd_um'])
                    
            avg_cd = np.mean(valid_cds) if valid_cds else 0.0
            
            # Tính tổng diện tích của vùng contour
            total_area_px = 0
            if self.current_img_gray is not None and accepted_boxes:
                img_h, img_w = self.current_img_gray.shape
                master_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                for b in accepted_boxes:
                    if b.get('raw_data'):
                        cv2.drawContours(master_mask, [b['raw_data']['contour']], -1, 255, -1)
                    else: 
                        bx, by, bw, bh = b['bbox']
                        cv2.rectangle(master_mask, (bx, by), (bx+bw, by+bh), 255, -1)
                total_area_px = cv2.countNonZero(master_mask)
                
            return len(accepted_boxes), avg_cd, total_area_px

        # Đẩy dữ liệu tính toán lên giao diện
        b_orig, cd_orig, area_orig = calc_stats(self.boxes_orig)
        self.lbl_box_orig.config(text=str(b_orig))
        self.lbl_cd_orig.config(text=f"{cd_orig:.3f}")
        self.lbl_area_orig.config(text=f"{area_orig:,} px²")
        
        b_proc, cd_proc, area_proc = calc_stats(self.boxes_proc)
        self.lbl_box_proc.config(text=str(b_proc))
        self.lbl_cd_proc.config(text=f"{cd_proc:.3f}")
        self.lbl_area_proc.config(text=f"{area_proc:,} px²")

    # ==============================================================================
    # TƯƠNG TÁC NGƯỜI DÙNG (CLICK, DOUBLE CLICK)
    # ==============================================================================
            
    def on_tree_select_proc(self, event):
        """Focus làm sáng Box trên Canvas nếu click vào ID tại bảng Tiền Xử Lý"""
        sel = self.tree_proc.selection()
        if sel: 
            box_id_display = str(self.tree_proc.item(sel[0], 'values')[0])
            if box_id_display.startswith("---"): 
                return
                
            real_id = box_id_display
            self.notebook.select(1)
            self.draw_boxes(real_id)

    def on_tree_select_orig(self, event):
        """Focus làm sáng Box trên Canvas nếu click vào ID tại bảng Ảnh Gốc"""
        sel = self.tree_orig.selection()
        if sel: 
            self.notebook.select(0)
            self.draw_boxes(self.tree_orig.item(sel[0], 'values')[0])

    def on_tree_select_error(self, event):
        """Focus làm sáng Box lỗi trên Canvas nếu click vào ID tại bảng Lỗi"""
        sel = self.tree_error_view.selection()
        if sel:
            error_id = str(self.tree_error_view.item(sel[0], 'values')[0])
            self.notebook.select(2)
            self.draw_boxes(error_id)

    def toggle_show_all(self):
        """Toggled trạng thái Ẩn/Hiện toàn bộ box trên màn hình Canvas"""
        self.is_showing_all = not getattr(self, 'is_showing_all', False)
        if self.is_showing_all:
            self.btn_show_all.config(text="Ẩn Box")
        else:
            self.btn_show_all.config(text="Hiện Box")
        
        self.draw_boxes()

    # ==============================================================================
    # KẾT XUẤT ĐỒ HỌA (RENDER CANVAS)
    # ==============================================================================
    def draw_boxes(self, selected_id=None):
        """Vẽ các hình chữ nhật nhận diện và Line Measurement lên ảnh (theo Layer)"""
        if self.current_img_orig is None: 
            self.canvas_result.delete("all")
            return
        
        # Xác định nguồn ảnh dựa trên Tab đang mở (0: Ảnh gốc, 1: Tiền xử lý)
        if self.current_view_tab == 0:
            canvas_img = self.current_img_orig.copy()
            box_list = self.boxes_orig
            show_measurement = any(b.get('measured') for b in self.boxes_orig)
        else:
            if self.img_balanced is not None:
                canvas_img = cv2.cvtColor(self.img_balanced, cv2.COLOR_GRAY2RGB)
            else:
                canvas_img = self.current_img_orig.copy()
            box_list = self.boxes_proc
            show_measurement = any(b.get('measured') for b in self.boxes_proc)

        if selected_id is None:
            selected_id = "ALL" if getattr(self, 'is_showing_all', False) else "NONE"
            
        if selected_id == "NONE":
            self.show_image(canvas_img, self.canvas_result)
            return
            
        # Duyệt qua từng box để vẽ
        for box in box_list:
            if not box.get('user_accepted', True): continue 
            
            is_all = (selected_id == "ALL")
            is_this_box_selected = (selected_id == box['id'])
            
            if not is_all and not is_this_box_selected:
                continue
                
            bx, by, bw, bh = box['bbox']
            
            # --- XỬ LÝ MÀU SẮC & TEXT ---
            status = box.get('status', 'N/A')
            if status == 'FAIL' or box.get('is_valid') is False:
                color = (0, 0, 255)   # Đỏ cho khối Đo thất bại (Hoặc hình dạng phức tạp)
                status = 'FAIL'
            else:
                color = (0, 255, 0)   # Xanh lá cho khối OK
            
            thickness = 2 if is_all else 3
            cv2.rectangle(canvas_img, (bx, by), (bx+bw, by+bh), color, thickness)
            
            # Ghi ID và Trạng thái bên cạnh Box
            label_text = f"{box['id']}" if show_measurement else f"{box['id']}"
            cv2.putText(canvas_img, label_text, (bx, by-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # Chỉ vẽ vạch đo CD (đỏ) nếu box này hợp lệ
            if show_measurement and box.get('is_valid'):
                pt1, pt2 = box.get('pt1'), box.get('pt2')
                if pt1 and pt2:
                    cv2.line(canvas_img, pt1, pt2, (0, 0, 255), thickness)
                    cv2.putText(canvas_img, f"{box['subpixel_cd']:.1f}", (bx, by+bh+15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
        # =======================================================
        # VẼ CÁC BOX LỖI TỪ AI (NẾU CÓ)
        # =======================================================
        if hasattr(self, 'error_boxes'):
            for err in self.error_boxes:
                e_id = err.get('id', 'ERR')
                
                # 1. Xác định trạng thái chọn (Giống Box Litho)
                is_all = (selected_id == "ALL")
                is_this_box_selected = (selected_id == e_id)
                
                # Nếu không bấm "Hiện Box" và cũng không click đúng ID này -> Ẩn nó đi
                if not is_all and not is_this_box_selected:
                    continue
                
                # 2. Thay đổi độ dày viền nếu được click (Dày hơn để nổi bật)
                thickness = 2 
                
                x, y, w, h = err['bbox']
                
                # 3. Vẽ khung hình chữ nhật màu Đỏ
                cv2.rectangle(canvas_img, (x, y), (x + w, y + h), (0, 0, 255), thickness)
                
                # 4. Vẽ ID Lỗi lên trên box
                label = f"ID: {e_id}"
                
                # Tùy chỉnh nét chữ ăn theo viền box
                text_thickness = max(1, thickness - 1)
                
                # max(0, y - 10) giúp chữ không bị văng ra ngoài mép trên của ảnh
                cv2.putText(canvas_img, label, (x, max(0, y - 10)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), text_thickness)

        self.show_image(canvas_img, self.canvas_result)


    def show_image(self, cv_img, canvas_widget):
        """Thay đổi kích cỡ (Resize) ảnh gốc để fit vừa vặn với kích thước UI và Render lên Tkinter Canvas"""
        canvas_widget.update_idletasks()
        c_w = canvas_widget.winfo_width()
        c_h = canvas_widget.winfo_height()
        if c_w < 10: c_w, c_h = 600, 500 
        
        h, w = cv_img.shape[:2]
        scale = min(c_w / w, c_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        
        self.ui_scale_factors[canvas_widget] = 1 / scale 
        
        img_resized = cv2.resize(cv_img, (new_w, new_h))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_GRAY2RGB) if len(img_resized.shape) == 2 else cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
            
        img_tk = ImageTk.PhotoImage(Image.fromarray(img_rgb))
        
        offset_x = (c_w - new_w) // 2
        offset_y = (c_h - new_h) // 2
        self.canvas_offsets[canvas_widget] = (offset_x, offset_y)
        
        canvas_widget.delete("all")
        canvas_widget.create_image(offset_x, offset_y, anchor=tk.NW, image=img_tk)
        canvas_widget.image = img_tk 

if __name__ == "__main__":
    root = tk.Tk()
    app = IndustrialInspectionUI(root)
    root.mainloop()