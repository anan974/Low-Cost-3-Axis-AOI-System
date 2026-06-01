# litho.py
# Module phân tích ảnh CD (Critical Dimension) từ ảnh grayscale
# Gồm các hàm xử lý ảnh thông minh, tìm cạnh sub-pixel, và class CDAnalyzer để tích hợp với UI.

import cv2
import numpy as np

# ==========================================
# 1. HELPER FUNCTIONS (Đã tối ưu & sửa lỗi an toàn)
# ==========================================
def refine_edge_1d_abs(profile, mask_idx, window=3):
    grad = np.gradient(profile.astype(float))
    abs_grad = np.abs(grad)
   
    start = max(0, mask_idx - window)
    end = min(len(abs_grad), mask_idx + window + 1)
    if start >= end: 
        return float(mask_idx)
      
    window_grad = abs_grad[start:end]
    local_idx = np.argmax(window_grad)
    peak_idx = start + local_idx
    if peak_idx == 0 or peak_idx == len(abs_grad) - 1: 
        return float(peak_idx)
      
    y_m1 = abs_grad[peak_idx - 1]
    y_0  = abs_grad[peak_idx]
    y_p1 = abs_grad[peak_idx + 1]
   
    denom = 2.0 * (y_m1 - 2.0 * y_0 + y_p1)
    if abs(denom) < 1e-6: 
        return float(peak_idx)
      
    offset = (y_m1 - y_p1) / denom
    offset = max(-1.0, min(1.0, offset))
    return float(peak_idx) + offset


def smart_enhance(img):
    mean_val = np.mean(img)
    if mean_val < 70:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(img)
    elif mean_val > 120:
        gamma = 2.5
        table = (np.arange(0, 256) / 255.0) ** gamma * 255
        return cv2.LUT(img, table.astype(np.uint8))
    else:
        return img.copy()
   

def is_spotted_texture(roi_gray, roi_mask, stdev_threshold=35.0):
    if roi_gray.size == 0 or np.count_nonzero(roi_mask) == 0:
        return True
    masked_pixels = roi_gray[roi_mask > 0]
    if masked_pixels.size == 0:
        return True
    std_dev = np.std(masked_pixels)
    return std_dev > stdev_threshold


# ==========================================
# 2. MODULE CHÍNH (Đã sửa lỗi Sub-pixel Overlap và thêm fallback)
# ==========================================
def preprocess_image(img_orig):
    img_balanced = smart_enhance(img_orig)
    img_denoised = cv2.GaussianBlur(img_balanced, (5, 5), 0)
    _, binary_mask = cv2.threshold(img_denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
   
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask_closed = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel_close)
   
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask_clean = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel_open)
   
    return img_balanced, mask_clean


def find_valid_bounding_boxes(mask_clean, img_gray, img_shape, margin=5):
    img_h, img_w = img_shape
    contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
   
    MIN_AREA = 200      
    MIN_SOLIDITY = 0.22  
    MIN_WIDTH = 12
    MIN_HEIGHT = 12
    STDEV_TEXTURE_FILTER = 38.0   

    valid_boxes = []
   
    for cnt in contours:
        area = cv2.contourArea(cnt)
        x, y, w, h = cv2.boundingRect(cnt)
       
        if area < MIN_AREA or w < MIN_WIDTH or h < MIN_HEIGHT:
            continue
          
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        solidity = area / float(hull_area) if hull_area > 0 else 0.0

        roi_gray = img_gray[y:y+h, x:x+w]
        roi_mask = mask_clean[y:y+h, x:x+w]
       
        if is_spotted_texture(roi_gray, roi_mask, STDEV_TEXTURE_FILTER):
            continue
          
        if solidity < MIN_SOLIDITY:
            continue
          
        # SỬA LỖI: Xác định hướng rõ ràng (dọc nếu cao >= rộng)
        is_vertical = (h >= w) and (h >= 15)
        is_horizontal = (w > h) and (w >= 15)
        
        # Nếu cả hai đều False (do kích thước nhỏ quá) thì bỏ qua
        if not (is_vertical or is_horizontal):
            continue
            
        aspect_ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 10
        if aspect_ratio > 15.0:  
            continue
            
        valid_boxes.append({
            'contour': cnt, 
            'area': area, 
            'bbox': (x, y, w, h),
            'is_vertical': is_vertical,
            'is_horizontal': is_horizontal,
            'solidity': solidity
        })
      
    valid_boxes.sort(key=lambda b: b['area'], reverse=True)
    return valid_boxes


def measure_cd_line_width(roi_mask, roi_gray, box_info, window_size=7, max_tolerance=2):
    x, y, w, h = box_info['bbox']
    result = {'pixel_cd': 0, 'subpixel_cd': 0.0, 'is_valid': False, 
              'pt1': None, 'pt2': None, 'direction': 'N/A'}

    if box_info['is_vertical']:
        result['direction'] = 'DỌC'
        l_edges, r_edges = np.full(h, np.nan), np.full(h, np.nan)
        
        for row in range(h):
            nz = np.where(roi_mask[row, :] > 0)[0]
            if len(nz) > 1:
                l_edges[row], r_edges[row] = nz[0], nz[-1]
      
        widths = r_edges - l_edges + 1
        valid_candidates = []
      
        for i in range(h - window_size + 1):
            win = widths[i:i+window_size]
            if not np.isnan(win).any() and (np.max(win) - np.min(win)) <= max_tolerance:
                mid = i + window_size // 2
                if widths[mid] >= 8:
                    valid_candidates.append((mid, float(widths[mid])))

        if valid_candidates:
            valid_candidates.sort(key=lambda c: c[1])
            best_idx, best_px = valid_candidates[0]
            safe_win = max(1, min(4, int(best_px // 2) - 1))
            prof = roi_gray[best_idx, :]
            s_l = refine_edge_1d_abs(prof, int(l_edges[best_idx]), safe_win)
            s_r = refine_edge_1d_abs(prof, int(r_edges[best_idx]), safe_win)
            result['subpixel_cd'] = s_r - s_l
            result['pixel_cd'] = int(round(best_px))
            result['pt1'] = (int(x + s_l), int(y + best_idx))
            result['pt2'] = (int(x + s_r), int(y + best_idx))
            result['is_valid'] = True
        else:
            # FALLBACK: lấy trung bình (hoặc median) của tất cả widths hợp lệ
            all_widths = widths[~np.isnan(widths)]
            if len(all_widths) > 0:
                best_px = np.median(all_widths)
                # Chọn hàng giữa để vẽ
                best_idx = h // 2
                # Tìm cạnh trái và phải gần nhất tại hàng đó
                if not np.isnan(l_edges[best_idx]) and not np.isnan(r_edges[best_idx]):
                    s_l = l_edges[best_idx]
                    s_r = r_edges[best_idx]
                else:
                    # Nếu hàng giữa bị lỗi, tìm hàng bất kỳ có cạnh
                    valid_rows = np.where(~np.isnan(l_edges) & ~np.isnan(r_edges))[0]
                    if len(valid_rows) > 0:
                        best_idx = valid_rows[0]
                        s_l = l_edges[best_idx]
                        s_r = r_edges[best_idx]
                    else:
                        s_l = s_r = 0
                result['subpixel_cd'] = float(best_px)
                result['pixel_cd'] = int(round(best_px))
                result['pt1'] = (int(x + s_l), int(y + best_idx))
                result['pt2'] = (int(x + s_r), int(y + best_idx))
                result['is_valid'] = True

    else:  # NGANG
        result['direction'] = 'NGANG'
        t_edges, b_edges = np.full(w, np.nan), np.full(w, np.nan)
        
        for col in range(w):
            nz = np.where(roi_mask[:, col] > 0)[0]
            if len(nz) > 1:
                t_edges[col], b_edges[col] = nz[0], nz[-1]
              
        heights = b_edges - t_edges + 1
        valid_candidates = []
      
        for i in range(w - window_size + 1):
            win = heights[i:i+window_size]
            if not np.isnan(win).any() and (np.max(win) - np.min(win)) <= max_tolerance:
                mid = i + window_size // 2
                if heights[mid] >= 8:
                    valid_candidates.append((mid, float(heights[mid])))

        if valid_candidates:
            valid_candidates.sort(key=lambda c: c[1])
            best_idx, best_px = valid_candidates[0]
            safe_win = max(1, min(4, int(best_px // 2) - 1))
            prof = roi_gray[:, best_idx]
            s_t = refine_edge_1d_abs(prof, int(t_edges[best_idx]), safe_win)
            s_b = refine_edge_1d_abs(prof, int(b_edges[best_idx]), safe_win)
            result['subpixel_cd'] = s_b - s_t
            result['pixel_cd'] = int(round(best_px))
            result['pt1'] = (int(x + best_idx), int(y + s_t))
            result['pt2'] = (int(x + best_idx), int(y + s_b))
            result['is_valid'] = True
        else:
            all_heights = heights[~np.isnan(heights)]
            if len(all_heights) > 0:
                best_px = np.median(all_heights)
                best_idx = w // 2
                if not np.isnan(t_edges[best_idx]) and not np.isnan(b_edges[best_idx]):
                    s_t = t_edges[best_idx]
                    s_b = b_edges[best_idx]
                else:
                    valid_cols = np.where(~np.isnan(t_edges) & ~np.isnan(b_edges))[0]
                    if len(valid_cols) > 0:
                        best_idx = valid_cols[0]
                        s_t = t_edges[best_idx]
                        s_b = b_edges[best_idx]
                    else:
                        s_t = s_b = 0
                result['subpixel_cd'] = float(best_px)
                result['pixel_cd'] = int(round(best_px))
                result['pt1'] = (int(x + best_idx), int(y + s_t))
                result['pt2'] = (int(x + best_idx), int(y + s_b))
                result['is_valid'] = True

    return result


# ==========================================
# 3. CLASS WRAPPER DÀNH CHO UI
# ==========================================
class CDAnalyzer:
    """
    Phân tích ảnh grayscale để đo chiều rộng CD (Critical Dimension).
    Sử dụng các hàm xử lý ảnh đã được tối ưu.
    """
    def __init__(self, calibration_um_per_pixel=1.0):
        """
        calibration_um_per_pixel: tỷ lệ chuyển đổi từ pixel sang micron.
                                 Mặc định = 1.0 (trả về pixel).
        """
        self.calibration = calibration_um_per_pixel

    def analyze(self, img_gray):
        """
        Đầu vào: ảnh grayscale (numpy array, dtype=uint8)
        Đầu ra: dict chứa kết quả đo.
        Kết quả mẫu:
        {
            'success': True,
            'measurements': [
                {
                    'cd_pixel': 12.34,
                    'cd_um': 12.34 * calib,
                    'direction': 'DỌC',
                    'bbox': (x, y, w, h),
                    'pt1': (x1, y1),
                    'pt2': (x2, y2),
                    'pixel_rough': 12
                },
                ...
            ]
        }
        Nếu không thành công: {'success': False, 'measurements': [], 'message': 'lý do'}
        """
        # 1. Tiền xử lý
        img_balanced, mask_clean = preprocess_image(img_gray)

        # 2. Tìm các bounding box hợp lệ
        boxes = find_valid_bounding_boxes(mask_clean, img_balanced, img_gray.shape)
        if not boxes:
            return {'success': False, 'measurements': [], 'message': 'Không tìm thấy đối tượng nào'}

        # 3. Đo CD cho từng box
        results = []
        for box in boxes:
            x, y, w, h = box['bbox']
            roi_gray = img_balanced[y:y+h, x:x+w]
            roi_mask = mask_clean[y:y+h, x:x+w]

            # Đảm bảo hướng đã được xác định đúng (có thể box đã có sẵn)
            # Đảm bảo hướng đã được xác định đúng (có thể box đã có sẵn)
            meas = measure_cd_line_width(roi_mask, roi_gray, box)
            if meas['is_valid']:
                # TRẢ VỀ CHUẨN KEY CHO ui.py
                results.append({
                    'cd_pixel': meas['pixel_cd'],           # Giá trị pixel nguyên (int)
                    'subpixel_cd': meas['subpixel_cd'],     # Giá trị pixel thực (float)
                    'cd_um': meas['subpixel_cd'] * self.calibration,
                    'direction': meas['direction'],
                    'bbox': (x, y, w, h),
                    'pt1': meas['pt1'],
                    'pt2': meas['pt2']
                })

        if not results:
            return {'success': False, 'measurements': [], 'message': 'Đo thất bại (không tìm được cạnh ổn định)'}

        # TRẢ VỀ THÊM CẢ ẢNH TIỀN XỬ LÝ VÀ MASK CHO ui.py (để tính diện tích)
        return {
            'success': True, 
            'measurements': results,
            'preprocessed_img': img_balanced,
            'mask_clean': mask_clean
        }

    def analyze_and_draw(self, img_gray, img_color=None):
        """
        Như analyze nhưng trả về thêm ảnh đã vẽ các điểm đo lên.
        Nếu img_color không được cung cấp, tự tạo ảnh màu từ ảnh xám.
        Trả về: (result_dict, annotated_image)
        """
        result = self.analyze(img_gray)
        if not result['success']:
            return result, None

        # Tạo ảnh để vẽ
        if img_color is None:
            img_color = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
        else:
            img_color = img_color.copy()

        for m in result['measurements']:
            pt1 = m['pt1']
            pt2 = m['pt2']
            # Vẽ đường kẻ đỏ giữa hai điểm cạnh
            if pt1 and pt2:
                cv2.line(img_color, pt1, pt2, (0, 0, 255), 2)
            # Vẽ hình chữ nhật bao quanh (xanh lá)
            x, y, w, h = m['bbox']
            cv2.rectangle(img_color, (x, y), (x+w, y+h), (0, 255, 0), 2)
            # Ghi kết quả lên ảnh
            if self.calibration != 1.0:
                text = f"{m['cd_um']:.2f} um"
            else:
                text = f"{m['cd_pixel']:.2f} px"
            cv2.putText(img_color, text, (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        return result, img_color