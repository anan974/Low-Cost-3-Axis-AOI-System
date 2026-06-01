import cv2
import math
import tkinter as tk
from tkinter import simpledialog

points = []
img_original = None
img_display = None

def mouse_click(event, x, y, flags, param):
    global points, img_original, img_display
    
    # 1. Sự kiện di chuyển chuột (Tạo hiệu ứng kéo thả)
    if event == cv2.EVENT_MOUSEMOVE:
        if len(points) == 1:
            # Phải copy lại ảnh gốc để xóa đường vẽ cũ đi (tránh bị lưu bóng mờ)
            img_display = img_original.copy()
            
            # Tọa độ điểm đầu tiên
            start_x, start_y = points[0]
            
            # Vẽ điểm đầu tiên
            cv2.circle(img_display, (start_x, start_y), 5, (0, 0, 255), -1)
            
            # TÍNH NĂNG MỚI: Vẽ đường gióng ngang màu vàng để canh tọa độ Y
            h, w = img_display.shape[:2]
            cv2.line(img_display, (0, start_y), (w, start_y), (0, 255, 255), 1, cv2.LINE_AA)
            
            # Vẽ đường thẳng nối từ điểm 1 đến vị trí chuột hiện tại
            cv2.line(img_display, (start_x, start_y), (x, y), (0, 255, 0), 2, cv2.LINE_AA)
            
            # Hiển thị độ lệch Y để nhắc nhở người dùng
            dy = abs(y - start_y)
            color = (0, 255, 0) if dy <= 2 else (0, 0, 255) # Đỏ nếu lệch > 2 pixel
            cv2.putText(img_display, f"Lech Y: {dy} px", (x + 10, y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            
            cv2.imshow("Calibration Setup", img_display)

    # 2. Sự kiện Click chuột trái
    elif event == cv2.EVENT_LBUTTONDOWN:
        if len(points) < 2:
            points.append((x, y))
            
            if len(points) == 1:
                cv2.circle(img_display, (x, y), 5, (0, 0, 255), -1)
                cv2.imshow("Calibration Setup", img_display)
                
            elif len(points) == 2:
                # Khi click xong điểm 2, chốt kết quả vẽ lại ảnh sạch sẽ
                img_display = img_original.copy()
                cv2.circle(img_display, points[0], 5, (0, 0, 255), -1)
                cv2.circle(img_display, points[1], 5, (0, 0, 255), -1)
                cv2.line(img_display, points[0], points[1], (0, 255, 0), 2)
                cv2.imshow("Calibration Setup", img_display)

def get_real_world_distance():
    root = tk.Tk()
    root.withdraw()
    real_dist_mm = simpledialog.askfloat(
        "Nhập thông số", 
        "Nhập khoảng cách thực tế giữa 2 điểm bạn vừa vẽ\n(Đơn vị: mm):",
        minvalue=0.0001
    )
    root.destroy()
    return real_dist_mm

def calibrate_image(image_path):
    global points, img_original, img_display
    points = []
    
    img = cv2.imread(image_path)
    if img is None:
        print("❌ Lỗi: Không thể đọc ảnh!")
        return None
        
    img_original = img.copy()
    img_display = img.copy()
    
    cv2.namedWindow("Calibration Setup")
    cv2.setMouseCallback("Calibration Setup", mouse_click)
    
    print("👉 Hãy click vào điểm ĐẦU. Sau đó di chuột đến điểm CUỐI và click lần 2.")
    print("💡 Mẹo: Cố gắng giữ 'Lệch Y' càng gần 0 càng tốt để kết quả chuẩn xác.")
    
    while True:
        cv2.imshow("Calibration Setup", img_display)
        key = cv2.waitKey(10) & 0xFF
        if key == 27: # Ấn ESC để thoát
            cv2.destroyAllWindows()
            return None
        if len(points) == 2:
            cv2.waitKey(500)
            break
            
    cv2.destroyAllWindows()
    
    x1, y1 = points[0]
    x2, y2 = points[1]
    
    # Cảnh báo nếu click quá lệch
    if abs(y2 - y1) > 5:
        print(f"⚠️ CẢNH BÁO: Bạn click 2 điểm lệch nhau {abs(y2 - y1)} pixel theo trục Y. "
              f"Điều này có thể gây sai số đường chéo. Khuyên bạn nên đo lại!")

    pixel_distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    print(f"📏 Khoảng cách đo được trên ảnh: {pixel_distance:.2f} pixels")
    
    real_dist_mm = get_real_world_distance()
    if real_dist_mm is None: return None
        
    real_dist_um = real_dist_mm * 1000
    calibration_factor = real_dist_um / pixel_distance
    
    print("-" * 40)
    print(f"✅ Khoảng cách thực tế: {real_dist_mm} mm = {real_dist_um} um")
    print(f"✅ Hệ số: {calibration_factor:.4f} um/pixel")
    print("-" * 40)
    
    return calibration_factor

if __name__ == "__main__":
    TEST_IMAGE = r'c:\Users\Dao Dang Thanh An\MVS\Data\Image_20260328155159593.bmp'
    calibrate_image(TEST_IMAGE)
