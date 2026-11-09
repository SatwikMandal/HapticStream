"""Detect kick and snare-like drum transients in live audio."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BeatEvent:
    timestamp: float
    strength: float
    energy_ratio: float

    # Retained so existing app code can be updated in the next step.
    bass: float
    mid: float
    high: float


class AudioBeatDetector:
    """Detect transient energy in bass and drum-body frequency ranges."""

    WINDOW_SIZE = 2048

    # These ranges catch kick/bass and much of a snare's body.
    # The high band is intentionally ignored to reduce cymbal triggers.
    BANDS = {
        "bass": (35.0, 150.0),
        "drum": (150.0, 5000.0),
    }

    def __init__(
        self,
        sensitivity: float = 1.3,
        min_interval: float = 0.12,
        history_size: int = 60,
    ):
        if sensitivity <= 1.0:
            raise ValueError("Sensitivity must be greater than 1.0.")
        if min_interval < 0:
            raise ValueError("Minimum interval cannot be negative.")

        self.sensitivity = sensitivity
        self.min_interval = min_interval
        self._history = {
            name: deque(maxlen=history_size) for name in self.BANDS
        }
        self._previous = {name: 0.0 for name in self.BANDS}
        self._last_event = {
            name: float("-inf") for name in self.BANDS
        }
        self._sample_buffer = np.zeros(self.WINDOW_SIZE, dtype=np.float32)

    def reset(self) -> None:
        """Clear recent audio and detector history."""
        for history in self._history.values():
            history.clear()

        self._previous = {name: 0.0 for name in self.BANDS}
        self._last_event = {
            name: float("-inf") for name in self.BANDS
        }
        self._sample_buffer.fill(0.0)

    def process(
        self,
        samples: np.ndarray,
        sample_rate: int,
        timestamp: float | None = None,
    ) -> BeatEvent | None:
        """Analyze one audio block; return a drum-like onset if detected."""
        if sample_rate <= 0:
            raise ValueError("Sample rate must be positive.")

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return None

        now = time.perf_counter() if timestamp is None else timestamp

        if audio.size >= self.WINDOW_SIZE:
            self._sample_buffer[:] = audio[-self.WINDOW_SIZE:]
        else:
            self._sample_buffer[:-audio.size] = self._sample_buffer[audio.size:]
            self._sample_buffer[-audio.size:] = audio

        window = np.hanning(self.WINDOW_SIZE)
        spectrum = np.abs(np.fft.rfft(self._sample_buffer * window))
        frequencies = np.fft.rfftfreq(
            self.WINDOW_SIZE,
            d=1.0 / sample_rate,
        )
        normalization = max(float(np.sum(window)), 1.0)

        energies = {}
        for name, (low_hz, high_hz) in self.BANDS.items():
            mask = (frequencies >= low_hz) & (frequencies < high_hz)
            if np.any(mask):
                energies[name] = float(
                    np.sqrt(2.0 * np.sum(spectrum[mask] ** 2))
                    / normalization
                )
            else:
                energies[name] = 0.0

        onsets = {}
        ratios = {}

        for name, energy in energies.items():
            history = self._history[name]
            baseline = (
                float(np.median(history))
                if len(history) >= 8
                else energy
            )
            ratio = energy / max(baseline, 0.001)
            ratios[name] = ratio

            onset = (
                len(history) >= 8
                and energy > 0.001
                and energy > baseline * self.sensitivity
                and energy > self._previous[name] * 1.02
                and now - self._last_event[name] >= self.min_interval
            )

            if onset:
                onsets[name] = max(0.0, min(1.0, (ratio - 1.0) / 2.5))
                self._last_event[name] = now

            history.append(energy)
            self._previous[name] = energy

        if not onsets:
            return None

        bass_strength = onsets.get("bass", 0.0)
        drum_strength = onsets.get("drum", 0.0)

        return BeatEvent(
            timestamp=now,
            strength=max(bass_strength, drum_strength),
            energy_ratio=max(ratios[name] for name in onsets),
            bass=bass_strength,
            mid=drum_strength,
            high=0.0,
        )