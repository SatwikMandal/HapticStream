"""High-speed display capture using Windows Desktop Duplication."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import dxcam
import numpy as np


FrameCallback = Callable[[np.ndarray, float], None]
ErrorCallback = Callable[[Exception], None]


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    device_index: int
    output_index: int
    width: int
    height: int
    primary: bool

    @property
    def label(self) -> str:
        primary_text = ", primary" if self.primary else ""
        return (
            f"Display {self.index}: {self.width}×{self.height}"
            f"{primary_text}"
        )


class ScreenCapture:
    """Capture RGB frames from a display on a background thread."""

    OUTPUT_PATTERN = re.compile(
        r"Device\[(\d+)\]\s+Output\[(\d+)\]:\s+"
        r"Res:\((\d+),\s*(\d+)\)\s+Rot:\d+\s+Primary:(True|False)"
    )

    def __init__(
        self,
        on_frame: FrameCallback,
        on_error: ErrorCallback | None = None,
        monitor_index: int = 1,
        fps: int = 60,
    ):
        if fps < 1 :
            raise ValueError("Capture rate must be positive.")

        self._on_frame = on_frame
        self._on_error = on_error
        self.monitor_index = monitor_index
        self.fps = fps

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: Exception | None = None

    @classmethod
    def list_monitors(cls) -> list[MonitorInfo]:
        """Return displays reported by DXcam."""
        info = dxcam.output_info()
        monitors = []

        for match in cls.OUTPUT_PATTERN.finditer(info):
            device, output, width, height, primary = match.groups()
            monitors.append(
                MonitorInfo(
                    index=len(monitors) + 1,
                    device_index=int(device),
                    output_index=int(output),
                    width=int(width),
                    height=int(height),
                    primary=(primary == "True"),
                )
            )

        if not monitors:
            raise RuntimeError(
                "DXcam did not report any displays. Check the Windows display "
                "driver and try again."
            )

        return monitors

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start capturing frames on a background thread."""
        if self.is_running:
            raise RuntimeError("Screen capture is already running.")

        self._stop_event.clear()
        self.error = None
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="HapticStreamScreenCapture",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop capture and wait briefly for the capture thread."""
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _capture_loop(self) -> None:
        camera = None

        try:
            monitors = self.list_monitors()
            monitor = next(
                (item for item in monitors if item.index == self.monitor_index),
                None,
            )
            if monitor is None:
                raise ValueError(f"Display {self.monitor_index} is unavailable.")

            camera = dxcam.create(
                device_idx=monitor.device_index,
                output_idx=monitor.output_index,
                output_color="RGB",
                processor_backend="numpy",
            )
            camera.start(target_fps=self.fps, video_mode=True)

            while not self._stop_event.is_set():
                frame, timestamp = camera.get_latest_frame(with_timestamp=True)
                if frame is not None:
                    self._on_frame(
                        frame,
                        float(timestamp or time.perf_counter()),
                    )

        except Exception as exc:
            self.error = exc
            if self._on_error is not None:
                self._on_error(exc)

        finally:
            if camera is not None:
                try:
                    camera.stop()
                except Exception:
                    pass
                try:
                    camera.release()
                except Exception:
                    pass