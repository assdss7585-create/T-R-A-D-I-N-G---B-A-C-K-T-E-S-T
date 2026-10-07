from ..models import Break
from .pivots import PivotTracker


class MarketStructure:
    def __init__(self, break_mode="once_per_pivot"):
        self.pivots = PivotTracker()
        self.broken = set()
        self.break_mode = break_mode

    def update(self, bar):
        confirmed = self.pivots.update(bar)
        candidates = []
        for direction, pivot, origin in (
            ("LONG", self.pivots.high, self.pivots.low),
            ("SHORT", self.pivots.low, self.pivots.high),
        ):
            if pivot is None:
                continue
            key = (pivot.kind, pivot.timestamp)
            beyond = bar.close > pivot.price if direction == "LONG" else bar.close < pivot.price
            if beyond and (self.break_mode == "every_qualifying_close" or key not in self.broken):
                candidates.append(Break(direction, bar.available_at, pivot, origin))
        if len(candidates) > 1:
            raise ValueError("Conflicting simultaneous structural breaks; cannot select direction objectively")
        for event in candidates:
            self.broken.add((event.broken.kind, event.broken.timestamp))
        return confirmed, candidates
