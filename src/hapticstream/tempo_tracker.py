"""Online tempo and beat-phase tracker for detected drum onsets."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TempoEstimate:
    bpm: float | None
    locked: bool
    on_beat: bool
    phase_error_ms: float | None
    next_beat_time: float | None


class TempoPhaseTracker:
    """Estimate a steady beat period and phase from onset timestamps."""

    MIN_PERIOD = 60.0 / 180.0
    MAX_PERIOD = 60.0 / 60.0
    DEFAULT_PERIOD = 0.5

    def __init__(
        self,
        min_bpm: float = 60.0,
        max_bpm: float = 180.0,
        phase_gain: float = 0.35,
        tempo_gain: float = 0.08,
    ):
        if min_bpm <= 0 or max_bpm <= min_bpm:
            raise ValueError("BPM range must be positive and increasing.")

        self.min_period = 60.0 / max_bpm
        self.max_period = 60.0 / min_bpm
        self.default_period = self.DEFAULT_PERIOD
        self.phase_gain = phase_gain
        self.tempo_gain = tempo_gain
        self.reset()

    def reset(self) -> None:
        """Forget the current tempo and reacquire from new onsets."""
        self.period: float | None = None
        self.phase_anchor: float | None = None
        self.last_onset: float | None = None
        self._intervals: deque[float] = deque(maxlen=8)
        self._aligned_hits = 0
        self._consecutive_offbeats = 0
        self._locked = False

    @property
    def bpm(self) -> float | None:
        return None if self.period is None else 60.0 / self.period

    @property
    def locked(self) -> bool:
        return self._locked

    def _candidate_period(self, interval: float) -> float:
        """Choose an interval or half/double-time equivalent."""
        candidates = set()

        for multiple in (1, 2, 3, 4):
            shorter = interval / multiple
            longer = interval * multiple

            if self.min_period <= shorter <= self.max_period:
                candidates.add(shorter)
            if self.min_period <= longer <= self.max_period:
                candidates.add(longer)

        if not candidates:
            return min(self.max_period, max(self.min_period, interval))

        reference = self.period or self.default_period
        return min(
            candidates,
            key=lambda candidate: (
                abs(math.log(candidate / reference)),
                -candidate,
            ),
        )

    def observe_onset(self, timestamp: float) -> TempoEstimate:
        """Update tempo and phase from one detected drum onset."""
        if self.last_onset is None:
            self.last_onset = timestamp
            self.phase_anchor = timestamp
            return self.current_estimate(timestamp, on_beat=False)

        interval = timestamp - self.last_onset

        if interval <= 0:
            return self.current_estimate(timestamp, on_beat=False)

        # Ignore close secondary transients without moving the anchor.
        if interval < 0.18:
            return self.current_estimate(timestamp, on_beat=False)

        # Reacquire after a long silence or track change.
        if interval > 4.0:
            self.reset()
            self.last_onset = timestamp
            self.phase_anchor = timestamp
            return self.current_estimate(timestamp, on_beat=False)

        candidate = self._candidate_period(interval)
        self._intervals.append(candidate)

        if self.period is None:
            self.period = candidate
        else:
            self.period = (
                (1.0 - self.tempo_gain) * self.period
                + self.tempo_gain * candidate
            )

        anchor = self.phase_anchor if self.phase_anchor is not None else timestamp
        beat_number = max(1, round((timestamp - anchor) / self.period))
        expected_time = anchor + beat_number * self.period
        phase_error = timestamp - expected_time
        on_beat = abs(phase_error) <= 0.22 * self.period

        if on_beat:
            self.phase_anchor = anchor + self.phase_gain * phase_error
            self._aligned_hits += 1
            self._consecutive_offbeats = 0

            observed_period = interval / beat_number
            if self.min_period <= observed_period <= self.max_period:
                self.period = (
                    (1.0 - self.tempo_gain) * self.period
                    + self.tempo_gain * observed_period
                )

            if len(self._intervals) >= 3 and self._aligned_hits >= 3:
                self._locked = True
        else:
            if self._locked:
                self._consecutive_offbeats += 1
                if self._consecutive_offbeats >= 4:
                    self._locked = False
                    self._aligned_hits = 0
            else:
                self._aligned_hits = 0

        self.last_onset = timestamp
        return self.current_estimate(
            timestamp,
            on_beat=on_beat,
            phase_error=phase_error,
        )

    def predict_next_beat(self, now: float) -> float | None:
        """Return the next predicted beat time on the monotonic clock."""
        if self.period is None or self.phase_anchor is None:
            return None

        beat_number = math.floor(
            (now - self.phase_anchor) / self.period
        ) + 1
        return self.phase_anchor + beat_number * self.period

    def current_estimate(
        self,
        now: float,
        on_beat: bool = False,
        phase_error: float | None = None,
    ) -> TempoEstimate:
        error_ms = None if phase_error is None else phase_error * 1000.0
        return TempoEstimate(
            bpm=self.bpm,
            locked=self.locked,
            on_beat=on_beat,
            phase_error_ms=error_ms,
            next_beat_time=self.predict_next_beat(now),
        )