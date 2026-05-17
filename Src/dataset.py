import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from PIL import Image, ImageTk
import cv2
import numpy as np
import os
import threading
import datetime
import ctypes

class YoloLabelingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Công cụ Chụp & Gán nhãn YOLO v3 (Tích hợp Camera MVS)")
        self.root.geometry("1200x700")

        # --- QUẢN LÝ THƯ MỤC ---
        self.dataset_dir = os.path.abspath("yolo_dataset")
        self.capture_dir = os.path.abspath("raw_captures")
        
        if not os.path.exists(self.dataset_dir): os.makedirs(self.dataset_dir)
        if not os.path.exists(self.capture_dir): os.makedirs(self.capture_dir)

        # --- QUẢN LÝ CAMERA ---
        self.cam = None
        self.is_live_running = False
        self.latest_frame = None

        self.setup_ui()
        
        # Đảm bảo tắt camera khi đóng app
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        # ==================== 1. SIDEBAR LEFT (ĐIỀU KHIỂN) ====================
        sidebar = ttk.Frame(self.root, padding="10", relief="flat", width=350)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False) 

        ttk.Label(sidebar, text="CẤU HÌNH THƯ MỤC LƯU", font=("Arial", 11, "bold")).pack(pady=(10, 5))
        
        # Thư mục lưu ảnh Raw
        f_cap = ttk.LabelFrame(sidebar, text="Thư mục Ảnh Chụp (Raw)", padding=5)
        f_cap.pack(fill=tk.X, pady=5)
        self.lbl_cap_dir = tk.Label(f_cap, text=self.capture_dir, fg="blue", wraplength=300, justify="left")
        self.lbl_cap_dir.pack(pady=2)
        ttk.Button(f_cap, text="Đổi thư mục Ảnh chụp", command=self.set_capture_dir).pack(pady=2)

        # Thư mục lưu Dataset
        f_data = ttk.LabelFrame(sidebar, text="Thư mục Dataset (YOLO txt)", padding=5)
        f_data.pack(fill=tk.X, pady=5)
        self.lbl_data_dir = tk.Label(f_data, text=self.dataset_dir, fg="green", wraplength=300, justify="left")
        self.lbl_data_dir.pack(pady=2)
        ttk.Button(f_data, text="Đổi thư mục Dataset", command=self.set_dataset_dir).pack(pady=2)

        # --- ĐIỀU KHIỂN CAMERA & GÁN NHÃN ---
        ttk.Label(sidebar, text="ĐIỀU KHIỂN GÁN NHÃN", font=("Arial", 11, "bold")).pack(pady=(20, 5))
        
        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill=tk.X)
        
        self.btn_live = ttk.Button(btn_frame, text="🔴 Bật Live Camera", command=self.toggle_live_camera)
        self.btn_live.pack(fill=tk.X, pady=5)
        
        self.btn_capture_label = ttk.Button(btn_frame, text="📸 Chụp & Bắt đầu Gán nhãn", command=self.capture_and_label)
        self.btn_capture_label.pack(fill=tk.X, pady=5)
        
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        
        self.btn_load_label = ttk.Button(btn_frame, text="📁 Tải ảnh có sẵn để Gán nhãn", command=self.load_and_label)
        self.btn_load_label.pack(fill=tk.X, pady=5)

        # --- BẢNG CHÚ THÍCH ---
        ttk.Label(sidebar, text="HƯỚNG DẪN", font=("Arial", 10, "bold")).pack(pady=(20, 5))
        guide_text = (
            "1. Bấm 'Chụp & Bắt đầu Gán nhãn'\n"
            "2. Một cửa sổ hiện ra, KÉO CHUỘT để vẽ hộp\n"
            "3. Nhấn SPACE hoặc ENTER để chốt hộp\n"
            "4. Nhập mã lỗi (ID) vào hộp thoại\n"
            "5. Nhấn SPACE mà KHÔNG VẼ gì để LƯU & THOÁT"
        )
        tk.Label(sidebar, text=guide_text, justify=tk.LEFT, fg="gray").pack(anchor="w")

        # ==================== 2. CENTER PANEL (LIVE VIEW) ====================
        display_frame = ttk.Frame(self.root, padding="10")
        display_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frame_live = ttk.LabelFrame(display_frame, text="Camera Live View")
        frame_live.pack(expand=True, fill=tk.BOTH)
        
        self.canvas_live = tk.Canvas(frame_live, bg="#1e1e1e")
        self.canvas_live.pack(expand=True, fill=tk.BOTH)

    # ==========================================
    # CÁC HÀM ĐỔI THƯ MỤC
    # ==========================================
    def set_capture_dir(self):
        new_dir = filedialog.askdirectory(title="Chọn thư mục lưu Ảnh Chụp (Raw)")
        if new_dir:
            self.capture_dir = new_dir
            self.lbl_cap_dir.config(text=self.capture_dir)

    def set_dataset_dir(self):
        new_dir = filedialog.askdirectory(title="Chọn thư mục lưu Dataset YOLO")
        if new_dir:
            self.dataset_dir = new_dir
            self.lbl_data_dir.config(text=self.dataset_dir)

    # ==========================================
    # LOGIC CAMERA MVS (LIVE & CAPTURE)
    # ==========================================
    def toggle_live_camera(self):
        if self.is_live_running:
            self.is_live_running = False
            self.btn_live.config(text="🔴 Bật Live Camera")
        else:
            self.is_live_running = True
            self.btn_live.config(text="⏹ Tắt Live Camera")
            threading.Thread(target=self.live_camera_loop, daemon=True).start()

    def live_camera_loop(self):
        try:
            from MvImport.MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, MV_USB_DEVICE, MV_GIGE_DEVICE, MV_CC_DEVICE_INFO, MV_ACCESS_Exclusive, MV_FRAME_OUT
        except ImportError:
            self.is_live_running = False
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi Thư viện", "Không tìm thấy thư viện SDK Hikvision (MvImport)."))
            return

        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        
        if deviceList.nDeviceNum == 0:
            self.is_live_running = False
            self.root.after(0, lambda: self.btn_live.config(text="🔴 Bật Live Camera"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi", "Không tìm thấy hoặc chưa kết nối Camera Hikvision!"))
            return

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
        
        while getattr(self, 'is_live_running', False):
            ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
            ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
            
            if ret == 0:
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
                    display_frame = cv2.resize(frame, (800, 600))
                    self.root.after(0, self.show_image, display_frame, self.canvas_live)
                        
                self.cam.MV_CC_FreeImageBuffer(stOutFrame)

        self.cam.MV_CC_StopGrabbing()
        self.cam.MV_CC_CloseDevice()
        self.cam.MV_CC_DestroyHandle()
        self.cam = None
        self.root.after(0, lambda: self.canvas_live.delete("all"))

    def capture_and_label(self):
        if not self.is_live_running or self.latest_frame is None:
            messagebox.showwarning("Cảnh báo", "Vui lòng 'Bật Live Camera' trước khi chụp ảnh!")
            return
            
        # Lấy frame mới nhất
        frame = self.latest_frame.copy()
        
        # 1. Lưu ảnh gốc vào Raw Capture Dir
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"img_{timestamp}"
        
        raw_path = os.path.join(self.capture_dir, f"{base_name}.jpg")
        cv2.imwrite(raw_path, frame)
        print(f"Đã lưu ảnh gốc tại: {raw_path}")
        
        # 2. Bắt đầu luồng gán nhãn
        self.process_labeling(frame, base_name)

    def load_and_label(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.png *.jpeg *.bmp")])
        if not path: return
        
        frame = cv2.imread(path)
        if frame is None:
            messagebox.showerror("Lỗi", "Không thể đọc ảnh!")
            return
            
        base_name = os.path.splitext(os.path.basename(path))[0]
        self.process_labeling(frame, base_name)

    # ==========================================
    # LOGIC GÁN NHÃN YOLO (OPENCV ROI)
    # ==========================================
    def process_labeling(self, frame, base_name):
        dataset_img_path = os.path.join(self.dataset_dir, f"{base_name}.jpg")
        txt_path = os.path.join(self.dataset_dir, f"{base_name}.txt")
        
        # Lưu ảnh vào dataset_dir để đồng bộ với file txt
        cv2.imwrite(dataset_img_path, frame)
        
        clone = frame.copy()
        img_height, img_width = clone.shape[:2]
        window_name = f"Gán nhãn YOLO: {base_name}"
        
        # Thu nhỏ cửa sổ nếu ảnh quá to so với màn hình
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 1000, 800)

        box_count = 0
        while True:
            cv2.imshow(window_name, clone)
            
            # Hàm selectROI tích hợp sẵn của OpenCV (Nhấn SPACE/ENTER để chốt)
            roi = cv2.selectROI(window_name, clone, fromCenter=False, showCrosshair=True)
            x, y, w, h = roi

            # Nếu nhấn SPACE/ENTER mà không quét vùng nào (w=0, h=0) -> Thoát
            if w == 0 or h == 0:
                break 

            # ==================================================
            # THÊM ĐOẠN NÀY ĐỂ ÉP FOCUS VÀO POPUP TKINTER
            # ==================================================
            if hasattr(self, 'root') and self.root:
                self.root.attributes('-topmost', True)  # Ép Tkinter nổi lên trên cùng
                self.root.focus_force()                 # Ép nhận tín hiệu bàn phím

            # Bật Popup hỏi mã lỗi
            class_id = simpledialog.askstring("Nhập mã lỗi", "Nhập ID lỗi (0-5):\n(Nhấn Cancel để vẽ lại)", parent=self.root)
            
            # Trả lại trạng thái bình thường để không bị đè lên các app khác
            if hasattr(self, 'root') and self.root:
                self.root.attributes('-topmost', False)
            # ==================================================
            
            if class_id is None or class_id.strip() == "":
                continue # Nếu Cancel thì vẽ lại

            # Tính toán tọa độ YOLO Format
            x_center = (x + w / 2.0) / img_width
            y_center = (y + h / 2.0) / img_height
            norm_w = w / img_width
            norm_h = h / img_height

            # Ghi nối vào file txt
            with open(txt_path, "a") as f:
                f.write(f"{class_id.strip()} {x_center:.6f} {y_center:.6f} {norm_w:.6f} {norm_h:.6f}\n")
            
            box_count += 1

            # Vẽ lên clone để user thấy được box vừa gán
            cv2.rectangle(clone, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(clone, f"ID: {class_id}", (x, max(15, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.destroyWindow(window_name)
        
        if box_count > 0:
            messagebox.showinfo("Hoàn tất", f"Đã lưu {box_count} hộp (boxes) cho: {base_name}")
        else:
            # Nếu user thoát mà không vẽ box nào, có thể xóa file txt rỗng nếu muốn (Tuỳ chọn)
            print(f"Không có hộp nào được gán cho {base_name}.")
            
    # ==========================================
    # HÀM RENDER CANVAS TKINTER
    # ==========================================
    def show_image(self, cv_img, canvas_widget):
        canvas_widget.update_idletasks()
        c_w = canvas_widget.winfo_width()
        c_h = canvas_widget.winfo_height()
        if c_w < 10: c_w, c_h = 600, 500 
        
        h, w = cv_img.shape[:2]
        scale = min(c_w / w, c_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        
        img_resized = cv2.resize(cv_img, (new_w, new_h))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
            
        img_tk = ImageTk.PhotoImage(Image.fromarray(img_rgb))
        
        offset_x = (c_w - new_w) // 2
        offset_y = (c_h - new_h) // 2
        
        canvas_widget.delete("all")
        canvas_widget.create_image(offset_x, offset_y, anchor=tk.NW, image=img_tk)
        canvas_widget.image = img_tk 

    def on_closing(self):
        """Xử lý dọn dẹp bộ nhớ trước khi tắt phần mềm"""
        self.is_live_running = False
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = YoloLabelingApp(root)
    root.mainloop()