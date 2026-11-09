"""Preview screen capture while targeting the display refresh rate."""

import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .screen_capture import MonitorInfo, ScreenCapture


class ScreenMonitorWindow(QMainWindow):
    PREVIEW_INTERVAL_MS = 33

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HapticStream — Screen Monitor")
        self.setMinimumSize(900, 600)

        self.capture = None
        self.monitors = []
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()
        self.last_pixmap = None

        self.monitor_box = QComboBox()
        self.start_button = QPushButton("Start screen capture")
        self.start_button.clicked.connect(self.start_capture)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_capture)
        self.stop_button.setEnabled(False)

        self.status_label = QLabel("Stopped")
        self.preview = QLabel("Screen preview will appear here")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(800, 450)
        self.preview.setStyleSheet("background-color: #202020; color: white;")

        controls = QHBoxLayout()
        controls.addWidget(self.monitor_box, 1)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(self.PREVIEW_INTERVAL_MS)
        self.preview_timer.timeout.connect(self.render_latest_frame)

        self.load_monitors()

    def load_monitors(self):
        try:
            self.monitors = ScreenCapture.list_monitors()

            for monitor in self.monitors:
                self.monitor_box.addItem(monitor.label, monitor.index)

            if not self.monitors:
                self.status_label.setText("No displays were found.")
                self.start_button.setEnabled(False)

        except Exception as exc:
            self.status_label.setText(f"Could not list displays: {exc}")
            self.start_button.setEnabled(False)

    def refresh_rate_for_monitor(self, monitor: MonitorInfo) -> int:
        screens = QApplication.screens()
        if not screens:
            return 60

        selected_screen = None
        primary_screen = QApplication.primaryScreen()

        if monitor.primary and primary_screen is not None:
            selected_screen = primary_screen
        else:
            for screen in screens:
                geometry = screen.geometry()
                scale = screen.devicePixelRatio()
                screen_width = round(geometry.width() * scale)
                screen_height = round(geometry.height() * scale)

                same_size = (
                    (screen_width == monitor.width and screen_height == monitor.height)
                    or (screen_width == monitor.height and screen_height == monitor.width)
                )

                if same_size and screen is not primary_screen:
                    selected_screen = screen
                    break

        if selected_screen is None:
            fallback_index = min(monitor.index - 1, len(screens) - 1)
            selected_screen = screens[fallback_index]

        refresh_rate = round(selected_screen.refreshRate())
        return refresh_rate if refresh_rate > 0 else 60

    def start_capture(self):
        monitor_index = self.monitor_box.currentData()
        if monitor_index is None:
            return

        monitor = next(
            (
                item for item in self.monitors
                if item.index == int(monitor_index)
            ),
            None,
        )
        if monitor is None:
            return

        fps = self.refresh_rate_for_monitor(monitor)

        self.capture = ScreenCapture(
            on_frame=self.on_frame,
            on_error=self.on_capture_error,
            monitor_index=monitor.index,
            fps=fps,
        )
        self.capture.start()
        self.preview_timer.start()

        self.status_label.setText(
            f"Capturing {monitor.label} — target {fps} FPS; "
            "preview updates at about 30 FPS."
        )
        self.start_button.setEnabled(False)
        self.monitor_box.setEnabled(False)
        self.stop_button.setEnabled(True)

    def on_frame(self, frame, _timestamp):
        # Keep only the newest frame so slow preview rendering cannot build a queue.
        with self.latest_frame_lock:
            self.latest_frame = frame

    def render_latest_frame(self):
        with self.latest_frame_lock:
            frame = self.latest_frame

        if frame is None:
            return

        height, width, _channels = frame.shape
        image = QImage(
            frame.data,
            width,
            height,
            frame.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()

        self.last_pixmap = QPixmap.fromImage(image)

        scaled = self.last_pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview.setPixmap(scaled)

    def on_capture_error(self, error):
        self.preview_timer.stop()
        self.status_label.setText(f"Capture error: {error}")
        self.start_button.setEnabled(True)
        self.monitor_box.setEnabled(True)
        self.stop_button.setEnabled(False)

    def stop_capture(self):
        self.preview_timer.stop()

        if self.capture is not None:
            self.capture.stop()
            self.capture = None

        with self.latest_frame_lock:
            self.latest_frame = None

        self.last_pixmap = None
        self.preview.clear()
        self.preview.setText("Screen preview will appear here")
        self.start_button.setEnabled(self.monitor_box.count() > 0)
        self.monitor_box.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopped")

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = ScreenMonitorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())