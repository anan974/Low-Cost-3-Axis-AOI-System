# test_litho_ui.py
# Giao diện test module litho: chọn ảnh, hiển thị kết quả đo CD

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
import numpy as np
from PIL import Image, ImageTk
import os

# Import module litho
from litho import CDAnalyzer

class LithoTestUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Test Litho - Đo CD trên ảnh")
        self.root.geometry("1200x700")
        
        # Khởi tạo analyzer (có thể điều chỉnh hệ số µm/pixel sau)
        self.analyzer = CDAnalyzer(calibration_um_per_pixel=1.0)
        self.current_image = None      # ảnh gốc (BGR)
        self.current_gray = None       # ảnh xám
        self.result_image = None       # ảnh đã vẽ kết quả (PIL)
        self.result_data = None         # dict kết quả từ analyze
        
        # --- Tạo giao diện ---
        # Khung trên: nút bấm và thông số
        top_frame = ttk.Frame(root, padding="5")
        top_frame.pack(fill=tk.X)
        
        btn_load = ttk.Button(top_frame, text="📂 Chọn ảnh", command=self.load_image)
        btn_load.pack(side=tk.LEFT, padx=5)
        
        # Ô nhập hệ số micron/pixel
        ttk.Label(top_frame, text="µm/pixel:").pack(side=tk.LEFT, padx=(10,2))
        self.entry_calib = ttk.Entry(top_frame, width=8)
        self.entry_calib.insert(0, "1.0")
        self.entry_calib.pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Cập nhật", command=self.update_calibration).pack(side=tk.LEFT, padx=5)
        
        # Nút đo (sau khi có ảnh)
        self.btn_measure = ttk.Button(top_frame, text="🔍 Đo CD", command=self.measure, state=tk.DISABLED)
        self.btn_measure.pack(side=tk.LEFT, padx=10)
        
        # Khung hiển thị ảnh (2 bên)
        display_frame = ttk.Frame(root, padding="5")
        display_frame.pack(fill=tk.BOTH, expand=True)
        
        # Bên trái: ảnh gốc
        left_frame = ttk.LabelFrame(display_frame, text="Ảnh gốc")
        left_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        self.canvas_orig = tk.Canvas(left_frame, bg="gray")
        self.canvas_orig.pack(expand=True, fill=tk.BOTH)
        
        # Bên phải: ảnh kết quả
        right_frame = ttk.LabelFrame(display_frame, text="Kết quả đo CD")
        right_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        self.canvas_result = tk.Canvas(right_frame, bg="gray")
        self.canvas_result.pack(expand=True, fill=tk.BOTH)
        
        # Khung hiển thị text kết quả
        text_frame = ttk.LabelFrame(root, text="Thông tin đo", padding="5")
        text_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.txt_result = tk.Text(text_frame, height=8, wrap=tk.WORD)
        self.txt_result.pack(fill=tk.BOTH, expand=True)
        
        # Thanh cuộn cho text
        scroll = ttk.Scrollbar(self.txt_result, command=self.txt_result.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_result.config(yscrollcommand=scroll.set)

        
        
    def load_image(self):
        path = filedialog.askopenfilename(
            title="Chọn ảnh",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff"), ("All files", "*.*")]
        )
        if not path:
            return
        # Đọc ảnh bằng OpenCV (BGR)
        img_bgr = cv2.imread(path)
        if img_bgr is None:
            messagebox.showerror("Lỗi", "Không thể đọc ảnh!")
            return
        self.current_image = img_bgr
        self.current_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        # Hiển thị ảnh gốc lên canvas bên trái
        self.show_image_on_canvas(self.current_image, self.canvas_orig)
        # Xóa ảnh kết quả cũ
        self.canvas_result.delete("all")
        self.txt_result.delete(1.0, tk.END)
        self.result_image = None
        self.result_data = None
        self.btn_measure.config(state=tk.NORMAL)
        
    def show_image_on_canvas(self, img_bgr, canvas, max_width=600, max_height=500):
        """Hiển thị ảnh BGR lên canvas, giữ tỷ lệ"""
        h, w = img_bgr.shape[:2]
        scale = min(max_width/w, max_height/h, 1.0)
        new_w, new_h = int(w*scale), int(h*scale)
        resized = cv2.resize(img_bgr, (new_w, new_h))
        # Chuyển BGR -> RGB
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=pil_img)
        canvas.config(width=new_w, height=new_h)
        canvas.create_image(new_w//2, new_h//2, anchor=tk.CENTER, image=imgtk)
        canvas.image = imgtk  # giữ tham chiếu
        # Lưu lại scale để có thể chuyển tọa độ nếu cần (tạm thời không dùng)
        canvas.scale_factor = scale
        canvas.orig_size = (w, h)
        
    def update_calibration(self):
        try:
            val = float(self.entry_calib.get())
            self.analyzer.calibration = val
            if self.result_data and self.result_data['success']:
                # Nếu đã có kết quả, cập nhật lại text
                self.display_results(self.result_data)
        except ValueError:
            messagebox.showerror("Lỗi", "µm/pixel phải là số thực")
    
    def measure(self):
        if self.current_gray is None:
            messagebox.showwarning("Cảnh báo", "Hãy chọn ảnh trước!")
            return
        # Gọi analyze
        result = self.analyzer.analyze(self.current_gray)
        self.result_data = result
        if not result['success']:
            self.txt_result.insert(tk.END, f"❌ Đo thất bại: {result.get('message', 'Không rõ lý do')}\n")
            self.canvas_result.delete("all")
            self.result_image = None
            return
        
        # Vẽ ảnh kết quả
        _, annotated_bgr = self.analyzer.analyze_and_draw(self.current_gray, self.current_image.copy())
        self.show_image_on_canvas(annotated_bgr, self.canvas_result)
        self.display_results(result)
        
    def display_results(self, result):
        self.txt_result.delete(1.0, tk.END)
        if not result['success']:
            self.txt_result.insert(tk.END, f"Lỗi: {result.get('message')}\n")
            return
        measurements = result['measurements']
        self.txt_result.insert(tk.END, f"✅ Tìm thấy {len(measurements)} đối tượng đo:\n\n")
        for i, m in enumerate(measurements, 1):
            um_val = m['cd_um']
            px_val = m['cd_pixel']
            direction = m['direction']
            rough = m['pixel_rough']
            self.txt_result.insert(tk.END, 
                f"📏 Đối tượng {i}:\n"
                f"   Hướng: {direction}\n"
                f"   Chiều rộng CD: {um_val:.3f} µm (≈ {px_val:.2f} pixel)\n"
                f"   Ước lượng thô: {rough} pixel\n"
                f"   Bounding box: {m['bbox']}\n\n"
            )
        # Nếu chỉ có 1 đối tượng, hiển thị thêm thông tin ngắn gọn
        if len(measurements) == 1:
            m = measurements[0]
            self.txt_result.insert(tk.END, f"👉 Kết luận: CD = {m['cd_um']:.3f} µm ({m['direction']})\n")

def main():
    root = tk.Tk()
    app = LithoTestUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()