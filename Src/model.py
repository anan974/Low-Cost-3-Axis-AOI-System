import cv2
import numpy as np
from ultralytics import YOLO

class ErrorDetector:
    def __init__(self, model_path="./best.pt"):
        self.model = YOLO(model_path)
    
    def detect(self, gray_image):
        """
        Nhận ảnh xám hoặc BGR, trả về danh sách các lỗi.
        Mỗi lỗi có dạng: (x, y, w, h, confidence, class_id)
        Nếu đầu vào None hoặc không hợp lệ, trả về danh sách rỗng.
        """
        # Kiểm tra đầu vào
        if gray_image is None:
            print("[ErrorDetector] Input image is None")
            return []
        if not isinstance(gray_image, np.ndarray):
            print("[ErrorDetector] Input is not a numpy array")
            return []
        if gray_image.size == 0:
            print("[ErrorDetector] Input image is empty")
            return []
        
        # Nếu đầu vào là ảnh xám, chuyển sang BGR vì YOLO thường dùng 3 kênh
        if len(gray_image.shape) == 2:
            img = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)
        else:
            img = gray_image
        
        results = self.model(img)
        detections = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                w = x2 - x1
                h = y2 - y1
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                detections.append((int(x1), int(y1), int(w), int(h), conf, cls))
        return detections