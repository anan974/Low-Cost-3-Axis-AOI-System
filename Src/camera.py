# -*- coding: utf-8 -*-
import sys
import os
import time
import threading
import cv2
import numpy as np
from ctypes import *

# --- SDK IMPORT ---
sys.path.append("./Src/MvImport")
try:
    from MvCameraControl_class import *
except ImportError:
    print("ERROR: Hikvision SDK folder 'MvImport' not found!")
    sys.exit(1)


class CameraManager:
    def __init__(self):
        self.cam = None
        self.device_list = []
        self._live_thread = None
        self._stop_live = False
        self.latest_frame = None
        self._frame_lock = threading.Lock()
        self.is_live = False
        self._payload_size = 0
        self._width = 0
        self._height = 0
        self._pixel_format = 0

    def refresh_devices(self):
        """Scan all connected Hikvision cameras (USB + GigE)"""
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        if ret != 0:
            return 0
        self.device_list = [deviceList.pDeviceInfo[i] for i in range(deviceList.nDeviceNum)]
        return len(self.device_list)

    def connect(self, index=0):
        #--------------CHỈNH SỬA---------------
        """Connect to the camera at the given index in the device list"""
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        if deviceList.nDeviceNum == 0 or index >= deviceList.nDeviceNum:
            return False
        # Ép kiểu đúng và lấy nội dung (hoặc giữ pointer)
        pDeviceInfo = ctypes.cast(deviceList.pDeviceInfo[index], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        self.cam = MvCamera()
        ret = self.cam.MV_CC_CreateHandle(pDeviceInfo)  # hoặc byref(pDeviceInfo)
        if ret != 0:
            return False

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            self.cam.MV_CC_DestroyHandle()
            self.cam = None
            return False

        # Get PayloadSize (frame buffer size) and resolution
        stParam = MVCC_INTVALUE()
        memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
        ret = self.cam.MV_CC_GetIntValue("PayloadSize", stParam)
        if ret != 0:
            self.disconnect()
            return False
        self._payload_size = stParam.nCurValue

        stWidth = MVCC_INTVALUE()
        stHeight = MVCC_INTVALUE()
        if (self.cam.MV_CC_GetIntValue("Width", stWidth) == 0 and
            self.cam.MV_CC_GetIntValue("Height", stHeight) == 0):
            self._width = stWidth.nCurValue
            self._height = stHeight.nCurValue
        else:
            self._width = 1920
            self._height = 1080

        # Disable trigger mode (continuous acquisition)
        self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)

        return True

    def disconnect(self):
        """Disconnect and release resources"""
        self.stop_live()
        if self.cam:
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.cam = None

    def start_live(self, frame_callback=None):
        """Start live stream in a separate thread.
           frame_callback: function that receives a numpy BGR frame each time a new frame arrives."""
        if self.is_live or not self.cam:
            return False
        if self.cam.MV_CC_StartGrabbing() != 0:
            return False
        self.is_live = True
        self._stop_live = False
        self._live_thread = threading.Thread(target=self._live_worker, args=(frame_callback,), daemon=True)
        self._live_thread.start()
        return True

    def _live_worker(self, callback):
        """Worker thread that continuously grabs frames using MV_CC_GetOneFrameTimeout"""
        data_buf = (c_ubyte * self._payload_size)()
        stFrameInfo = MV_FRAME_OUT_INFO_EX()

        while not self._stop_live and self.is_live:
            ret = self.cam.MV_CC_GetOneFrameTimeout(byref(data_buf), self._payload_size, stFrameInfo, 500)
            if ret == 0:
                img_data = np.frombuffer(data_buf, dtype=np.uint8, count=stFrameInfo.nFrameLen)

                # Handle pixel format (Mono8, BGR8, etc.)
                if stFrameInfo.enPixelType == 17301505:   # PixelType_Gvsp_Mono8
                    frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                elif stFrameInfo.enPixelType == 17301514: # PixelType_Gvsp_BGR8_Packed
                    frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth, 3))
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                else:
                    # Fallback: assume grayscale if size matches
                    if img_data.size == stFrameInfo.nWidth * stFrameInfo.nHeight:
                        frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    else:
                        continue

                with self._frame_lock:
                    self.latest_frame = frame.copy()

                if callback:
                    callback(frame)
            else:
                time.sleep(0.01)

    def stop_live(self):
        """Stop the live stream"""
        self._stop_live = True
        if self._live_thread and self._live_thread.is_alive():
            self._live_thread.join(timeout=1)
        if self.cam:
            self.cam.MV_CC_StopGrabbing()
        self.is_live = False

    def get_last_frame(self):
        """Return the latest BGR frame (copy), or None if not available"""
        with self._frame_lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def capture_single(self, timeout_ms=1000):
        """Capture a single static frame (does not require live stream to be running).
           Returns (success, frame_bgr)"""
        if not self.cam:
            return False, None

        data_buf = (c_ubyte * self._payload_size)()
        stFrameInfo = MV_FRAME_OUT_INFO_EX()

        ret = self.cam.MV_CC_GetOneFrameTimeout(byref(data_buf), self._payload_size, stFrameInfo, timeout_ms)
        if ret != 0:
            return False, None

        img_data = np.frombuffer(data_buf, dtype=np.uint8, count=stFrameInfo.nFrameLen)

        if stFrameInfo.enPixelType == 17301505:   # Mono8
            frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif stFrameInfo.enPixelType == 17301514: # BGR8
            frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth, 3))
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            if img_data.size == stFrameInfo.nWidth * stFrameInfo.nHeight:
                frame = img_data.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            else:
                return False, None
        return True, frame


# --- Example usage (can be removed if only importing the module) ---
if __name__ == "__main__":
    cam_mgr = CameraManager()
    print("Number of cameras found:", cam_mgr.refresh_devices())
    if cam_mgr.connect(0):
        print("Connected successfully")
        success, frame = cam_mgr.capture_single(2000)
        if success:
            cv2.imwrite("test_capture.jpg", frame)
            print("Saved test_capture.jpg")

        def on_frame(frame):
            cv2.imshow("Live", frame)
            cv2.waitKey(1)

        cam_mgr.start_live(on_frame)
        time.sleep(5)
        cam_mgr.stop_live()
        cv2.destroyAllWindows()
        cam_mgr.disconnect()
    else:
        print("Connection failed")