import ctypes
import threading
import numpy as np
import cv2
from MvImport.MvCameraControl_class import *

class CameraManager:
    def __init__(self):
        self.cam = None
        self.device_list = []
        self._live_thread = None
        self._stop_live = False
        self.latest_frame = None
        self._frame_lock = threading.Lock()
        self.is_live = False

    def refresh_devices(self):
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        self.device_list = [deviceList.pDeviceInfo[i] for i in range(deviceList.nDeviceNum)]
        return len(self.device_list)

    def connect(self, index=0):
        if not self.device_list:
            if self.refresh_devices() == 0:
                return False
        if index >= len(self.device_list):
            return False
        self.cam = MvCamera()
        ret = self.cam.MV_CC_CreateHandle(self.device_list[index])
        if ret != 0:
            return False
        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            self.cam.MV_CC_DestroyHandle()
            self.cam = None
            return False
        return True

    def disconnect(self):
        self.stop_live()
        if self.cam:
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.cam = None

    def start_live(self, frame_callback=None):
        """Bắt đầu live stream (thread riêng). frame_callback nhận frame (numpy) mỗi khi có ảnh mới"""
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
        stOutFrame = MV_FRAME_OUT()
        while not self._stop_live and self.is_live:
            ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
            ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, 500)
            if ret == 0:
                nLen = stOutFrame.stFrameInfo.nFrameLen
                pData = (ctypes.c_ubyte * nLen)()
                ctypes.memmove(pData, stOutFrame.pBufAddr, nLen)
                data = np.frombuffer(pData, dtype=np.uint8)
                w, h = stOutFrame.stFrameInfo.nWidth, stOutFrame.stFrameInfo.nHeight
                frame = None
                if data.size == w * h:
                    frame = data.reshape((h, w))
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                elif data.size == w * h * 3:
                    frame = data.reshape((h, w, 3))
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if frame is not None:
                    with self._frame_lock:
                        self.latest_frame = frame.copy()
                    if callback:
                        callback(frame)
                self.cam.MV_CC_FreeImageBuffer(stOutFrame)
            else:
                time.sleep(0.01)
        self.is_live = False

    def stop_live(self):
        self._stop_live = True
        if self._live_thread and self._live_thread.is_alive():
            self._live_thread.join(timeout=1)
        if self.cam:
            self.cam.MV_CC_StopGrabbing()
        self.is_live = False

    def get_last_frame(self):
        """Lấy frame mới nhất (thread-safe), dùng khi live đang chạy"""
        with self._frame_lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def capture_single(self, timeout_ms=1000):
        """Chụp ảnh tĩnh (không cần live) – trả về (success, frame)"""
        if not self.cam:
            return False, None
        stOutFrame = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
        ret = self.cam.MV_CC_GetImageBuffer(stOutFrame, timeout_ms)
        if ret != 0:
            return False, None
        nLen = stOutFrame.stFrameInfo.nFrameLen
        pData = (ctypes.c_ubyte * nLen)()
        ctypes.memmove(pData, stOutFrame.pBufAddr, nLen)
        data = np.frombuffer(pData, dtype=np.uint8)
        w, h = stOutFrame.stFrameInfo.nWidth, stOutFrame.stFrameInfo.nHeight
        frame = None
        if data.size == w * h:
            frame = data.reshape((h, w))
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif data.size == w * h * 3:
            frame = data.reshape((h, w, 3))
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        self.cam.MV_CC_FreeImageBuffer(stOutFrame)
        return True, frame