import cv2
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# BƯỚC 1: TẠO MẶT NẠ ROI BẰNG OTSU THRESHOLDING
# ==========================================
def create_roi_mask(blurred_img, dilation_size=3):
    """
    Sử dụng Otsu để phân mảnh ảnh, sau đó tìm viền thô và mở rộng (dilate) 
    để tạo ra vùng quan tâm (ROI).
    """
    # Áp dụng Otsu's thresholding
    _, binary = cv2.threshold(blurred_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Tìm viền thô trên ảnh nhị phân bằng thuật toán hình thái học (Morphological Gradient)
    kernel = np.ones((3, 3), np.uint8)
    morph_gradient = cv2.morphologyEx(binary, cv2.MORPH_GRADIENT, kernel)
    
    # Làm dày viền (Dilate) để đảm bảo bao trùm hết khu vực gradient xám thực tế
    dilation_kernel = np.ones((dilation_size, dilation_size), np.uint8)
    roi_mask = cv2.dilate(morph_gradient, dilation_kernel, iterations=1)
    
    return roi_mask, binary

# ==========================================
# BƯỚC 2: TRÍCH XUẤT VIỀN SUB-PIXEL TRONG VÙNG ROI
# ==========================================
def extract_subpixel_edges_with_roi(image_path, sigma=1.5, low_thresh=30, high_thresh=100):
    """Trích xuất điểm sub-pixel nhưng chỉ giới hạn trong vùng ROI của Otsu."""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Không thể đọc ảnh từ '{image_path}'.")

    # Làm mịn ảnh
    blurred = cv2.GaussianBlur(img, (0, 0), sigma)

    # Tạo ROI Mask từ thuật toán Otsu
    roi_mask, binary_otsu = create_roi_mask(blurred, dilation_size=5)

    # Tính Gradient Sobel (trên ảnh xám)
    sobelx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(sobelx, sobely)
    angle = cv2.phase(sobelx, sobely, angleInDegrees=False)

    # Canny nguyên bản
    edges = cv2.Canny(blurred, low_thresh, high_thresh)
    
    # LỌC BẰNG MẶT NẠ: Chỉ giữ lại pixel viền Canny nếu nó nằm trong vùng ROI
    masked_edges = cv2.bitwise_and(edges, edges, mask=roi_mask)

    subpixel_pts = []
    rows, cols = masked_edges.shape

    # Nội suy Devernay
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            if masked_edges[y, x] == 255:
                theta = angle[y, x]
                
                # Viền dọc
                if (np.abs(np.cos(theta)) > np.abs(np.sin(theta))):
                    m_minus = magnitude[y, x-1]
                    m_zero  = magnitude[y, x]
                    m_plus  = magnitude[y, x+1]
                    
                    denom = 2.0 * (m_minus - 2.0 * m_zero + m_plus)
                    offset = (m_minus - m_plus) / denom if denom != 0 else 0
                    subpixel_pts.append((x + offset, y))
                
                # Viền ngang
                else:
                    m_minus = magnitude[y-1, x]
                    m_zero  = magnitude[y, x]
                    m_plus  = magnitude[y+1, x]
                    
                    denom = 2.0 * (m_minus - 2.0 * m_zero + m_plus)
                    offset = (m_minus - m_plus) / denom if denom != 0 else 0
                    subpixel_pts.append((x, y + offset))

    return img, np.array(subpixel_pts), roi_mask

# ==========================================
# BƯỚC 3 & 4: TÁCH VIỀN VÀ TÍNH LER
# ==========================================
def isolate_left_edge(subpixel_pts):
    if len(subpixel_pts) == 0: return np.array([])
    median_x = np.median(subpixel_pts[:, 0])
    return subpixel_pts[subpixel_pts[:, 0] < median_x]

def calculate_ler_3sigma(edge_pts):
    if len(edge_pts) < 2: return 0, None, None

    sorted_pts = edge_pts[edge_pts[:, 1].argsort()]
    y_vals, x_vals = sorted_pts[:, 1], sorted_pts[:, 0]

    unique_y, indices = np.unique(y_vals, return_inverse=True)
    unique_x = np.bincount(indices, weights=x_vals) / np.bincount(indices)

    coefficients = np.polyfit(unique_y, unique_x, 1)
    poly_func = np.poly1d(coefficients)
    x_ideal = poly_func(unique_y)

    deviations = unique_x - x_ideal
    sigma_ler = np.std(deviations)
    return 3 * sigma_ler, (unique_x, unique_y), (x_ideal, unique_y)

# ==========================================
# BƯỚC 5: TRỰC QUAN HÓA (CẬP NHẬT)
# ==========================================
def visualize_hybrid_pipeline(img, roi_mask, left_pts, ideal_prof, ler_val):
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    
    # Plot 1: Hiển thị ROI Mask sinh ra từ Otsu
    axes[0].imshow(roi_mask, cmap='gray')
    axes[0].set_title("Otsu ROI Mask (Giới hạn vùng tìm kiếm)")
    axes[0].axis('off')

    # Plot 2: Hiển thị ảnh gốc + Điểm Sub-pixel + Ideal Edge
    axes[1].imshow(img, cmap='gray', alpha=0.8)
    if len(left_pts) > 0:
        axes[1].scatter(left_pts[:, 0], left_pts[:, 1], color='red', s=5.0, label='Sub-pixel Edge', zorder=2)
    if ideal_prof is not None:
        axes[1].plot(ideal_prof[0], ideal_prof[1], color='blue', linestyle='--', linewidth=2, label='Ideal Edge', zorder=3)

    axes[1].set_title(f"Wafer LER Measurement\nCalculated LER ($3\\sigma$): {ler_val:.3f} pixels")
    axes[1].legend()
    axes[1].axis('on')
    
    plt.tight_layout()
    plt.show()

# ==========================================
# HÀM MAIN
# ==========================================
if __name__ == "__main__":
    # Thay đổi đường dẫn tới ảnh SEM của bạn
    image_path = "D:\\Projects\\04_WafferDetection\\Sample\\d2.png" 
    
    try:
        # 1. Trích xuất với cấu trúc lai (Hybrid)
        img, all_pts, roi_mask = extract_subpixel_edges_with_roi(image_path, sigma=1.2)
        
        # 2. Cô lập viền bên trái
        # left_edge_pts = isolate_left_edge(all_pts)
        points_to_draw = all_pts
        
        # # 3. Tính LER
        # ler_3sigma, real_profile, ideal_profile = calculate_ler_3sigma(left_edge_pts)
        
        # 4. In kết quả
        # print(f"Đã tìm thấy {len(left_edge_pts)} điểm viền hợp lệ trong vùng ROI.")
        # print(f"Độ nhám LER (3-sigma): {ler_3sigma:.4f} pixels")
        print(f"Đã tìm thấy tổng cộng {len(points_to_draw)} điểm viền trên TOÀN BỘ ảnh.")
        
        # 5. Vẽ đồ thị đôi (Mask và Kết quả)
        # visualize_hybrid_pipeline(img, roi_mask, left_edge_pts, ideal_profile, ler_3sigma)
        visualize_hybrid_pipeline(img, roi_mask, points_to_draw, ideal_prof=None, ler_val=0.0)
        
    except Exception as e:
        print(f"Lỗi: {e}")