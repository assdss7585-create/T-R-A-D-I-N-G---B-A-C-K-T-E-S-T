from collections import deque
from ..models import Pivot


class PivotTracker:
    def __init__(self):
        self.window = deque(maxlen=5)
        self.high = None
        self.low = None

    def update(self, bar):
        self.window.append(bar)
        if len(self.window) < 5:
            return []
        bars = list(self.window)
        center = bars[2]
        others = bars[:2] + bars[3:]
        pivots = []
        if all(center.high > b.high for b in others):
            self.high = Pivot("HIGH", center.high, center.timestamp, bar.available_at)
            pivots.append(self.high)
        if all(center.low < b.low for b in others):
            self.low = Pivot("LOW", center.low, center.timestamp, bar.available_at)
            pivots.append(self.low)
        return pivots
