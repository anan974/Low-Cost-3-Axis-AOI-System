# -*- coding: utf-8 -*-
import sys
import os
import time
import cv2
import numpy as np
import RPi.GPIO as GPIO
from ctypes import *

# --- CẤU HÌNH CƠ BẢN ---
TRIGGER_PIN = 17       
BLINK_SPEED = 0.1      
BLINK_TIMES = 3        
SAVE_DIR = "Sample"

# 1. Tạo thư mục Sample nếu chưa có
os.makedirs(SAVE_DIR, exist_ok=True)

# --- SDK IMPORT ---
sys.path.append("./MvImport")
try:
    from MvCameraControl_class import *
except ImportError:
    print("LỖI: Không tìm thấy thư mục MvImport của Hikvision SDK!")
    sys.exit(1)

# --- GPIO SETUP ---
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIGGER_PIN, GPIO.OUT)
    GPIO.output(TRIGGER_PIN, GPIO.LOW)

def blink_signal():
    for _ in range(BLINK_TIMES):
        GPIO.output(TRIGGER_PIN, GPIO.HIGH)
        time.sleep(BLINK_SPEED)
        GPIO.output(TRIGGER_PIN, GPIO.LOW)
        time.sleep(BLINK_SPEED)

# --- KIỂM TRA ĐIỀU KIỆN TRIGGER (STATE LOGIC) ---
def check_trigger_condition(image):
    """
    Hàm đánh giá ảnh. Trả về: (boolean, string_state)
    """
    # Check độ sáng
    mean_brightness = np.mean(image)
    if mean_brightness < 30: 
        return False, "ERR_TOO_DARK"
    if mean_brightness > 225: 
        return False, "ERR_TOO_BRIGHT"

    # Nhị phân hóa và tìm viền vật thể
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False, "ERR_NO_OBJECT"
    
    # Lấy vật lớn nhất để check góc
    largest_contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest_contour) < 5000: # Lọc nhiễu
        return False, "ERR_OBJECT_TOO_SMALL"
        
    # Tính góc theo trục XY
    rect = cv2.minAreaRect(largest_contour)
    angle = rect[-1] 
    mod_angle = angle % 90
    tolerance = 4.0 # Biên độ sai số góc cho phép (4 độ)
    
    if mod_angle <= tolerance or mod_angle >= (90 - tolerance):
        return True, "READY_XY_ALIGNED"
    else:
        return False, f"ERR_XY_MISALIGNED (Lệch: {mod_angle:.1f} độ)"

# --- HÀM MAIN ---
def main():
    setup_gpio()
    print("=== HỆ THỐNG AUTO TRIGGER CAMERA ===")

    # 2. Check cam có tồn tại / kết nối không
    deviceList = MV_CC_DEVICE_INFO_LIST()
    MvCamera.MV_CC_EnumDevices(MV_USB_DEVICE, deviceList)
    
    if deviceList.nDeviceNum == 0:
        # Nếu không có cam -> return lỗi và in ra terminal
        print("LỖI NGHIÊM TRỌNG: Không tìm thấy hoặc chưa kết nối Camera Hikvision!")
        return -1

    stDeviceList = cast(deviceList.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
    cam = MvCamera()
    
    if cam.MV_CC_CreateHandle(stDeviceList) != 0: 
        print("LỖI: Không thể khởi tạo Handle Camera!")
        return -1
    if cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) != 0: 
        print("LỖI: Không thể mở Camera!")
        return -1
    
    cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)

    stParam = MVCC_INTVALUE()
    memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
    cam.MV_CC_GetIntValue("PayloadSize", stParam)
    nPayloadSize = stParam.nCurValue
    data_buf = (c_ubyte * nPayloadSize)()
    stFrameInfo = MV_FRAME_OUT_INFO_EX()

    if cam.MV_CC_StartGrabbing() != 0: 
        print("LỖI: Không thể bắt đầu lấy hình!")
        return -1

    WINDOW_NAME = "AUTO TRIGGER MONITOR"
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 640, 480) 

    snap_count = 0
    ready_to_capture = True 
    last_state = ""

    print("=> Hệ thống khởi động thành công. Bắt đầu giám sát...")

    try:
        while True:
            # TimeOut 1000ms. Nếu rút cáp cam đột ngột, ret sẽ khác 0
            ret = cam.MV_CC_GetOneFrameTimeout(byref(data_buf), nPayloadSize, stFrameInfo, 1000)
            
            if ret == 0:
                # Lấy dữ liệu ảnh
                pData = (c_ubyte * stFrameInfo.nFrameLen).from_address(addressof(data_buf))
                live_img = np.frombuffer(pData, dtype=np.uint8).reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                
                # 3. Check điều kiện State
                is_trigger_ok, current_state = check_trigger_condition(live_img)

                # In ra Terminal State (Chỉ in khi state thay đổi để tránh trôi màn hình)
                if current_state != last_state:
                    print(f"[{time.strftime('%H:%M:%S')}] STATE: {current_state}")
                    last_state = current_state

                # Thực thi Auto Trigger
                if is_trigger_ok:
                    if ready_to_capture:
                        snap_count += 1
                        filename = os.path.join(SAVE_DIR, f"sample_{snap_count}.jpg")
                        
                        # Lưu ảnh
                        cv2.imwrite(filename, live_img)
                        print(f"[{time.strftime('%H:%M:%S')}] ---> ĐÃ CHỤP & LƯU: {filename}")
                        
                        # Xuất tín hiệu GPIO
                        blink_signal()
                        
                        # Khóa trigger, đợi vật này đi qua mới chụp vật khác
                        ready_to_capture = False 
                else:
                    # Nếu điều kiện sai (vật đã đi khỏi hoặc lệch góc), mở khóa cho vật tiếp theo
                    ready_to_capture = True

                # Hiển thị GUI cơ bản để giám sát
                live_bgr = cv2.cvtColor(live_img, cv2.COLOR_GRAY2BGR)
                color = (0, 255, 0) if is_trigger_ok else (0, 0, 255)
                cv2.putText(live_bgr, f"STATE: {current_state}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                cv2.imshow(WINDOW_NAME, live_bgr)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("Nhận lệnh thoát (Q).")
                    break
            else:
                # Bắt lỗi mất kết nối giữa chừng (ví dụ: lỏng cáp, sập nguồn cam)
                print(f"[{time.strftime('%H:%M:%S')}] LỖI: Camera mất kết nối hoặc không phản hồi (Error Code: {ret}).")
                break # Return lỗi ra ngoài vòng lặp

    except KeyboardInterrupt:
        print("Người dùng ngắt chương trình (Ctrl+C).")
    finally:
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        cv2.destroyAllWindows()
        GPIO.cleanup()
        print("=> Đã dọn dẹp hệ thống. Kết thúc.")
        return 0

if __name__ == "__main__":
    main()