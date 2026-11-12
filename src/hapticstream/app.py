"""HapticStream: drum-focused music mode with beat-triggered haptics."""

import sys

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .audio_analysis import AudioBeatDetector
from .audio_capture import SystemAudioCapture
from .xinput import XInputDriver, XInputError


class AppSignals(QObject):
    audio_level = Signal(float)
    drum_onset = Signal(object)
    error = Signal(str)


class HapticStreamWindow(QMainWindow):
    HAPTIC_PULSE_MS = 120
    

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HapticStream — Music Mode")
        self.setMinimumWidth(460)

        self.driver = XInputDriver()
        self.detector = AudioBeatDetector(
            sensitivity=1.8,
            min_interval=0.13,
        )
        self.audio_capture = None
        self.events = AppSignals()

        self.events.audio_level.connect(self.update_audio_level)
        self.events.drum_onset.connect(self.on_drum_onset)
        self.events.error.connect(self.on_audio_error)

        self.stop_timer = QTimer(self)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.timeout.connect(self.stop_vibration)

        self.controller_box = QComboBox()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_controllers)

        self.start_button = QPushButton("Start music mode")
        self.start_button.clicked.connect(self.start_audio)

        self.stop_audio_button = QPushButton("Stop")
        self.stop_audio_button.clicked.connect(self.stop_audio)
        self.stop_audio_button.setEnabled(False)

        self.test_button = QPushButton("Test controller")
        self.test_button.clicked.connect(self.test_controller)

        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(45, 100)
        self.strength_slider.setValue(100)

        self.strength_label = QLabel("100%")
        self.strength_slider.valueChanged.connect(
            lambda value: self.strength_label.setText(f"{value}%")
        )

        strength_row = QHBoxLayout()
        strength_row.addWidget(self.strength_slider, 1)
        strength_row.addWidget(self.strength_label)

        self.audio_level = QProgressBar()
        self.audio_level.setRange(0, 100)
        self.audio_level.setValue(0)

        self.audio_status = QLabel("Music mode stopped.")
        self.beat_status = QLabel("Waiting for detected beats.")

        form = QFormLayout()
        form.addRow("Controller", self.controller_box)
        form.addRow("Haptic strength", strength_row)

        controller_row = QHBoxLayout()
        controller_row.addWidget(self.refresh_button)
        controller_row.addWidget(self.test_button)

        audio_row = QHBoxLayout()
        audio_row.addWidget(self.start_button)
        audio_row.addWidget(self.stop_audio_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(controller_row)
        layout.addWidget(QLabel("System audio level"))
        layout.addWidget(self.audio_level)
        layout.addLayout(audio_row)
        layout.addWidget(self.audio_status)
        layout.addWidget(self.beat_status)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.refresh_controllers()

    def selected_index(self):
        data = self.controller_box.currentData()
        return int(data) if data is not None else None

    def refresh_controllers(self):
        try:
            controllers = self.driver.connected_controllers()
            self.controller_box.clear()

            for controller in controllers:
                self.controller_box.addItem(
                    f"Controller {controller.index}",
                    controller.index,
                )

            if not controllers:
                self.beat_status.setText(
                    "No XInput controller found. Connect one and refresh."
                )

        except XInputError as exc:
            self.beat_status.setText(str(exc))

    def start_audio(self):
        if self.audio_capture is not None:
            return

        self.stop_vibration()
        self.detector.reset()

        self.audio_capture = SystemAudioCapture(
            on_audio=self.on_audio_block,
            on_error=self.on_audio_capture_error,
        )
        self.audio_capture.start()

        self.start_button.setEnabled(False)
        self.stop_audio_button.setEnabled(True)
        self.audio_status.setText("Connecting to desktop audio…")
        self.beat_status.setText("Listening for beats…")

    def on_audio_block(self, samples, sample_rate):
        samples = np.asarray(samples, dtype=np.float32)

        if samples.size:
            rms = float(np.sqrt(np.mean(samples * samples)))
            dbfs = 20.0 * np.log10(max(rms, 1e-6))
            level = max(0.0, min(100.0, (dbfs + 60.0) * (100.0 / 60.0)))
            self.events.audio_level.emit(level)

        event = self.detector.process(samples, sample_rate)
        if event is not None:
            self.events.drum_onset.emit(event)

    def update_audio_level(self, level):
        self.audio_level.setValue(round(level))

        if self.audio_capture is not None:
            device = self.audio_capture.device_name
            sample_rate = self.audio_capture.sample_rate

            if device and sample_rate:
                self.audio_status.setText(
                    f"Listening to {device} at {sample_rate} Hz"
                )

    def on_audio_capture_error(self, error):
        self.events.error.emit(str(error))

    def on_audio_error(self, message):
        self.stop_timer.stop()
        self.stop_vibration()
        self.audio_status.setText(f"Audio capture error: {message}")
        self.start_button.setEnabled(True)
        self.stop_audio_button.setEnabled(False)

    def on_drum_onset(self, event):
        index = self.selected_index()

        if index is None:
            self.beat_status.setText(
                "Beat detected — connect a controller."
            )
            return

        # Apply the slider setting directly, without scaling it by
        # aubio's confidence or the detected event's strength.
        strength = self.strength_slider.value() / 100.0

        bpm = getattr(event, "bpm", 0.0)
        bpm_text = f" · {bpm:.0f} BPM" if bpm else ""
        self.beat_status.setText(f"Beat detected{bpm_text}")

        try:
            self.driver.set_vibration(index, strength, strength)
            self.stop_timer.start(self.HAPTIC_PULSE_MS)
        except XInputError as exc:
            self.beat_status.setText(f"Controller error: {exc}")

    def test_controller(self):
        index = self.selected_index()

        if index is None:
            self.beat_status.setText("Connect a controller first.")
            return

        self.stop_timer.stop()

        strength = self.strength_slider.value() / 100.0

        try:
            self.driver.set_vibration(index, strength, strength)
            self.stop_timer.start(250)
            self.beat_status.setText("Controller test pulse.")
        except XInputError as exc:
            self.beat_status.setText(f"Controller error: {exc}")

    def stop_vibration(self):
        self.stop_timer.stop()
        index = self.selected_index()

        if index is not None:
            try:
                self.driver.stop(index)
            except XInputError:
                pass

    def stop_audio(self):
        if self.audio_capture is not None:
            self.audio_capture.stop()
            self.audio_capture = None

        self.stop_vibration()
        self.detector.reset()
        self.audio_level.setValue(0)
        self.audio_status.setText("Music mode stopped.")
        self.beat_status.setText("Waiting for detected beats.")
        self.start_button.setEnabled(True)
        self.stop_audio_button.setEnabled(False)

    def closeEvent(self, event):
        self.stop_audio()
        self.driver.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = HapticStreamWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())