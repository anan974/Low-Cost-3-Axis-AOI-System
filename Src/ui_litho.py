import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import cv2
import numpy as np
import litho # Import file thuật toán nguyên bản của bạn

class LithoDebugUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Công cụ Debug Thuật toán Litho (Từng bước)")
        self.root.geometry("1000x750")

        self.steps_images = []
        self.steps_titles = []
        self.current_step = 0

        self.setup_ui()

    def setup_ui(self):
        # --- Bảng điều khiển trên cùng ---
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        btn_load = ttk.Button(top_frame, text="📁 Chọn Ảnh Khảo Sát", command=self.load_image)
        btn_load.pack(side=tk.LEFT, padx=5)

        self.btn_prev = ttk.Button(top_frame, text="◀ Lùi Bước", command=self.prev_step, state=tk.DISABLED)
        self.btn_prev.pack(side=tk.LEFT, padx=5)

        self.lbl_step_info = ttk.Label(top_frame, text="Bước: 0/0", font=("Arial", 11, "bold"))
        self.lbl_step_info.pack(side=tk.LEFT, padx=15)

        self.btn_next = ttk.Button(top_frame, text="Tiến Bước ▶", command=self.next_step, state=tk.DISABLED)
        self.btn_next.pack(side=tk.LEFT, padx=5)

        self.lbl_title = ttk.Label(top_frame, text="Chưa có dữ liệu", font=("Arial", 12, "bold"), foreground="blue")
        self.lbl_title.pack(side=tk.RIGHT, padx=10)

        # --- Khung hiển thị ảnh ---
        self.canvas = tk.Canvas(self.root, bg="#2b2b2b")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.png *.bmp")])
        if not path:
            return
        
        img_bgr = cv2.imread(path)
        if img_bgr is None:
            messagebox.showerror("Lỗi", "Không thể đọc ảnh!")
            return

        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        self.process_image(img_bgr, img_gray)

    def process_image(self, img_bgr, img_gray):
        self.steps_images.clear()
        self.steps_titles.clear()
        self.current_step = 0

        # Bước 1: Ảnh gốc
        self.steps_images.append(img_bgr.copy())
        self.steps_titles.append("1. Ảnh gốc (Original)")

        # Bước 2: Tiền xử lý (Cân bằng & Mask)
        # Giữ nguyên hàm litho.preprocess_image của bạn
        img_balanced, mask_clean = litho.preprocess_image(img_gray)
        
        self.steps_images.append(img_balanced)
        self.steps_titles.append("2. Ảnh Cân bằng sáng (CLAHE/Gamma)")
        
        self.steps_images.append(mask_clean)
        self.steps_titles.append("3. Mask Tiền xử lý (Morphology)")

        # Bước 3: Tìm Bounding Box
        valid_boxes = litho.find_valid_bounding_boxes(mask_clean, img_gray, img_gray.shape[:2])
        
        img_boxes = img_bgr.copy()
        for i, box in enumerate(valid_boxes):
            bx, by, bw, bh = box['bbox']
            cv2.rectangle(img_boxes, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
            cv2.putText(img_boxes, f"Box {i+1}", (bx, by-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
        self.steps_images.append(img_boxes)
        self.steps_titles.append(f"4. Tìm Boxes (Lọc tỷ lệ & Solidity) - Tìm thấy: {len(valid_boxes)} box")

        # Bước 4: Đo Sub-pixel CD
        img_final = img_bgr.copy()
        measured_count = 0
        
        for box in valid_boxes:
            # Tạo ROI y hệt như code chính
            bx, by, bw, bh = box['bbox']
            
            # Tạo local mask contour
            local_mask = np.zeros_like(mask_clean)
            cv2.drawContours(local_mask, [box['contour']], -1, 255, -1)
            roi_mask = local_mask[by:by+bh, bx:bx+bw]
            roi_gray = img_gray[by:by+bh, bx:bx+bw]
            
            # Gọi hàm đo lường nguyên bản
            res = litho.measure_cd_line_width(roi_mask, roi_gray, box)
            
            if res['is_valid']:
                measured_count += 1
                pt1, pt2 = res['pt1'], res['pt2']
                cv2.line(img_final, pt1, pt2, (0, 0, 255), 2)
                cv2.putText(img_final, f"{res['subpixel_cd']:.1f}", (bx, by+bh+15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            else:
                # Nếu không hợp lệ, vẽ viền đỏ để biết box nào bị từ chối ở khâu cuối
                cv2.rectangle(img_final, (bx, by), (bx+bw, by+bh), (0, 0, 255), 1)

        self.steps_images.append(img_final)
        self.steps_titles.append(f"5. Kết quả Đo CD (Đo thành công: {measured_count}/{len(valid_boxes)})")

        self.update_display()
        self.btn_next.config(state=tk.NORMAL if len(self.steps_images) > 1 else tk.DISABLED)
        self.btn_prev.config(state=tk.DISABLED)

    def update_display(self):
        if not self.steps_images: return
        
        img_np = self.steps_images[self.current_step]
        title = self.steps_titles[self.current_step]

        # Convert OpenCV to PIL
        if len(img_np.shape) == 2:
            img_pil = Image.fromarray(img_np)
        else:
            img_pil = Image.fromarray(cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB))
        
        # Scale to fit canvas
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w < 10: canvas_w, canvas_h = 900, 600

        img_w, img_h = img_pil.size
        scale = min(canvas_w / img_w, canvas_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        
        img_pil = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
        img_tk = ImageTk.PhotoImage(img_pil)
        
        self.canvas.delete("all")
        self.canvas.create_image(canvas_w//2, canvas_h//2, anchor=tk.CENTER, image=img_tk)
        self.canvas.image = img_tk
        
        self.lbl_title.config(text=title)
        self.lbl_step_info.config(text=f"Bước: {self.current_step + 1}/{len(self.steps_images)}")

    def next_step(self):
        if self.current_step < len(self.steps_images) - 1:
            self.current_step += 1
            self.update_display()
            self.btn_prev.config(state=tk.NORMAL)
            if self.current_step == len(self.steps_images) - 1:
                self.btn_next.config(state=tk.DISABLED)

    def prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_display()
            self.btn_next.config(state=tk.NORMAL)
            if self.current_step == 0:
                self.btn_prev.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = LithoDebugUI(root)
    root.mainloop()