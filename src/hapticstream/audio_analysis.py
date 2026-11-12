"""Detect individual percussive attacks in live audio using aubio."""

from __future__ import annotations

import time
from dataclasses import dataclass

import aubio
import numpy as np


@dataclass(frozen=True)
class BeatEvent:
    timestamp: float
    strength: float
    energy_ratio: float
    bass: float
    mid: float
    high: float
    bpm: float = 0.0
    confidence: float = 1.0


class AudioBeatDetector:
    """Emit a haptic event for each detected audio onset."""

    HOP_SIZE = 512
    BUFFER_SIZE = 1024

    def __init__(
        self,
        sensitivity: float = 1.8,
        min_interval: float = 0.09,
        history_size: int = 60,
    ):
        self.sensitivity = sensitivity
        self.min_interval = min_interval
        self.history_size = history_size

        self._onset = None
        self._sample_rate: int | None = None
        self._pending_samples = np.empty(0, dtype=np.float32)
        self._last_event_time = float("-inf")

    def _make_detector(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._onset = aubio.onset(
            "default",
            self.BUFFER_SIZE,
            self.HOP_SIZE,
            sample_rate,
        )
        self._pending_samples = np.empty(0, dtype=np.float32)
        self._last_event_time = float("-inf")

    def reset(self) -> None:
        self._onset = None
        self._sample_rate = None
        self._pending_samples = np.empty(0, dtype=np.float32)
        self._last_event_time = float("-inf")

    def process(
        self,
        samples: np.ndarray,
        sample_rate: int,
        timestamp: float | None = None,
    ) -> BeatEvent | None:
        if sample_rate <= 0:
            raise ValueError("Sample rate must be positive.")

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return None

        now = time.perf_counter() if timestamp is None else timestamp

        if self._onset is None or self._sample_rate != sample_rate:
            self._make_detector(sample_rate)

        self._pending_samples = np.concatenate(
            (self._pending_samples, audio)
        )

        detected = False

        while self._pending_samples.size >= self.HOP_SIZE:
            block = self._pending_samples[:self.HOP_SIZE]
            self._pending_samples = self._pending_samples[self.HOP_SIZE:]

            onset_result = self._onset(block)
            if float(onset_result[0]) != 0.0:
                detected = True

        if not detected or now - self._last_event_time < self.min_interval:
            return None

        self._last_event_time = now

        # Request full strength for each detected attack. The app’s slider
        # still controls the actual controller strength.
        return BeatEvent(
            timestamp=now,
            strength=1.0,
            energy_ratio=1.0,
            bass=0.0,
            mid=1.0,
            high=0.0,
            bpm=0.0,
            confidence=1.0,
        )