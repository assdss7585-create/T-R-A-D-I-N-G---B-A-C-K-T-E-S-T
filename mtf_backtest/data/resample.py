"""Emit 4H candles only after all sixteen 15m candles have closed."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..models import Candle


class FourHourAggregator:
    def __init__(self, config):
        self.zone = ZoneInfo(config.timezone)
        self.anchor = config.h4_anchor_minutes
        self.start = None
        self.bars = []
        self.discarded_buckets = 0

    def bucket(self, timestamp):
        # Local midnight anchors each trading day; 4H means elapsed 4 hours.
        local = timestamp.astimezone(self.zone)
        midnight = datetime(local.year, local.month, local.day, tzinfo=self.zone)
        anchor = midnight.astimezone(timezone.utc) + timedelta(minutes=self.anchor)
        count = (timestamp - anchor) // timedelta(hours=4)
        return anchor + count * timedelta(hours=4)

    def update(self, bar):
        start = self.bucket(bar.timestamp)
        if start != self.start:
            if self.bars:
                self.discarded_buckets += 1
            self.start, self.bars = start, []
        self.bars.append(bar)
        end = start + timedelta(hours=4)
        if bar.available_at != end:
            return None
        complete = len(self.bars) == 16 and all(
            b.timestamp == start + timedelta(minutes=15 * i) for i, b in enumerate(self.bars))
        result = None
        if complete:
            result = Candle(start, end, self.bars[0].open, max(b.high for b in self.bars),
                            min(b.low for b in self.bars), bar.close,
                            sum(b.volume for b in self.bars))
        else:
            self.discarded_buckets += 1
        self.bars = []
        return result
