"""Engineered price paths for correctness tests, NEVER market performance."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from .config import Config
from .data.csv_loader import write_csv
from .models import Candle


def demo_config():
    return Config(
        profile_label="SYNTHETIC DEMO ONLY — provisional choices, not approved strategy rules",
        stop_buffer=0.1, structural_break_mode="once_per_pivot",
        h4_origin="last_confirmed_opposite_pivot", h4_range_end="freeze_at_bos",
        zone_detection="range_overlap", zone_midpoint="include", choch_timing="later_candle",
        fib_origin="last_confirmed_opposite_pivot", fib_end="freeze_at_choch",
        correction_start="after_choch", touch_extreme_ties="allow_equal",
        failed_first_touch="cancel_setup", post_touch_extreme="keep_first",
        setups_per_bos="one", new_bos_pending="cancel", concurrent_positions="allow",
        gap_execution="open_price").validate()


def synthetic(direction="LONG", outcome="WIN"):
    if direction not in {"LONG", "SHORT"} or outcome not in {"WIN", "LOSS", "AMBIGUOUS_INTRABAR"}:
        raise ValueError("Unknown synthetic scenario")
    start = datetime(2025, 1, 6, tzinfo=timezone.utc)
    bars = []
    blocks = [(100, 102, 98, 100), (100, 104, 99, 102), (102, 110, 101, 105),
              (105, 106, 99, 101), (101, 103, 96, 99), (99, 102, 90, 96),
              (96, 106, 95, 103), (103, 109, 98, 106), (106, 116, 104, 114)]
    def add(o, h, l, c):
        stamp = start + timedelta(minutes=15*len(bars))
        bars.append(Candle(stamp, stamp+timedelta(minutes=15), o, h, l, c, 100))
    for op, hi, lo, cl in blocks:
        previous = op
        for j in range(16):
            close = op + (cl-op)*(j+1)/16
            high, low = max(previous, close)+.02, min(previous, close)-.02
            if j == 4:
                high = hi
            if j == 9:
                low = lo
            add(previous, high, low, close)
            previous = close
    path = [(114,115,103.5,104), (104,106,101,102), (102,105,99,103),
            (103,108,102,106), (106,106.5,100,102), (102,105,98,100),
            (100,106,99,104), (104,112,102,111), (111,111.5,106,107),
            (107,108,103,104), (104,110,104,109)]
    for values in path:
        add(*values)
    if outcome == "WIN":
        add(109,122,108,121)
    elif outcome == "LOSS":
        add(109,110,102,103)
    else:
        add(109,123,102,110)
    for _ in range(4):
        close = bars[-1].close
        add(close, close+.2, close-.2, close)
    if direction == "SHORT":
        bars = [Candle(b.timestamp, b.available_at, 300-b.open, 300-b.low,
                       300-b.high, 300-b.close, b.volume) for b in bars]
    return bars


def generate(root):
    root = Path(root)
    (root/"data").mkdir(parents=True, exist_ok=True)
    (root/"configs").mkdir(parents=True, exist_ok=True)
    (root/"configs/demo.json").write_text(json.dumps(demo_config().to_dict(), indent=2)+"\n", encoding="utf-8")
    (root/"configs/strategy.unresolved.json").write_text(json.dumps(Config().to_dict(), indent=2)+"\n", encoding="utf-8")
    scenarios = [("long_win", "LONG", "WIN"), ("short_win", "SHORT", "WIN"),
                 ("long_loss", "LONG", "LOSS"), ("short_loss", "SHORT", "LOSS"),
                 ("long_ambiguous", "LONG", "AMBIGUOUS_INTRABAR"),
                 ("short_ambiguous", "SHORT", "AMBIGUOUS_INTRABAR")]
    for name, direction, outcome in scenarios:
        write_csv(root/"data"/f"{name}.csv", synthetic(direction, outcome))
    return scenarios
