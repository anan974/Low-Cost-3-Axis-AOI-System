import cv2
import numpy as np
import matplotlib.pyplot as plt
# ==========================================
# 1. HÀM DETECT: Tối ưu chống viền răng cưa & Lọc vật thể dính mép ảnh
# ==========================================
def detect_objects(image_path, min_area=500, border_margin=1):
    """
    Thêm border_margin: Khoảng cách an toàn tới mép ảnh. 
    Vật nào nằm trong vùng này sẽ bị loại bỏ.
    """
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Không thể đọc ảnh từ: {image_path}")
        
    # LẤY KÍCH THƯỚC ẢNH (Chiều cao, Chiều rộng)
    img_h, img_w = img.shape
    
    # Khử nhiễu
    blurred = cv2.GaussianBlur(img, (5, 5), 1.2)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Morphological Closing để làm mượt biên
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary_closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(binary_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    valid_objects = []
    object_coordinates = []
    
    for cnt in contours:
        if cv2.contourArea(cnt) >= min_area:
            x, y, w, h = cv2.boundingRect(cnt)
            
            # ---------------------------------------------------------
            # BỘ LỌC VIỀN: KIỂM TRA VẬT THỂ CÓ BỊ CẮT BỞI CAMERA KHÔNG
            # ---------------------------------------------------------
            is_touching_left = (x <= border_margin)
            is_touching_top = (y <= border_margin)
            is_touching_right = (x + w >= img_w - border_margin)
            is_touching_bottom = (y + h >= img_h - border_margin)
            
            # Nếu chạm bất kỳ mép nào -> Bỏ qua vật thể này
            if is_touching_left or is_touching_top or is_touching_right or is_touching_bottom:
                continue 
                
            # Nếu vật thể nằm trọn vẹn bên trong ảnh -> Đưa vào danh sách xử lý
            valid_objects.append(cnt)
            object_coordinates.append((x, y, w, h))
            
    return img, valid_objects, object_coordinates

# ==========================================
# 2. HÀM CLASSIFY SHAPES: Dùng Extent & Circularity
# ==========================================
def classify_shapes(contour):
    # Tâm vật thể
    M = cv2.moments(contour)
    cx, cy = (int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])) if M['m00'] != 0 else (0, 0)

    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if area == 0 or perimeter == 0: 
        return "Unknown", (cx, cy)

    # 1. Tính Circularity (Độ tròn)
    circularity = (4 * np.pi * area) / (perimeter * perimeter)

    # 2. Tính Extent dựa trên Rotated Bounding Box
    rect = cv2.minAreaRect(contour)
    (_, _), (w, h), _ = rect
    if w == 0 or h == 0: 
        return "Unknown", (cx, cy)
    
    rect_area = w * h
    extent = area / rect_area  # Tỷ lệ lấp đầy hộp
    aspect_ratio = max(w, h) / min(w, h)

    # Xấp xỉ đa giác (Chỉ dùng phụ trợ để check Tam giác)
    approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
    vertices = len(approx)

    # ---------------------------------------------------------
    # LOGIC PHÂN LOẠI MỚI (CHỐNG LỖI BO GÓC)
    # ---------------------------------------------------------
    # Tròn hoàn hảo có Circularity ~ 1.0 (Ngưỡng an toàn là 0.85)
    if circularity >= 0.85:
        shape = "Circle"
        
    # Chữ nhật/Vuông (kể cả bo góc) sẽ lấp đầy > 85% diện tích hộp
    elif extent >= 0.85:
        tolerance_nguong_vuong = 1.15
        if aspect_ratio <= tolerance_nguong_vuong:
            shape = "Square"
        else:
            shape = "Rectangle"
            
    # Tam giác thường chiếm Extent thấp (khoảng 0.5) nên đếm đỉnh là chuẩn nhất
    elif vertices == 3:
        shape = "Triangle"
        
    else:
        shape = f"Polygon ({vertices})"
        
    return shape, (cx, cy)

# ==========================================
# 3. HÀM CALCULATE BASED ON SHAPES (Giữ nguyên thuật toán Ruler tốt của bạn)
# ==========================================
def calculate_based_on_shapes(contour, shape_name):
    pts = contour.reshape(-1, 2)
    
    if shape_name in ["Rectangle", "Square"]:
        x, y, w, h = cv2.boundingRect(pts)
        cx, cy = x + w / 2, y + h / 2
        
        if w > h:
            top_edge = pts[pts[:, 1] < cy]
            bot_edge = pts[pts[:, 1] >= cy]
            if len(top_edge) < 2 or len(bot_edge) < 2: return 0, 0, "Error", None
            
            p_top = np.polyfit(top_edge[:, 0], top_edge[:, 1], 1)
            p_bot = np.polyfit(bot_edge[:, 0], bot_edge[:, 1], 1)
            
            y_top_ideal = np.poly1d(p_top)(cx)
            y_bot_ideal = np.poly1d(p_bot)(cx)
            width = abs(y_bot_ideal - y_top_ideal)
            ler = 3 * np.std(top_edge[:, 1] - np.poly1d(p_top)(top_edge[:, 0]))
            
            pt1 = (int(cx), int(y_top_ideal))
            pt2 = (int(cx), int(y_bot_ideal))
            return width, ler, "Width / LER", (pt1, pt2)
            
        else:
            left_edge = pts[pts[:, 0] < cx]
            right_edge = pts[pts[:, 0] >= cx]
            if len(left_edge) < 2 or len(right_edge) < 2: return 0, 0, "Error", None
            
            p_left = np.polyfit(left_edge[:, 1], left_edge[:, 0], 1)
            p_right = np.polyfit(right_edge[:, 1], right_edge[:, 0], 1)
            
            x_left_ideal = np.poly1d(p_left)(cy)
            x_right_ideal = np.poly1d(p_right)(cy)
            width = abs(x_right_ideal - x_left_ideal)
            ler = 3 * np.std(left_edge[:, 0] - np.poly1d(p_left)(left_edge[:, 1]))
            
            pt1 = (int(x_left_ideal), int(cy))
            pt2 = (int(x_right_ideal), int(cy))
            return width, ler, "Width / LER", (pt1, pt2)

    elif shape_name == "Circle":
        if len(contour) >= 5:
            ellipse = cv2.fitEllipse(contour)
            (xc, yc), (minor_axis, major_axis), _ = ellipse
            diameter = (minor_axis + major_axis) / 2.0
            
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            circ = (4 * np.pi * area) / (perimeter**2)
            
            pt1 = (int(xc - diameter/2), int(yc))
            pt2 = (int(xc + diameter/2), int(yc))
            return diameter, circ, "Diameter/Circ", (pt1, pt2)
        return 0, 0, "Error", None

    else:
        rect = cv2.minAreaRect(contour)
        (cx, cy), (w, h), angle = rect
        max_span = max(w, h)
        
        box = cv2.boxPoints(rect)
        box = box.astype(np.intp)
        
        dist_01 = np.linalg.norm(box[0] - box[1])
        dist_12 = np.linalg.norm(box[1] - box[2])
        
        if dist_01 > dist_12:
            pt1 = (int((box[1][0] + box[2][0]) / 2), int((box[1][1] + box[2][1]) / 2))
            pt2 = (int((box[0][0] + box[3][0]) / 2), int((box[0][1] + box[3][1]) / 2))
        else:
            pt1 = (int((box[0][0] + box[1][0]) / 2), int((box[0][1] + box[1][1]) / 2))
            pt2 = (int((box[2][0] + box[3][0]) / 2), int((box[2][1] + box[3][1]) / 2))
            
        return max_span, 0, "Max Span", (pt1, pt2)

# ==========================================
# 4. HÀM MAIN: Visual Ruler
# ==========================================
def main():
    image_path = "D:\\Projects\\04_WafferDetection\\Sample\\SEMcrl.png"
    
    try:
        img_gray, objects, coordinates = detect_objects(image_path, min_area=100)
        img_color = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
        
        print(f"Đã phát hiện {len(objects)} đối tượng hợp lệ.")
        print("-" * 85)
        print(f"{'ID':<4} | {'Shape':<15} | {'Metric':<15} | {'Value (px)':<15}")
        print("-" * 85)
        
        for i, contour in enumerate(objects):
            obj_id = i + 1
            shape, center = classify_shapes(contour)
            val, secondary_val, metric, ruler_pts = calculate_based_on_shapes(contour, shape)
            
            print(f"#{obj_id:<3} | {shape:<15} | {metric:<15} | {val:<15.3f}")
            
            cv2.drawContours(img_color, [contour], -1, (0, 200, 0), 1)
            
            if ruler_pts is not None:
                pt1, pt2 = ruler_pts
                cv2.line(img_color, pt1, pt2, (255, 255, 0), 2)
                cv2.circle(img_color, pt1, 3, (0, 0, 255), -1)
                cv2.circle(img_color, pt2, 3, (0, 0, 255), -1)
                
            # Ghi ID của vật thể
            # cv2.putText(img_color, f"#{obj_id} {shape}", (center[0] - 15, center[1] - 15),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
                        
        print("-" * 85)
        plt.figure(figsize=(14, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.title("Optimized Feature Extraction & Metrology")
        plt.axis('off')
        plt.tight_layout()
        plt.show()
        
    except Exception as e:
        print(f"Lỗi hệ thống: {e}")

if __name__ == "__main__":
    main()