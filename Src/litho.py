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
    # SỬA LỖI 2: Dùng ngưỡng Epsilon an toàn chặn tràn số / nhiễu nội suy
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
        # SỬA LỖI 3: Dùng Numpy Vectorization tăng tốc thuật toán
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
# 2. MODULE CHÍNH (Đã sửa lỗi Sub-pixel Overlap)
# ==========================================
def preprocess_image(img_orig):
    img_balanced = smart_enhance(img_orig)
    img_denoised = cv2.GaussianBlur(img_balanced, (5, 5), 0)
    _, binary_mask = cv2.threshold(img_denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
   
    # BƯỚC 1: CLOSE (Dilation -> Erosion) 
    # Tác dụng: Lấp đầy các lỗ hổng bên trong khối, nối liền các vết nứt nhỏ.
    # Kernel (7,7) ở đây là hợp lý để khối được đặc (Solid)
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask_closed = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel_close)
   
    # BƯỚC 2: OPEN (Erosion -> Dilation)
    # SỬA Ở ĐÂY: Giảm Kernel từ (7,7) xuống (3,3) để tránh cắt đứt các mạch nối/ngã ba
    # Nó sẽ chỉ xóa các hạt bụi (nhiễu muối tiêu) cực nhỏ
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
          
        is_vertical = (h >= w * 0.9) and (h >= 15)
        is_horizontal = (w >= h * 0.9) and (w >= 15)
        
        aspect_ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 10
        if aspect_ratio > 15.0:  
            continue
            
        valid_boxes.append({
            'contour': cnt, 
            'area': area, 
            'bbox': (x, y, w, h),
            'is_vertical': is_vertical or not is_horizontal,
            'is_horizontal': is_horizontal,
            'solidity': solidity
        })
      
    valid_boxes.sort(key=lambda b: b['area'], reverse=True)
    return valid_boxes


def measure_cd_line_width(roi_mask, roi_gray, box_info, window_size=7, max_tolerance=2):
    x, y, w, h = box_info['bbox']
    result = {'pixel_cd': 0, 'subpixel_cd': 0.0, 'is_valid': False, 
              'pt1': None, 'pt2': None, 'direction': 'N/A'}

    if box_info['is_vertical'] or h >= w * 0.85:
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
            
            # SỬA LỖI 1: Trừ đi 1 để đảm bảo search window trái và phải không bao giờ dính nhau
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
            
            # SỬA LỖI 1: Tương tự như nhánh khối Dọc
            safe_win = max(1, min(4, int(best_px // 2) - 1))
            
            prof = roi_gray[:, best_idx]
            s_t = refine_edge_1d_abs(prof, int(t_edges[best_idx]), safe_win)
            s_b = refine_edge_1d_abs(prof, int(b_edges[best_idx]), safe_win)
          
            result['subpixel_cd'] = s_b - s_t
            result['pixel_cd'] = int(round(best_px))
            result['pt1'] = (int(x + best_idx), int(y + s_t))
            result['pt2'] = (int(x + best_idx), int(y + s_b))
            result['is_valid'] = True

    return result