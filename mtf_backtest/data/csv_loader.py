import csv
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..models import Candle

STEP = timedelta(minutes=15)


def parse_timestamp(value, source_timezone):
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        zone = ZoneInfo(source_timezone)
        first, second = dt.replace(tzinfo=zone, fold=0), dt.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("Ambiguous/nonexistent DST timestamp: provide an explicit UTC offset")
        if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != dt:
            raise ValueError("Nonexistent local timestamp")
        dt = first
    return dt.astimezone(timezone.utc)


def validate_candles(candles, data_gaps="error"):
    if not candles:
        raise ValueError("No candles")
    previous = None
    for c in candles:
        if c.timestamp.tzinfo is None or c.available_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone aware")
        if c.available_at - c.timestamp != STEP:
            raise ValueError("Base candles must be exactly 15 minutes")
        if c.timestamp.second or c.timestamp.microsecond or c.timestamp.minute % 15:
            raise ValueError("Candle timestamp must be on a 15 minute boundary")
        values = [c.open, c.high, c.low, c.close, c.volume]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Non-finite OHLCV")
        if c.low > min(c.open, c.close) or c.high < max(c.open, c.close) or c.low > c.high:
            raise ValueError("Inconsistent OHLC")
        if c.volume < 0:
            raise ValueError("Negative volume")
        if previous:
            if c.timestamp <= previous.timestamp:
                raise ValueError("Duplicate or unsorted timestamps; input is not silently sorted")
            if c.timestamp != previous.available_at and data_gaps == "error":
                raise ValueError("Missing 15m candles; explicitly set data_gaps=allow to accept market closures/gaps")
        previous = c


def load_csv(path, config):
    candles = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Required columns: {sorted(required)}")
        for row_number, row in enumerate(reader, 2):
            try:
                stamp = parse_timestamp(row["timestamp"], config.source_timezone)
                if config.timestamp_label == "close":
                    stamp -= STEP
                candles.append(Candle(stamp, stamp + STEP, *(float(row[k]) for k in
                                      ("open", "high", "low", "close", "volume"))))
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"CSV row {row_number}: {exc}") from exc
    validate_candles(candles, config.data_gaps)
    return candles


def write_csv(path, candles):
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume])
