import cv2
import numpy as np

# ==========================================
# MODULE 1: TOÁN HỌC & SUBPIXEL (Giữ nguyên)
# ==========================================
def refine_edge_1d_strict(profile, mask_idx, edge_type, window=3):
    """Tìm mép subpixel dựa trên cực trị Gradient."""
    grad = np.gradient(profile.astype(float))
    start = max(0, mask_idx - window)
    end = min(len(grad), mask_idx + window + 1)
    
    if start >= end: return float(mask_idx)
    window_grad = grad[start:end]
    
    if edge_type in ['left', 'top']:
        local_idx = np.argmin(window_grad) # Đáy dốc
    else:
        local_idx = np.argmax(window_grad) # Đỉnh dốc
        
    peak_idx = start + local_idx
    
    if peak_idx == 0 or peak_idx == len(grad) - 1: return float(peak_idx)
        
    y_m1 = grad[peak_idx - 1]
    y_0  = grad[peak_idx]
    y_p1 = grad[peak_idx + 1]
    
    denom = 2.0 * (y_m1 - 2.0 * y_0 + y_p1)
    if denom == 0: return float(peak_idx)
        
    offset = (y_m1 - y_p1) / denom
    offset = max(-1.0, min(1.0, offset)) 
    return float(peak_idx) + offset

# ==========================================
# MODULE 2: TIỀN XỬ LÝ (Tăng lực cắt rễ bằng dao phay 5x5)
# ==========================================
def preprocess_image(img_gray):
    debug_steps = []
    debug_steps.append(("[Bước 0] Ảnh xám gốc", img_gray.copy()))

    # 1. Làm mượt nhẹ
    blurred = cv2.GaussianBlur(img_gray, (5, 5), 0)

    # 2. Tăng tương phản
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)
    
    # 3. Phân ngưỡng an toàn
    otsu_thresh_val, _ = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, mask = cv2.threshold(enhanced, otsu_thresh_val * 0.9, 255, cv2.THRESH_BINARY_INV)
    debug_steps.append(("[Bước 1] Cắt ngưỡng", mask.copy()))

    # --- BƯỚC SỬA LỖI: TĂNG LỰC CẮT RỄ ---
    # Thay vì (3, 3), dùng (5, 5) để "chặt" đứt lìa các rễ to dính vào khối
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask_opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
    debug_steps.append(("[Bước 2] Chặt rễ (Dao 5x5)", mask_opened.copy()))
    
    # --- BƯỚC LỌC HÌNH HỌC ---
    contours, _ = cv2.findContours(mask_opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    clean_mask = np.zeros_like(mask)
    
    if contours:
        areas = [cv2.contourArea(cnt) for cnt in contours]
        max_area = max(areas) if areas else 0
        
        for cnt, area in zip(contours, areas):
            if area < 50: 
                continue
                
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0: continue
            
            thickness = area / perimeter
            
            epsilon = 0.015 * perimeter
            approx = cv2.approxPolyDP(cnt, epsilon, True)
            so_khuc_cua = len(approx)
            
            # Khối chính hoặc nhánh hình học vuông vức
            is_main_body = area > (max_area * 0.2)
            is_geometric_branch = (thickness > 3.0) and (so_khuc_cua < 15)
            
            if is_main_body or is_geometric_branch:
                cv2.drawContours(clean_mask, [cnt], -1, 255, -1) 
                
    debug_steps.append(("[Bước 3] Khối đã lọc", clean_mask.copy()))

    # --- BƯỚC BÙ NÉT (QUAN TRỌNG) ---
    # Vì dùng dao 5x5 nên các góc vuông của khối chính có thể bị mòn hơi bo tròn.
    # Ta dùng bitwise_and chập cái khối sạch (vừa lọc) với cái mask gốc (sắc nét)
    # để lấy lại 100% hình dáng vuông vức ban đầu, rác bị đứt rồi thì sẽ không quay lại được.
    final_mask = cv2.bitwise_and(clean_mask, mask)
    debug_steps.append(("[Bước 4] Final Mask (Bù góc vuông)", final_mask.copy()))

    return enhanced, final_mask, debug_steps

# ==========================================
# MODULE 3: TÌM VÀ LỌC CÁC VÙNG ĐO CẦN THIẾT
# ==========================================
def find_valid_bounding_boxes(mask_clean, img_shape, margin=3):
    """Tìm Bounding Box và phân loại dính viền"""
    img_h, img_w = img_shape[:2]
    contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    valid_boxes = []
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        x, y, w, h = cv2.boundingRect(cnt)
        
        # Lọc rác li ti
        if area < 200:
            continue
            
        # Đánh dấu dính viền (Không đo CD, chỉ tính diện tích)
        is_on_edge = (x <= margin or y <= margin or 
                      (x + w) >= (img_w - margin) or 
                      (y + h) >= (img_h - margin))
            
        valid_boxes.append({
            'contour': cnt,
            'area': area,
            'bbox': (x, y, w, h),
            'is_on_edge': is_on_edge
        })
        
    return valid_boxes

# ==========================================
# MODULE 4: TÍNH TOÁN KÍCH THƯỚC CD
# ==========================================
def measure_cd_line_width(roi_mask, roi_gray, box):
    """Quét mask trục X/Y để tìm vùng ổn định và tính Gradient Subpixel CD"""
    x, y, w, h = box['bbox']
    window_size = 7
    max_tolerance = 3
    min_valid_dist = 5
    
    best_pixel_cd = float('inf')
    best_idx = None
    scan_axis = None 

    # --- BƯỚC 1: QUÉT MASK TRỤC Y ---
    l_edges = np.full(h, np.nan); r_edges = np.full(h, np.nan)
    for row in range(h):
        nz = np.where(roi_mask[row, :] > 0)[0]
        if len(nz) > 0: l_edges[row], r_edges[row] = nz[0], nz[-1]
    
    widths_y = r_edges - l_edges + 1
    for i in range(h - window_size):
        win = widths_y[i:i+window_size]
        if np.isnan(win).any(): continue
        if (np.max(win) - np.min(win)) <= max_tolerance:
            mid_idx = i + window_size // 2
            if min_valid_dist < widths_y[mid_idx] < best_pixel_cd:
                best_pixel_cd = widths_y[mid_idx]
                best_idx = mid_idx
                scan_axis = 'Y'

    # --- BƯỚC 2: QUÉT MASK TRỤC X ---
    t_edges = np.full(w, np.nan); b_edges = np.full(w, np.nan)
    for col in range(w):
        nz = np.where(roi_mask[:, col] > 0)[0]
        if len(nz) > 0: t_edges[col], b_edges[col] = nz[0], nz[-1]
        
    heights_x = b_edges - t_edges + 1
    for i in range(w - window_size):
        win = heights_x[i:i+window_size]
        if np.isnan(win).any(): continue
        if (np.max(win) - np.min(win)) <= max_tolerance:
            mid_idx = i + window_size // 2
            if min_valid_dist < heights_x[mid_idx] < best_pixel_cd:
                best_pixel_cd = heights_x[mid_idx]
                best_idx = mid_idx
                scan_axis = 'X'

    # Nếu không tìm được trục quét hợp lệ
    if scan_axis is None:
        return {'pixel_cd': 0, 'subpixel_cd': 0.0, 'pt1': None, 'pt2': None, 'direction': 'N/A', 'is_valid': False}

    # --- BƯỚC 3: TÍNH SUBPIXEL VỚI CỬA SỔ ĐỘNG ---
    safe_window = max(1, min(4, int(best_pixel_cd // 2) - 1))
    
    if scan_axis == 'Y':
        row_y = best_idx
        mask_left, mask_right = int(l_edges[best_idx]), int(r_edges[best_idx])
        profile_gray = roi_gray[row_y, :]
        
        sub_left = refine_edge_1d_strict(profile_gray, mask_left, 'left', window=safe_window)
        sub_right = refine_edge_1d_strict(profile_gray, mask_right, 'right', window=safe_window)
        
        return {
            'pixel_cd': best_pixel_cd,
            'subpixel_cd': sub_right - sub_left,
            'pt1': (int(x + sub_left), int(y + row_y)),
            'pt2': (int(x + sub_right), int(y + row_y)),
            'direction': 'Y', 'is_valid': True
        }
        
    elif scan_axis == 'X':
        col_x = best_idx
        mask_top, mask_bot = int(t_edges[best_idx]), int(b_edges[best_idx])
        profile_gray = roi_gray[:, col_x]
        
        sub_top = refine_edge_1d_strict(profile_gray, mask_top, 'top', window=safe_window)
        sub_bot = refine_edge_1d_strict(profile_gray, mask_bot, 'bottom', window=safe_window)
        
        return {
            'pixel_cd': best_pixel_cd,
            'subpixel_cd': sub_bot - sub_top,
            'pt1': (int(x + col_x), int(y + sub_top)),
            'pt2': (int(x + col_x), int(y + sub_bot)),
            'direction': 'X', 'is_valid': True
        }

# ==========================================
# MODULE 5: LUỒNG CHẠY CHÍNH DÀNH CHO UI
# ==========================================
def run_etching_inspection_pipeline(image_path):
    """Hàm tổng hợp kết quả, sẵn sàng trả về dữ liệu thuần cho giao diện"""
    img_gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img_gray is None: return None, None, [], []

    # 1. Tiền xử lý
    enhanced_gray, mask_clean, debug_steps = preprocess_image(img_gray)
    
    # 2. Tìm Bounding Boxes
    boxes = find_valid_bounding_boxes(mask_clean, img_gray.shape)
    
    # 3. Chuẩn bị ảnh màu để UI vẽ lên sau này
    img_orig_rgb = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2RGB)
    
    # SỬA LỖI: img_denoised không tồn tại, thay bằng enhanced_gray
    processed_base_rgb = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2RGB)
    
    results_list = []
    
    # 4. Quét từng Box và đo đạc
    for block_id, box in enumerate(boxes, start=1):
        x, y, w, h = box['bbox']
        area = box['area']
        
        # Nếu box bị dính viền, chỉ lưu diện tích
        if box.get('is_on_edge', False):
            results_list.append({
                'id': f"B_{block_id}", 'x': x, 'y': y, 'w': w, 'h': h,
                'area': area, 'pixel_cd': 0, 'subpixel_cd': 0.0,
                'is_valid': False, 'pt1': None, 'pt2': None,
                'direction': 'N/A', 'status': 'Dính Viền'
            })
            continue
            
        # Cắt ROI cho vùng hợp lệ
        local_mask = np.zeros_like(mask_clean)
        cv2.drawContours(local_mask, [box['contour']], -1, 255, -1)
        
        roi_mask = local_mask[y:y+h, x:x+w]
        
        # SỬA LỖI: img_denoised không tồn tại, thay bằng enhanced_gray
        roi_gray = enhanced_gray[y:y+h, x:x+w] # Dùng ảnh đã giảm nhiễu để tính Gradient mượt hơn
        
        cd_data = measure_cd_line_width(roi_mask, roi_gray, box)
        status_str = "OK" if cd_data['is_valid'] else "FAIL_CD"
        
        results_list.append({
            'id': f"B_{block_id}", 'x': x, 'y': y, 'w': w, 'h': h,
            'area': area, 
            'pixel_cd': cd_data['pixel_cd'], 
            'subpixel_cd': cd_data['subpixel_cd'],
            'is_valid': cd_data['is_valid'], 
            'pt1': cd_data['pt1'], 'pt2': cd_data['pt2'],
            'direction': cd_data['direction'], 
            'status': status_str
        })

    # SỬA LỖI: Trả về đúng tên biến đã khai báo
    return img_orig_rgb, processed_base_rgb, results_list, debug_steps

from PIL import Image, ImageTk
import cv2

def process_and_display_etching(self, file_path):
    """
    Hàm này nằm trong Class UI của Tkinter.
    self.image_label là widget Label dùng để hiển thị ảnh.
    """
    # 1. Gọi đường ống xử lý backend
    orig_rgb, processed_rgb, results = run_etching_inspection_pipeline(file_path)
    
    if orig_rgb is None:
        print("Lỗi: Không thể đọc hoặc xử lý ảnh!")
        return

    # 2. Tạo một bản sao để vẽ vời (Drawing Layer)
    img_draw = orig_rgb.copy()

    # 3. Duyệt qua kết quả và vẽ lên ảnh
    for item in results:
        x, y, w, h = item['x'], item['y'], item['w'], item['h']
        box_id = item['id']
        status = item['status']
        
        if status == 'Dính Viền':
            # Vùng dính viền: Vẽ màu Vàng/Cam, KHÔNG vẽ line CD
            color = (0, 255, 255) # BGR: Vàng
            cv2.rectangle(img_draw, (x, y), (x+w, y+h), color, 2)
            cv2.putText(img_draw, f"{box_id} [Edge]", (x, y - 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        
        elif item['is_valid']:
            # Vùng hợp lệ (Đo thành công): Vẽ màu Xanh lá, vẽ line CD màu Đỏ
            color = (0, 255, 0) # BGR: Xanh lá
            cv2.rectangle(img_draw, (x, y), (x+w, y+h), color, 2)
            
            # Đảm bảo pt1, pt2 tồn tại trước khi vẽ để chống crash app
            if item['pt1'] and item['pt2']:
                cv2.line(img_draw, item['pt1'], item['pt2'], (0, 0, 255), 2)
                cv2.circle(img_draw, item['pt1'], 3, (0, 0, 255), -1)
                cv2.circle(img_draw, item['pt2'], 3, (0, 0, 255), -1)
                
            cv2.putText(img_draw, f"{box_id} CD:{item['subpixel_cd']:.2f}", (x, y - 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        
        else:
            # Các lỗi khác (VD: Lệch Trục, FAIL_CD): Vẽ màu Đỏ
            color = (0, 0, 255) # BGR: Đỏ
            cv2.rectangle(img_draw, (x, y), (x+w, y+h), color, 2)
            cv2.putText(img_draw, f"{box_id} [{status}]", (x, y - 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    # 4. Chuyển đổi hệ màu từ OpenCV (BGR) sang Tkinter/PIL (RGB)
    img_draw_rgb = cv2.cvtColor(img_draw, cv2.COLOR_BGR2RGB)
    
    # Resize ảnh lại cho vừa màn hình giao diện (nếu cần)
    # Ví dụ: fix cứng chiều rộng 800px, giữ nguyên tỷ lệ
    display_width = 800
    ratio = display_width / float(img_draw_rgb.shape[1])
    display_height = int(img_draw_rgb.shape[0] * ratio)
    img_resized = cv2.resize(img_draw_rgb, (display_width, display_height))

    # 5. Đưa lên Tkinter Label
    pi = Image.fromarray(img_resized)
    self.tk_image = ImageTk.PhotoImage(pi) # Nhớ lưu vào self để tránh bị Garbage Collector xoá mất
    
    # Cập nhật Label trên UI (Giả sử bạn có widget tên là self.image_label)
    self.image_label.config(image=self.tk_image)
    
    # Tùy chọn: Bạn có thể đưa biến `results` này vào một hàm khác để đổ dữ liệu ra bảng Treeview (Excel) nếu có
    # self.update_table_data(results)

import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import cv2
import numpy as np

class EtchingMeasurementApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Etching Inspection - Step-by-Step Debugger")
        self.root.geometry("1400x750")

        # --- BIẾN TRẠNG THÁI DEBUG ---
        self.debug_steps = []
        self.current_step = 0
        self.tk_image_orig = None 
        self.tk_image_proc = None

        # --- GIAO DIỆN ---
        self.frame_top = tk.Frame(self.root, pady=10)
        self.frame_top.pack(fill=tk.X)
        tk.Button(self.frame_top, text="📂 Mở ảnh Etching", font=("Arial", 12, "bold"), 
                  bg="#4CAF50", fg="white", command=self.load_image).pack()

        self.frame_images = tk.Frame(self.root)
        self.frame_images.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        # Cột Trái: Ảnh Gốc + Vẽ Kết Quả
        self.frame_left = tk.Frame(self.frame_images)
        self.frame_left.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        tk.Label(self.frame_left, text="[ Ảnh Gốc Đo Lường ]", font=("Arial", 14, "bold"), bg="#e0e0e0").pack(fill=tk.X)
        self.image_label_orig = tk.Label(self.frame_left, bg="black")
        self.image_label_orig.pack(expand=True, fill=tk.BOTH)

        # Cột Phải: Các bước Tiền xử lý
        self.frame_right = tk.Frame(self.frame_images)
        self.frame_right.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH, padx=5)
        self.lbl_step_name = tk.Label(self.frame_right, text="[ Quá trình tiền xử lý ]", font=("Arial", 14, "bold"), bg="#e0e0e0", fg="blue")
        self.lbl_step_name.pack(fill=tk.X)
        
        self.image_label_proc = tk.Label(self.frame_right, bg="black")
        self.image_label_proc.pack(expand=True, fill=tk.BOTH)

        # Thanh điều hướng (Nút Next/Prev)
        self.frame_nav = tk.Frame(self.frame_right)
        self.frame_nav.pack(pady=5)
        tk.Button(self.frame_nav, text="◀ Bước Trước", font=("Arial", 11), width=15, command=self.prev_step).pack(side=tk.LEFT, padx=10)
        tk.Button(self.frame_nav, text="Bước Sau ▶", font=("Arial", 11), width=15, command=self.next_step).pack(side=tk.LEFT, padx=10)

    def load_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.bmp *.png *.jpg *.jpeg")])
        if file_path:
            # Gọi Pipeline và nhận debug_steps
            orig_rgb, _, results, steps = run_etching_inspection_pipeline(file_path)
            if orig_rgb is None: return

            self.debug_steps = steps

            # Vẽ kết quả cuối lên ảnh gốc bên trái
            drawn_orig = self.draw_results_on_image(orig_rgb, results)
            self.tk_image_orig = self.convert_for_tk(drawn_orig)
            self.image_label_orig.config(image=self.tk_image_orig)

            # Vẽ luôn kết quả (Drawn) thành [Bước cuối cùng] cho vào list debug
            drawn_proc = self.draw_results_on_image(orig_rgb.copy(), results)
            self.debug_steps.append(("[Bước 7] Chốt kết quả (Đo CD)", drawn_proc))

            # Mặc định hiển thị bước cuối
            self.current_step = len(self.debug_steps) - 1
            self.update_debug_view()

    def update_debug_view(self):
        if not self.debug_steps: return
        
        step_name, step_img = self.debug_steps[self.current_step]
        self.lbl_step_name.config(text=f"{self.current_step}/{len(self.debug_steps)-1}: {step_name}")

        # Kiểm tra xem ảnh là Grayscale (1 kênh) hay Color (3 kênh BGR) để convert cho đúng
        if len(step_img.shape) == 2:
            img_rgb = cv2.cvtColor(step_img, cv2.COLOR_GRAY2RGB)
        else:
            img_rgb = cv2.cvtColor(step_img, cv2.COLOR_BGR2RGB)

        self.tk_image_proc = self.convert_for_tk(img_rgb, target_width=600)
        self.image_label_proc.config(image=self.tk_image_proc)

    def next_step(self):
        if self.current_step < len(self.debug_steps) - 1:
            self.current_step += 1
            self.update_debug_view()

    def prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_debug_view()

    def draw_results_on_image(self, base_image, results):
        img_draw = base_image.copy()
        for item in results:
            x, y, w, h = item['x'], item['y'], item['w'], item['h']
            color = (0, 255, 0) if item['is_valid'] else (0, 0, 255)
            cv2.rectangle(img_draw, (x, y), (x+w, y+h), color, 2)
            if item['is_valid'] and item['pt1'] and item['pt2']:
                cv2.line(img_draw, item['pt1'], item['pt2'], (0, 0, 255), 2)
        return img_draw

    def convert_for_tk(self, img_array, target_width=600):
        ratio = target_width / float(img_array.shape[1])
        height = int(img_array.shape[0] * ratio)
        img_resized = cv2.resize(img_array, (target_width, height))
        return ImageTk.PhotoImage(Image.fromarray(img_resized))

if __name__ == "__main__":
    root = tk.Tk()
    app = EtchingMeasurementApp(root)
    root.mainloop()