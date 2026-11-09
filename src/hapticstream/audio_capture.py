"""Capture audio playing through the default Windows output device."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
import pyaudiowpatch as pyaudio


AudioCallback = Callable[[np.ndarray, int], None]
ErrorCallback = Callable[[Exception], None]


class SystemAudioCapture:
    """Read system audio through WASAPI loopback on a background thread.

    The audio callback receives:
      - a mono float32 NumPy array with values approximately between -1 and 1
      - the sample rate in samples per second

    The callback runs on the capture thread. Do not update Qt widgets directly
    from it; use a Qt signal when connecting it to the UI.
    """

    CHUNK_FRAMES = 512

    def __init__(
        self,
        on_audio: AudioCallback,
        on_error: ErrorCallback | None = None,
    ):
        self._on_audio = on_audio
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self.sample_rate: int | None = None
        self.channels: int | None = None
        self.device_name: str | None = None
        self.error: Exception | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start capturing. Audio blocks arrive through the callback."""
        if self.is_running:
            raise RuntimeError("System audio capture is already running.")

        self._stop_event.clear()
        self.error = None
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="HapticStreamAudioCapture",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Request capture to stop and wait briefly for the audio stream."""
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _capture_loop(self) -> None:
        audio = None
        stream = None

        try:
            audio = pyaudio.PyAudio()
            device = audio.get_default_wasapi_loopback()

            self.device_name = str(device["name"])
            self.sample_rate = int(device["defaultSampleRate"])
            self.channels = int(device["maxInputChannels"])

            if self.channels < 1:
                raise RuntimeError(
                    f'Loopback device "{self.device_name}" has no input channels.'
                )

            stream = audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=self.CHUNK_FRAMES,
            )

            while not self._stop_event.is_set():
                raw_audio = stream.read(
                    self.CHUNK_FRAMES,
                    exception_on_overflow=False,
                )

                samples = np.frombuffer(raw_audio, dtype=np.int16)

                if self.channels > 1:
                    samples = samples.reshape(-1, self.channels).mean(axis=1)

                mono_float = samples.astype(np.float32) / 32768.0
                self._on_audio(mono_float, self.sample_rate)

        except Exception as exc:
            self.error = exc
            if self._on_error is not None:
                self._on_error(exc)

        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

            if audio is not None:
                try:
                    audio.terminate()
                except Exception:
                    pass