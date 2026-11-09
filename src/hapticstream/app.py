"""HapticStream audio-reactive controller app."""

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
    beat = Signal(object)
    error = Signal(str)


class HapticStreamWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HapticStream")
        self.setMinimumWidth(460)

        self.driver = XInputDriver()
        self.detector = AudioBeatDetector(
            sensitivity=1.3,
            min_interval=0.12,
        )
        self.audio_capture = None
        self.events = AppSignals()
        self.current_event_strength = 0.0
        self.punch_phases = []
        self.punch_phase_index = 0

        self.events.audio_level.connect(self.update_audio_level)
        self.events.beat.connect(self.on_beat)
        self.events.error.connect(self.on_audio_error)

        self.stop_timer = QTimer(self)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.timeout.connect(self.stop_vibration)

        self.punch_timer = QTimer(self)
        self.punch_timer.setSingleShot(True)
        self.punch_timer.timeout.connect(self.play_next_punch_phase)

        self.controller_box = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_controllers)

        self.audio_start_button = QPushButton("Start audio detection")
        self.audio_start_button.clicked.connect(self.start_audio)

        self.audio_stop_button = QPushButton("Stop")
        self.audio_stop_button.clicked.connect(self.stop_audio)
        self.audio_stop_button.setEnabled(False)

        self.test_button = QPushButton("Test controller")
        self.test_button.clicked.connect(self.test_controller)

        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(45, 100)
        self.strength_slider.setValue(100)
        self.strength_label = QLabel("100%")
        self.strength_slider.valueChanged.connect(
            lambda value: self.strength_label.setText(f"{value}%")
        )

        self.audio_level = QProgressBar()
        self.audio_level.setRange(0, 100)
        self.audio_level.setValue(0)

        self.audio_status = QLabel("Audio detection stopped.")
        self.event_status = QLabel("Waiting for audio.")

        strength_row = QHBoxLayout()
        strength_row.addWidget(self.strength_slider, 1)
        strength_row.addWidget(self.strength_label)

        form = QFormLayout()
        form.addRow("Controller", self.controller_box)
        form.addRow("Master strength", strength_row)

        controls = QHBoxLayout()
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.test_button)

        audio_controls = QHBoxLayout()
        audio_controls.addWidget(self.audio_start_button)
        audio_controls.addWidget(self.audio_stop_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(controls)
        layout.addWidget(QLabel("System audio level"))
        layout.addWidget(self.audio_level)
        layout.addLayout(audio_controls)
        layout.addWidget(self.audio_status)
        layout.addWidget(self.event_status)

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

            if controllers:
                self.event_status.setText(
                    f"Found {len(controllers)} controller(s)."
                )
            else:
                self.event_status.setText(
                    "No XInput controller found. Connect one and refresh."
                )

        except XInputError as exc:
            self.event_status.setText(str(exc))

    def start_audio(self):
        if self.audio_capture is not None:
            return

        self.detector.reset()
        self.audio_capture = SystemAudioCapture(
            on_audio=self.on_audio_block,
            on_error=self.on_audio_capture_error,
        )
        self.audio_capture.start()

        self.audio_start_button.setEnabled(False)
        self.audio_stop_button.setEnabled(True)
        self.audio_status.setText("Connecting to desktop audio…")

    def on_audio_block(self, samples, sample_rate):
        rms = float(np.sqrt(np.mean(samples * samples)))
        dbfs = 20.0 * np.log10(max(rms, 1e-6))
        level = max(0.0, min(100.0, (dbfs + 60.0) * (100.0 / 60.0)))
        self.events.audio_level.emit(level)

        event = self.detector.process(samples, sample_rate)
        if event is not None:
            self.events.beat.emit(event)

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
        self.audio_status.setText(f"Audio capture error: {message}")
        self.audio_start_button.setEnabled(True)
        self.audio_stop_button.setEnabled(False)

    @staticmethod
    @staticmethod
    def motor_strength(band_level, master):
        """Map detected sound strength to a more forceful motor range."""
        if band_level < 0.08:
            return 0.0

        normalized = min(1.0, (band_level - 0.08) / 0.92)
        return max(0.70, min(1.0, master * (0.70 + 0.30 * normalized)))
    
    def on_beat(self, event):
        index = self.selected_index()
        if index is None:
            return

        self.event_status.setText(
            f"Drum hit detected — strength {event.strength:.2f}"
        )

        # Avoid stacking a weaker hit over one already playing.
        if (
            self.punch_timer.isActive()
            and event.strength <= self.current_event_strength * 1.15
        ):
            return

        master = self.strength_slider.value() / 100.0
        strength = self.motor_strength(event.strength, master)

        if strength == 0.0:
            return

        self.stop_timer.stop()
        self.current_event_strength = event.strength
        self.punch_phases = [
            (110, strength, strength),
            (20, 0.0, 0.0),
            (
                60 + round(50 * event.strength),
                strength * 0.85,
                strength * 0.85,
            ),
        ]
        self.punch_phase_index = 0
        self.play_next_punch_phase()

    def play_next_punch_phase(self):
        index = self.selected_index()
        if index is None:
            return

        if self.punch_phase_index >= len(self.punch_phases):
            self.stop_vibration()
            return

        duration_ms, left, right = self.punch_phases[self.punch_phase_index]
        self.punch_phase_index += 1

        try:
            self.driver.set_vibration(index, left, right)
            self.punch_timer.start(duration_ms)
        except XInputError as exc:
            self.event_status.setText(f"Controller error: {exc}")
            self.stop_vibration()

    def test_controller(self):
        index = self.selected_index()
        if index is None:
            self.event_status.setText("Connect a controller first.")
            return

        self.punch_timer.stop()
        self.stop_timer.stop()

        strength = self.strength_slider.value() / 100.0
        try:
            self.driver.set_vibration(index, strength, strength)
            self.stop_timer.start(250)
            self.event_status.setText("Controller test pulse.")
        except XInputError as exc:
            self.event_status.setText(f"Controller error: {exc}")

    def stop_vibration(self):
        self.stop_timer.stop()
        self.punch_timer.stop()
        self.current_event_strength = 0.0

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
        self.audio_level.setValue(0)
        self.audio_status.setText("Audio detection stopped.")
        self.audio_start_button.setEnabled(True)
        self.audio_stop_button.setEnabled(False)

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