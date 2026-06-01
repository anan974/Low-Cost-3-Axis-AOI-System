import sys
import numpy as np
import cv2
from ctypes import *  # Cần thiết cho các hàm memmove, cast, POINTER...
from MvImport.MvCameraControl_class import *

def main():
    # 1. Khởi tạo SDK và tìm kiếm thiết bị
    deviceList = MV_CC_DEVICE_INFO_LIST()
    tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
    
    ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
    if ret != 0:
        print(f"Tìm kiếm thiết bị thất bại! ret[0x{ret:x}]")
        sys.exit()

    if deviceList.nDeviceNum == 0:
        print("Không tìm thấy camera nào!")
        sys.exit()

    print(f"Tìm thấy {deviceList.nDeviceNum} camera.")

    # 2. Chọn camera đầu tiên và khởi tạo handle
    cam = MvCamera()
    # Đã sửa lỗi lặp từ khóa stDevice ở đây
    stDevice = cast(deviceList.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
    ret = cam.MV_CC_CreateHandle(stDevice)
    if ret != 0:
        print(f"Tạo handle thất bại! ret[0x{ret:x}]")
        sys.exit()

    # 3. Mở Camera
    ret = cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
    if ret != 0:
        print(f"Không thể mở camera! ret[0x{ret:x}]")
        sys.exit()

    # 4. Cấu hình (Tùy chọn): Ví dụ chỉnh Exposure Time
    # cam.MV_CC_SetExposureTime(20000) # 20ms

    # 5. Bắt đầu truyền hình ảnh (Streaming)
    ret = cam.MV_CC_StartGrabbing()
    if ret != 0:
        print(f"Bắt đầu grabbing thất bại! ret[0x{ret:x}]")
        sys.exit()

    # 6. Lấy dữ liệu ảnh LIÊN TỤC
    stOutFrame = MV_FRAME_OUT()
    memset(byref(stOutFrame), 0, sizeof(MV_FRAME_OUT))
    
    print("Bắt đầu lấy ảnh liên tục... Nhấn phím 'q' trên cửa sổ ảnh để thoát.")

    try:
        while True:
            ret = cam.MV_CC_GetImageBuffer(stOutFrame, 1000) # Chờ tối đa 1s

            if ret == 0:
                # Chuyển đổi dữ liệu sang Numpy để dùng với OpenCV
                pData = (c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                memmove(pData, stOutFrame.pBufAddr, stOutFrame.stFrameInfo.nFrameLen)
                data = np.frombuffer(pData, dtype=np.uint8)
                
                # Biến đổi shape tùy theo định dạng (Giả sử là Mono8)
                img = data.reshape((stOutFrame.stFrameInfo.nHeight, stOutFrame.stFrameInfo.nWidth))
                
                # Resize ảnh lại để cửa sổ không bị quá to (chiếm hết màn hình)
                img_show = cv2.resize(img, (800, 600))
                
                # Hiển thị thử bằng OpenCV
                cv2.imshow("Hikrobot Camera Stream", img_show)

                # Giải phóng buffer ảnh (BẮT BUỘC để không bị đầy bộ nhớ)
                cam.MV_CC_FreeImageBuffer(stOutFrame)

                # Đợi 1ms để OpenCV vẽ ảnh, và kiểm tra xem có nhấn 'q' không
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("Đã nhấn 'q', đang dừng camera...")
                    break
            else:
                print(f"Đợi ảnh... ret[0x{ret:x}]")

    except Exception as e:
        print(f"Đã xảy ra lỗi: {e}")

    finally:
        # 7. Đóng và giải phóng tài nguyên (Luôn được chạy dù có lỗi hay bấm thoát)
        print("Đang dọn dẹp tài nguyên...")
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        cv2.destroyAllWindows()
        print("Chương trình kết thúc an toàn.")

if __name__ == "__main__":
    main()