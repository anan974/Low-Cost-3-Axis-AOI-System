# model.py
import cv2
import numpy as np
import os
import warnings
import onnxruntime as ort
from ultralytics import YOLO

# Cố gắng import onnxruntime, nếu không có thì fallback ultralytics (kém hiệu năng)
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False
    from ultralytics import YOLO
    warnings.warn("onnxruntime not installed. Using ultralytics (slow). Install with: pip install onnxruntime")

class ErrorDetector:
    def __init__(self, model_path="./best640.onnx"):
        """
        Tối ưu: Nếu tồn tại best.onnx thì dùng ONNX Runtime (nhanh hơn 3-5x trên CPU).
        Nếu không, fallback về ultralytics YOLO (chậm).
        """
        self.use_onnx = False
        onnx_path = model_path.replace('.pt', '.onnx')
        if ONNX_AVAILABLE and os.path.exists(onnx_path):
            try:
                sess_options = ort.SessionOptions()
                sess_options.enable_cpu_mem_arena = False
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.ort_session = ort.InferenceSession(onnx_path, sess_options)
                self.input_name = self.ort_session.get_inputs()[0].name
                self.input_shape = self.ort_session.get_inputs()[0].shape
                self.use_onnx = True
                print(f"[ErrorDetector] Loaded ONNX model from {onnx_path}")
            except Exception as e:
                print(f"[ErrorDetector] Failed to load ONNX: {e}. Falling back to ultralytics.")
                self.model = YOLO(model_path)
        else:
            if not ONNX_AVAILABLE:
                print("[ErrorDetector] onnxruntime missing, using ultralytics (slow).")
            else:
                print("[ErrorDetector] ONNX file not found, using ultralytics. Export to ONNX for better performance.")
            self.model = YOLO(model_path)

    def detect(self, gray_image):
        """
        Nhận ảnh xám hoặc BGR, trả về danh sách các lỗi: (x, y, w, h, conf, class_id)
        Nếu đầu vào None hoặc không hợp lệ, trả về danh sách rỗng.
        """
        if gray_image is None:
            return []
        if not isinstance(gray_image, np.ndarray):
            return []
        if gray_image.size == 0:
            return []

        # Chuyển sang BGR nếu cần (YOLO yêu cầu 3 kênh)
        if len(gray_image.shape) == 2:
            img = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)
        else:
            img = gray_image

        if self.use_onnx:
            return self._detect_onnx(img)
        else:
            return self._detect_ultralytics(img)

    def _detect_ultralytics(self, img):
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

    def _detect_onnx(self, img):
        """
        Xử lý inference với model ONNX của YOLOv26n.
        Định dạng output là (N, 300, 6) với 6 giá trị: x1, y1, x2, y2, confidence, class_id.
        """
        orig_h, orig_w = img.shape[:2]

        # --- Tiền xử lý ảnh ---
        target_size = 640  # Kích thước mặc định khi export ONNX
        input_tensor = self._preprocess_image(img, target_size, target_size)

        # --- Inference ONNX ---
        outputs = self.ort_session.run(None, {self.input_name: input_tensor})
        
        # --- Hậu xử lý kết quả ---
        # output của YOLOv26n có shape (1, 300, 6)
        # Mỗi hàng: [x1, y1, x2, y2, confidence, class_id]
        predictions = outputs[0][0]  # Lấy batch đầu tiên, kết quả (300, 6)
        
        detections = []
        for pred in predictions:
            x1, y1, x2, y2, conf, cls_id = pred
            
            # Lọc bỏ các detection có confidence thấp
            if conf < 0.5:
                continue
                
            # Chuyển đổi tọa độ từ không gian 640x640 về kích thước ảnh gốc
            scale_x = orig_w / target_size
            scale_y = orig_h / target_size
            
            x1_orig = int(x1 * scale_x)
            y1_orig = int(y1 * scale_y)
            x2_orig = int(x2 * scale_x)
            y2_orig = int(y2 * scale_y)
            
            w = x2_orig - x1_orig
            h = y2_orig - y1_orig
            
            # Đảm bảo bounding box nằm trong ảnh
            if w > 0 and h > 0:
                detections.append((x1_orig, y1_orig, w, h, float(conf), int(cls_id)))
        
        return detections

    def _preprocess_image(self, img, target_w, target_h):
        """
        Tiền xử lý ảnh đầu vào cho model ONNX.
        Resize về đúng kích thước, chuyển đổi màu sắc và normalize.
        """
        # Resize ảnh về kích thước model yêu cầu
        resized = cv2.resize(img, (target_w, target_h))
        
        # Chuyển từ BGR sang RGB (nếu cần)
        # Lưu ý: Model của Ultralytics thường được train trên ảnh RGB
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        # Chuyển đổi định dạng array: (H, W, C) -> (C, H, W) và normalize về [0, 1]
        input_tensor = rgb.astype(np.float32) / 255.0
        input_tensor = np.transpose(input_tensor, (2, 0, 1))
        
        # Thêm batch dimension
        input_tensor = np.expand_dims(input_tensor, axis=0)
        
        return input_tensor