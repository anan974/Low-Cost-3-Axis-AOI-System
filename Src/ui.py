
# PyQt5 UI for Monitoring Machine
import sys
import os
import cv2
from datetime import datetime
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
	QApplication, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
	QLineEdit, QComboBox, QFileDialog, QGroupBox, QGridLayout
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QMessageBox

# Compatibility for Qt.AlignCenter, Qt.KeepAspectRatio, Qt.SmoothTransformation
# Use integer fallback values directly for Qt alignment and scaling flags
ALIGN_CENTER = Qt.Alignment(0x0004)  # Qt.AlignCenter
KEEP_ASPECT_RATIO = 0x01  # Qt.KeepAspectRatio
SMOOTH_TRANSFORMATION = 0x02  # Qt.SmoothTransformation

class MonitoringUI(QWidget):
	def is_camera_ready(self):
		# Simulate camera check: replace with actual camera check logic
		# For demo, always return False to simulate camera not ready
		# Return True if camera is ready
		# Example: return cv2.VideoCapture(0).isOpened()
		return False  # Change to True to simulate camera ready

	def show_error(self, message):
		QMessageBox.critical(self, "Error", message)
	def __init__(self):
		super().__init__()
		self.setWindowTitle("Monitoring Machine")
		self.resize(1000, 700)
		self.init_ui()

	def init_ui(self):
		main_layout = QVBoxLayout()

		# Parameter display
		param_group = QGroupBox("Parameters")
		param_layout = QHBoxLayout()
		self.fps_label = QLabel("FPS: 0")
		self.avr_line_label = QLabel("AVR Line Width: 0")
		self.avr_space_label = QLabel("AVR Space Width: 0")
		self.error_status_label = QLabel("Error Status: None")
		self.detected_error_label = QLabel("Detected Error: 0")
		param_layout.addWidget(self.fps_label)
		param_layout.addWidget(self.avr_line_label)
		param_layout.addWidget(self.avr_space_label)
		param_layout.addWidget(self.error_status_label)
		param_layout.addWidget(self.detected_error_label)
		param_group.setLayout(param_layout)
		main_layout.addWidget(param_group)

		# Mode switch and calibration
		control_group = QGroupBox("Control")
		control_layout = QHBoxLayout()
		self.mode_combo = QComboBox()
		self.mode_combo.addItems(["Auto", "Manual"])
		self.mode_combo.currentIndexChanged.connect(self.update_mode)
		control_layout.addWidget(QLabel("Mode:"))
		control_layout.addWidget(self.mode_combo)

		self.calib_edit = QLineEdit()
		self.calib_edit.setPlaceholderText("1.0")
		self.calib_edit.setText("1.0")
		self.calib_edit.setFixedWidth(100)
		control_layout.addWidget(QLabel("Calibration:"))
		control_layout.addWidget(self.calib_edit)
		self.calib_unit_label = QLabel("um/pixel")
		control_layout.addWidget(self.calib_unit_label)

		# Show selected image path
		self.image_path_label = QLabel("")
		self.image_path_label.setStyleSheet("color: #555; font-size: 10px;")
		self.image_path_label.setFixedWidth(300)
		control_layout.addWidget(self.image_path_label)


		self.capture_btn = QPushButton("Capture")
		self.capture_btn.setEnabled(False)
		self.capture_btn.clicked.connect(self.capture_image)
		control_layout.addWidget(self.capture_btn)

		self.image_path_btn = QPushButton("Image Path")
		self.image_path_btn.setEnabled(False)
		self.image_path_btn.clicked.connect(self.select_image_path)
		control_layout.addWidget(self.image_path_btn)

		# Add Measure CD Width, Measure CD Space, and Detect Error buttons
		self.measure_cd_btn = QPushButton("Measure CD Width")
		self.measure_cd_btn.setEnabled(False)
		self.measure_cd_btn.clicked.connect(self.measure_cd_width)
		control_layout.addWidget(self.measure_cd_btn)

		self.measure_cd_space_btn = QPushButton("Measure CD Space")
		self.measure_cd_space_btn.setEnabled(False)
		self.measure_cd_space_btn.clicked.connect(self.measure_cd_space)
		control_layout.addWidget(self.measure_cd_space_btn)

		self.detect_error_btn = QPushButton("Detect Error")
		self.detect_error_btn.setEnabled(False)
		self.detect_error_btn.clicked.connect(self.detect_error)
		control_layout.addWidget(self.detect_error_btn)

		control_group.setLayout(control_layout)
		main_layout.addWidget(control_group)

		# Tabs for Live View and Measure View
		self.tabs = QTabWidget()
		self.live_view = QWidget()
		self.measure_view = QWidget()
		self.tabs.addTab(self.live_view, "Live View")
		self.tabs.addTab(self.measure_view, "Measure View")

		# Live View layout
		live_layout = QVBoxLayout()
		self.live_image_label = QLabel("Live feed will appear here")
		self.live_image_label.setAlignment(ALIGN_CENTER)
		self.live_image_label.setStyleSheet("background: #222; color: #fff; border: 1px solid #888;")
		live_layout.addWidget(self.live_image_label)
		self.live_view.setLayout(live_layout)

		# Measure View layout
		measure_layout = QVBoxLayout()
		self.measure_image_label = QLabel("Measurement result will appear here")
		self.measure_image_label.setAlignment(ALIGN_CENTER)
		self.measure_image_label.setStyleSheet("background: #222; color: #fff; border: 1px solid #888;")
		measure_layout.addWidget(self.measure_image_label)
		self.measure_view.setLayout(measure_layout)

		main_layout.addWidget(self.tabs)
		self.setLayout(main_layout)

	def update_mode(self):
		mode = self.mode_combo.currentText()
		is_manual = (mode == "Manual")
		self.capture_btn.setEnabled(is_manual)
		self.image_path_btn.setEnabled(is_manual)
		self.measure_cd_btn.setEnabled(is_manual)
		self.measure_cd_space_btn.setEnabled(is_manual)
		self.detect_error_btn.setEnabled(is_manual)

	def capture_image(self):
		# Check if camera is ready
		if not self.is_camera_ready():
			self.show_error("Error: Camera not detected or not ready.")
			return
		sample_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Sample")
		if not os.path.exists(sample_dir):
			os.makedirs(sample_dir)
		# Simulate capture: use a blank image or a test image
		img = 255 * np.ones((480, 640, 3), dtype=np.uint8)
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		img_path = os.path.join(sample_dir, f"capture_{timestamp}.png")
		cv2.imwrite(img_path, img)
		# Show in measure view
		self.show_measure_image(img_path)
		self.image_path_label.setText(img_path)
		print(f"Captured and saved: {img_path}")

	def select_image_path(self):
		file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.bmp)")
		if file_path:
			self.image_path_label.setText(file_path)
			self.show_measure_image(file_path)
			print(f"Selected image: {file_path}")
			
	def show_measure_image(self, img_path):
		img = cv2.imread(img_path)
		if img is not None:
			img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
			h, w, ch = img.shape
			bytes_per_line = ch * w
			qimg = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)
			pixmap = QPixmap.fromImage(qimg)
			self.set_measure_image(pixmap)
		else:
			self.measure_image_label.setText("Failed to load image")
			QMessageBox.warning(self, "No Image", "No image to measure.")

	def measure_cd_width(self):
		# Check if measure view contains an image
		if self.measure_image_label.pixmap() is None:
			QMessageBox.warning(self, "No Image", "No image to measure.")
			return
		# Get image path and calibration value
		img_path = self.image_path_label.text().strip()
		if not img_path or not os.path.exists(img_path):
			QMessageBox.warning(self, "No Image", "No image to measure.")
			return
		try:
			calib_str = self.calib_edit.text().strip()
			calib = float(calib_str) if calib_str else 1.0
			if not calib_str:
				self.calib_edit.setText("1.0")
		except Exception:
			QMessageBox.warning(self, "Calibration Error", "Invalid calibration value. Using 1.0 um/pixel.")
			calib = 1.0
			self.calib_edit.setText("1.0")

		# Import and call run_visual_ruler from main.py
		try:
			from main import run_visual_ruler
		except ImportError:
			QMessageBox.critical(self, "Error", "Could not import measurement algorithm.")
			return
		result = run_visual_ruler(img_path, calib)
		# If error in algorithm
		if result.get('error'):
			self.error_status_label.setText("Error Status: Failed")
			QMessageBox.critical(self, "Error", f"Algorithm error: {result['error']}")
			return
		# If no objects detected
		if not result.get('objects'):
			self.error_status_label.setText("Error Status: Failed")
			self.detected_error_label.setText("Detected Error: 1")
			QMessageBox.critical(self, "Error", "No objects detected or error image.")
			self.set_avr_line_width(None)
			self.set_avr_space_width(None)
			return
		# Show results in a message box
		msg = f"Detected {len(result['objects'])} objects.\n"
		for obj in result['objects']:
			msg += f"#{obj['id']}: {obj['shape']} | {obj['metric']} | {obj['value_px']:.2f} px | {obj['value_um']:.2f} um\n"
		QMessageBox.information(self, "Measurement Results", msg)
		# Show annotated image in measure view
		img_color = result.get('image_with_annotations')
		if img_color is not None:
			img_rgb = cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB)
			h, w, ch = img_rgb.shape
			bytes_per_line = ch * w
			qimg = QImage(img_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
			pixmap = QPixmap.fromImage(qimg)
			self.set_measure_image(pixmap)
		# Show average CD width and space width
		avr_cd = result.get('avr_cd_width_um')
		avr_space = result.get('avr_space_width_um')
		self.set_avr_line_width(avr_cd)
		self.set_avr_space_width(avr_space)
		self.error_status_label.setText("Error Status: Passed")
		self.detected_error_label.setText("Detected Error: 0")

	def measure_cd_space(self):
		# This is a placeholder for the Measure CD Space logic
		QMessageBox.information(self, "Measure CD Space", "Measure CD Space functionality is not implemented yet.")

	def detect_error(self):
		# Check if measure view contains an image
		if self.measure_image_label.pixmap() is None:
			QMessageBox.warning(self, "No Image", "No image to detect error.")
			return
		# Placeholder for detect error logic
		print("Detect Error button pressed")

	def set_fps(self, fps):
		self.fps_label.setText(f"FPS: {fps}")

	def set_avr_line_width(self, width):
		if width is None or (isinstance(width, float) and (width != width or width == float('inf') or width == float('-inf'))):
			self.avr_line_label.setText("AVR Line Width: -")
			QMessageBox.warning(self, "Error", "Cannot calculate average CD width.")
		else:
			self.avr_line_label.setText(f"AVR Line Width: {width:.2f}")

	def set_avr_space_width(self, width):
		if width is None or (isinstance(width, float) and (width != width or width == float('inf') or width == float('-inf'))):
			self.avr_space_label.setText("AVR Space Width: -")
			QMessageBox.warning(self, "Error", "Cannot calculate average space width.")
		else:
			self.avr_space_label.setText(f"AVR Space Width: {width:.2f}")
			
	def set_live_image(self, qpixmap):
		self.live_image_label.setPixmap(qpixmap.scaled(
			self.live_image_label.size(), KEEP_ASPECT_RATIO, SMOOTH_TRANSFORMATION))


	def set_measure_image(self, qpixmap):
		self.measure_image_label.setPixmap(qpixmap.scaled(
			self.measure_image_label.size(), KEEP_ASPECT_RATIO, SMOOTH_TRANSFORMATION))


def main():
	app = QApplication(sys.argv)
	window = MonitoringUI()
	window.show()
	sys.exit(app.exec_())


if __name__ == "__main__":
	main()
