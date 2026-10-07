from dataclasses import dataclass
from datetime import datetime


@dataclass
class FibLeg:
    direction: str
    start: float
    end: float
    start_time: datetime
    end_time: datetime

    @property
    def level(self):
        # start -> end; 0.618 retraces FROM the end back toward the start.
        return self.end + 0.618 * (self.start - self.end)

    def valid(self):
        return self.end > self.start if self.direction == "LONG" else self.end < self.start


def select_leg(direction, origin, history, config):
    previous = history[-2] if len(history) >= 2 else None
    if config.fib_origin == "last_candle_extreme":
        if previous is None:
            return None
        start = previous.low if direction == "LONG" else previous.high
        start_time = previous.timestamp
    else:
        if origin is None:
            return None
        start, start_time = origin.price, origin.timestamp
    segment = [b for b in history if b.timestamp >= start_time]
    if not segment:
        return None
    end_bar = (max(segment, key=lambda b: b.high) if direction == "LONG"
               else min(segment, key=lambda b: b.low))
    end = end_bar.high if direction == "LONG" else end_bar.low
    leg = FibLeg(direction, start, end, start_time, end_bar.timestamp)
    return leg if leg.valid() else None
