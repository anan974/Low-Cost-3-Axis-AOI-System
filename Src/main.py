import cv2
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# 1. HÀM DETECT: Thêm CLAHE cân bằng sáng & Lọc nhiễu
# ==========================================
def detect_objects(image_path, min_area=500, border_margin=1):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Không thể đọc ảnh từ: {image_path}")
        
    img_h, img_w = img.shape
    
    # TỐI ƯU 1: Cân bằng sáng cục bộ (CLAHE) giúp rõ nét viền trong vùng tối
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img_clahe = clahe.apply(img)
    
    # Khử nhiễu & Cắt ngưỡng
    blurred = cv2.GaussianBlur(img_clahe, (5, 5), 1.2)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Morphological: Dùng MỞ (Open) để xóa nhiễu hột, sau đó ĐÓNG (Close) để mượt biên
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary_opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    binary_closed = cv2.morphologyEx(binary_opened, cv2.MORPH_CLOSE, kernel, iterations=1)
    
    contours, _ = cv2.findContours(binary_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    valid_objects = []
    object_coordinates = []
    
    for cnt in contours:
        if cv2.contourArea(cnt) >= min_area:
            x, y, w, h = cv2.boundingRect(cnt)
            
            # Lọc mép ảnh
            if (x <= border_margin) or (y <= border_margin) or \
               (x + w >= img_w - border_margin) or (y + h >= img_h - border_margin):
                continue 
                
            valid_objects.append(cnt)
            object_coordinates.append((x, y, w, h))
            
    return img, valid_objects, object_coordinates

# ==========================================
# 2. HÀM CLASSIFY: Thêm Elip & Truyền Bounding Box xoay đi tiếp
# ==========================================
def classify_shapes(contour):
    M = cv2.moments(contour)
    cx, cy = (int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])) if M['m00'] != 0 else (0, 0)

    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if area == 0 or perimeter == 0: 
        return "Unknown", (cx, cy), None

    circularity = (4 * np.pi * area) / (perimeter * perimeter)
    
    # Lấy Hộp giới hạn xoay (Truyền luôn biến này ra ngoài để Calculate xài ké)
    rect = cv2.minAreaRect(contour)
    (_, _), (w, h), angle = rect
    if w == 0 or h == 0: 
        return "Unknown", (cx, cy), rect
        
    extent = area / (w * h)
    aspect_ratio = max(w, h) / min(w, h)
    vertices = len(cv2.approxPolyDP(contour, 0.04 * perimeter, True))

    # TỐI ƯU 2: Nhận diện chính xác Hình Elip (Lỗi kéo giãn Via/Contact)
    if circularity >= 0.85:
        shape = "Circle"
    elif 0.70 <= extent <= 0.83 and aspect_ratio > 1.2:
        # Độ lấp đầy của Elip nằm trong khoảng Pi/4 (~0.785)
        shape = "Ellipse"
    elif extent >= 0.85:
        if aspect_ratio <= 1.15: shape = "Square"
        else: shape = "Rectangle"
    elif vertices == 3:
        shape = "Triangle"
    else:
        shape = f"Polygon ({vertices})"
        
    return shape, (cx, cy), rect

# ==========================================
# 3. HÀM CALCULATE: Chống xoay lệch góc & Thước đo vạn năng
# ==========================================
def calculate_based_on_shapes(contour, shape_name, rect):
    if rect is None: return 0, 0, "Error", None
    
    (cx, cy), (w, h), angle = rect
    
    # Lấy 4 đỉnh của Rotated Rect (Box xoay)
    box = cv2.boxPoints(rect).astype(np.intp)
    dist_01 = np.linalg.norm(box[0] - box[1])
    dist_12 = np.linalg.norm(box[1] - box[2])
    
    # ---------------------------------------------------------
    # TỐI ƯU 3: ĐO LINE/PAD (Chữ nhật/Vuông) - CHỐNG LỖI XOAY GÓC
    # Đo CD: Là đường CHÉO NGANG chiều rộng ngắn nhất (Minor Axis)
    # ---------------------------------------------------------
    if shape_name in ["Rectangle", "Square"]:
        width_cd = min(w, h) # CD chính là cạnh ngắn của Bounding Box xoay
        
        # Để vẽ thước đo độ rộng: Nối trung điểm của 2 CẠNH DÀI
        if dist_01 > dist_12: 
            # Cạnh 0-1 là dài, 1-2 là ngắn (rộng). Ta nối trung điểm 0-1 và 2-3
            pt1 = (int((box[0][0] + box[1][0]) / 2), int((box[0][1] + box[1][1]) / 2))
            pt2 = (int((box[2][0] + box[3][0]) / 2), int((box[2][1] + box[3][1]) / 2))
        else:
            pt1 = (int((box[1][0] + box[2][0]) / 2), int((box[1][1] + box[2][1]) / 2))
            pt2 = (int((box[0][0] + box[3][0]) / 2), int((box[0][1] + box[3][1]) / 2))
            
        return width_cd, 0, "Width (CD)", (pt1, pt2)

    # ---------------------------------------------------------
    # ĐO ĐƯỜNG TRÒN / ELIP (Đo đường kính trung bình)
    # ---------------------------------------------------------
    elif shape_name in ["Circle", "Ellipse"]:
        if len(contour) >= 5:
            ellipse = cv2.fitEllipse(contour)
            (xc, yc), (minor_axis, major_axis), el_angle = ellipse
            
            if shape_name == "Circle":
                diameter = (minor_axis + major_axis) / 2.0
                metric_name = "Diameter"
            else:
                diameter = major_axis # Đối với Elip, người ta thường quan tâm trục dài nhất bị kéo giãn
                metric_name = "Major Axis"
            
            # Thước vẽ ngang tâm theo hệ quy chiếu OpenCV
            pt1 = (int(xc - diameter/2 * np.cos(np.radians(el_angle + 90))), 
                   int(yc - diameter/2 * np.sin(np.radians(el_angle + 90))))
            pt2 = (int(xc + diameter/2 * np.cos(np.radians(el_angle + 90))), 
                   int(yc + diameter/2 * np.sin(np.radians(el_angle + 90))))
                   
            return diameter, 0, metric_name, (pt1, pt2)
        return 0, 0, "Error", None

    # ---------------------------------------------------------
    # ĐO POLYGON Khác (Max Span - Nối trung điểm 2 cạnh ngắn)
    # ---------------------------------------------------------
    else:
        max_span = max(w, h)
        if dist_01 > dist_12:
            pt1 = (int((box[1][0] + box[2][0]) / 2), int((box[1][1] + box[2][1]) / 2))
            pt2 = (int((box[0][0] + box[3][0]) / 2), int((box[0][1] + box[3][1]) / 2))
        else:
            pt1 = (int((box[0][0] + box[1][0]) / 2), int((box[0][1] + box[1][1]) / 2))
            pt2 = (int((box[2][0] + box[3][0]) / 2), int((box[2][1] + box[3][1]) / 2))
            
        return max_span, 0, "Max Span", (pt1, pt2)


# ==========================================
# 4. HÀM: Visual Ruler Execute (Refactored)
# ==========================================
def run_visual_ruler(image_path, calib_um_per_pixel=1.0):
    """
    Run the full visual ruler pipeline.
    Args:
        image_path (str): Path to the input image.
        calib_um_per_pixel (float): Calibration value (um/pixel).
    Returns:
        dict: Results including detected objects and measurements.
    """
    result = {
        'objects': [],
        'image_with_annotations': None,
        'avr_cd_width_px': None,
        'avr_cd_width_um': None,
        'avr_space_width_px': None,
        'avr_space_width_um': None,
        'error': None
    }
    try:
        img_gray, objects, coordinates = detect_objects(image_path, min_area=100, border_margin=0)
        img_color = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
        measurements = []
        for i, contour in enumerate(objects):
            obj_id = i + 1
            shape, center, rect = classify_shapes(contour)
            val, _, metric, ruler_pts = calculate_based_on_shapes(contour, shape, rect)
            val_um = val * calib_um_per_pixel
            measurements.append({
                'id': obj_id,
                'shape': shape,
                'metric': metric,
                'value_px': val,
                'value_um': val_um,
                'center': center
            })
            # Draw contour and ruler
            cv2.drawContours(img_color, [contour], -1, (0, 200, 0), 1)
            if ruler_pts is not None:
                pt1, pt2 = ruler_pts
                cv2.line(img_color, pt1, pt2, (255, 255, 0), 2)
                cv2.circle(img_color, pt1, 3, (0, 0, 255), -1)
                cv2.circle(img_color, pt2, 3, (0, 0, 255), -1)
        # Calculate averages
        if measurements:
            avr_cd_width_px = np.mean([obj['value_px'] for obj in measurements])
            avr_cd_width_um = avr_cd_width_px * calib_um_per_pixel
            avr_space_width_px = np.mean([obj['value_px'] for obj in measurements])
            avr_space_width_um = avr_space_width_px * calib_um_per_pixel
        else:
            avr_cd_width_px = None
            avr_cd_width_um = None
            avr_space_width_px = None
            avr_space_width_um = None
        result['objects'] = measurements
        result['image_with_annotations'] = img_color
        result['avr_cd_width_px'] = avr_cd_width_px
        result['avr_cd_width_um'] = avr_cd_width_um
        result['avr_space_width_px'] = avr_space_width_px
        result['avr_space_width_um'] = avr_space_width_um
    except Exception as e:
        result['error'] = str(e)
    return result

def main():
    image_path = "D:\\Projects\\04_WafferDetection\\Sample\\b2.png"
    calib_um_per_pixel = 1.0
    result = run_visual_ruler(image_path, calib_um_per_pixel)
    if result['error']:
        print(f"Lỗi hệ thống: {result['error']}")
        return
    print(f"Đã phát hiện {len(result['objects'])} đối tượng hợp lệ.")
    print("-" * 85)
    print(f"{'ID':<4} | {'Shape':<15} | {'Metric':<15} | {'Value (px)':<15} | {'Value (um)':<15}")
    print("-" * 85)
    for obj in result['objects']:
        print(f"#{obj['id']:<3} | {obj['shape']:<15} | {obj['metric']:<15} | {obj['value_px']:<15.3f} | {obj['value_um']:<15.3f}")
    print("-" * 85)
    # Print average CD width
    avr_cd = result.get('avr_cd_width_um')
    if avr_cd is not None:
        print(f"Average CD Width: {avr_cd:.3f} um")
    else:
        print("Average CD Width: -")
    # Show annotated image
    img_color = result['image_with_annotations']
    if img_color is not None:
        plt.figure(figsize=(14, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.title("Pro-Grade Feature Extraction & Rotated Metrology")
        plt.axis('off')
        plt.tight_layout()
        plt.show()

if __name__ == "__main__":
    main()