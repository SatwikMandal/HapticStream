"""Small live meter for checking Windows system-audio capture."""

import sys

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .audio_capture import SystemAudioCapture


class AudioSignals(QObject):
    level = Signal(float)
    status = Signal(str)
    error = Signal(str)


class AudioMonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HapticStream — Audio Monitor")
        self.setMinimumWidth(380)

        self.capture = None
        self.signals = AudioSignals()
        self.signals.level.connect(self.update_level)
        self.signals.status.connect(self.status_label_text)
        self.signals.error.connect(self.show_error)

        self.status_label = QLabel("Stopped")
        self.level_label = QLabel("Audio level: —")
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)

        self.start_button = QPushButton("Start listening")
        self.start_button.clicked.connect(self.start_capture)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_capture)
        self.stop_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.level_label)
        layout.addWidget(self.level_bar)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def start_capture(self):
        self.capture = SystemAudioCapture(
            on_audio=self.on_audio,
            on_error=self.on_capture_error,
        )
        self.capture.start()

        self.status_label.setText("Connecting to the default output…")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def on_audio(self, samples, sample_rate):
        rms = float(np.sqrt(np.mean(samples * samples)))
        dbfs = 20.0 * np.log10(max(rms, 1e-6))

        # Convert the -60 to 0 dBFS range into a 0–100 meter.
        level = max(0.0, min(100.0, (dbfs + 60.0) * (100.0 / 60.0)))
        self.signals.level.emit(level)

        if self.capture is not None and self.capture.device_name:
            self.signals.status.emit(
                f"Listening to {self.capture.device_name} at {sample_rate} Hz"
            )

    def on_capture_error(self, error):
        self.signals.error.emit(str(error))

    def update_level(self, level):
        self.level_bar.setValue(round(level))
        dbfs = (level * 0.6) - 60.0
        self.level_label.setText(f"Audio level: {dbfs:.1f} dBFS")

    def status_label_text(self, text):
        self.status_label.setText(text)

    def show_error(self, message):
        self.status_label.setText(f"Capture error: {message}")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def stop_capture(self):
        if self.capture is not None:
            self.capture.stop()
            self.capture = None

        self.level_bar.setValue(0)
        self.level_label.setText("Audio level: —")
        self.status_label.setText("Stopped")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = AudioMonitorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())