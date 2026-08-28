"""iOS MJPEG 基于帧大小与到达间隔的自适应 FPS 阶梯。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

_FPS_LADDER = (3.0, 5.0, 8.0, 12.0, 15.0, 20.0)


@dataclass(slots=True)
class IosQualitySnapshot:
    fps: float
    average_frame_bytes: int
    average_interval_ms: float
    regime: str


class IosQualityController:
    def __init__(self, initial_fps: float = 12.0) -> None:
        self.enabled = False
        self.target_fps = float(initial_fps)
        self._samples: deque[tuple[float, int]] = deque(maxlen=30)
        self._last_change = 0.0
        self._regime = "STEADY"

    def observe(self, frame_bytes: int) -> float | None:
        now = time.monotonic()
        self._samples.append((now, int(frame_bytes)))
        if not self.enabled or len(self._samples) < 10:
            return None
        intervals = [
            self._samples[index][0] - self._samples[index - 1][0]
            for index in range(1, len(self._samples))
        ]
        avg_interval = sum(intervals) / len(intervals)
        avg_size = sum(size for _ts, size in self._samples) / len(self._samples)
        expected = 1.0 / max(self.target_fps, 1.0)
        if avg_interval > expected * 1.8 or avg_size > 1_500_000:
            self._regime = "STRESSED"
            direction = -1
        elif avg_interval < expected * 1.15 and avg_size < 500_000:
            self._regime = "HEALTHY"
            direction = 1
        else:
            self._regime = "STEADY"
            return None
        if now - self._last_change < 8.0:
            return None
        index = min(
            range(len(_FPS_LADDER)),
            key=lambda item: abs(_FPS_LADDER[item] - self.target_fps),
        )
        target = _FPS_LADDER[max(0, min(len(_FPS_LADDER) - 1, index + direction))]
        if target == self.target_fps:
            return None
        self.target_fps = target
        self._last_change = now
        return target

    def snapshot(self) -> IosQualitySnapshot:
        if len(self._samples) < 2:
            return IosQualitySnapshot(self.target_fps, 0, 0.0, self._regime)
        intervals = [
            self._samples[index][0] - self._samples[index - 1][0]
            for index in range(1, len(self._samples))
        ]
        return IosQualitySnapshot(
            fps=self.target_fps,
            average_frame_bytes=int(
                sum(size for _ts, size in self._samples) / len(self._samples)
            ),
            average_interval_ms=(sum(intervals) / len(intervals)) * 1000,
            regime=self._regime,
        )
