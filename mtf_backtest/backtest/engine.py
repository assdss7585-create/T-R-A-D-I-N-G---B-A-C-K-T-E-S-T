from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

from ..config import Config
from ..data.csv_loader import validate_candles
from ..data.resample import FourHourAggregator
from ..models import Trade
from ..structure.market import MarketStructure
from ..strategy.entry import Setup, update_confirmation
from ..strategy.fibonacci import select_leg
from .risk import evaluate_exit, levels


def serial(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


class BacktestEngine:
    """One pass over closed 15m candles. No full-frame shift or future indexing."""
    def __init__(self, config: Config):
        self.config = deepcopy(config).validate()
        self.aggregator = FourHourAggregator(config)
        self.h4 = MarketStructure(config.structural_break_mode)
        self.m15 = MarketStructure(config.structural_break_mode)
        self.history, self.h4_history = [], []
        self.trades, self.events = [], []
        self.setup = None
        self.pending_entry = None
        self.setup_counter = 0
        self.direction = None
        self.context = None
        self.used = False

    def log(self, time, event, setup=None, **details):
        self.events.append(serial({"time": time, "event": event,
                                   "setup_id": setup.setup_id if setup else None, **details}))

    def _new_setup(self, context):
        self.setup_counter += 1
        return Setup(self.setup_counter, context["direction"], context["bos_time"],
                     context["low"], context["high"])

    def _h4_update(self, h4_bar):
        self.h4_history.append(h4_bar)
        pivots, breaks = self.h4.update(h4_bar)
        for p in pivots:
            self.log(h4_bar.available_at, "PIVOT_4H_CONFIRMED", pivot=asdict(p))
        for event in breaks:
            self.direction = event.direction
            keep = (self.config.new_bos_pending == "keep_same_direction" and self.setup
                    and self.setup.stage != "DONE" and self.setup.direction == event.direction)
            if not keep and self.setup and self.setup.stage != "DONE":
                self.log(event.time, "SETUP_CANCELLED_NEW_BOS", self.setup)
            if not keep:
                self.setup = None
            if event.origin is None:
                self.context = None
                self.log(event.time, "BOS_WITHOUT_CONFIRMED_ORIGIN", direction=event.direction)
                continue
            leg = [b for b in self.h4_history if b.timestamp >= event.origin.timestamp]
            low = event.origin.price if event.direction == "LONG" else min(b.low for b in leg)
            high = max(b.high for b in leg) if event.direction == "LONG" else event.origin.price
            self.context = {"direction": event.direction, "bos_time": event.time,
                            "low": low, "high": high}
            if not keep:
                self.setup = self._new_setup(self.context)
            self.log(event.time, "BOS_4H_DETECTED", self.setup, direction=event.direction,
                     broken_swing=asdict(event.broken), origin=asdict(event.origin),
                     range_low=low, range_high=high)
        # Range updates are handled AFTER lower timeframe evaluation below.

    def _extend_h4_range(self, bar):
        s = self.setup
        if (s and s.stage == "WAIT_ZONE" and self.config.h4_range_end == "extend_until_zone"
                and bar.available_at > s.bos_time):
            old = (s.range_low, s.range_high)
            if s.direction == "LONG":
                s.range_high = max(s.range_high, bar.high)
            else:
                s.range_low = min(s.range_low, bar.low)
            if old != (s.range_low, s.range_high):
                self.log(bar.available_at, "DEALING_RANGE_EXTENDED", s,
                         range_low=s.range_low, range_high=s.range_high)

    def _enter(self, s, price, time):
        if self.config.concurrent_positions == "block" and any(t.result == "OPEN" for t in self.trades):
            self.log(time, "ENTRY_BLOCKED_OPEN_POSITION", s)
            return
        try:
            stop, target = levels(s.direction, price, s.touch, self.config)
        except ValueError as exc:
            self.log(time, "ENTRY_REJECTED_INVALID_RISK", s, reason=str(exc))
            return
        t = Trade(len(self.trades) + 1, s.setup_id, s.direction, s.bos_time,
                  "BULLISH" if s.direction == "LONG" else "BEARISH", s.zone_time,
                  s.choch_time, s.leg.start, s.leg.end, s.leg.level, s.leg.start_time,
                  s.leg.end_time, s.touch.timestamp, s.touch.high, s.touch.low,
                  s.confirmation.available_at, time, price, stop, target, self.config.risk_reward)
        self.trades.append(t)
        self.log(time, "ENTRY", s, trade_id=t.trade_id, entry_price=price,
                 stop_loss=stop, take_profit=target, risk_reward=t.risk_reward)

    def _exits(self, bar):
        for t in self.trades:
            if t.result != "OPEN":
                continue
            resolution = evaluate_exit(t, bar, self.config)
            if resolution:
                t.result, t.exit_price, t.R_multiple, t.exit_time = resolution
                self.log(t.exit_time, "EXIT", trade_id=t.trade_id, trade_setup_id=t.setup_id,
                         result=t.result, exit_price=t.exit_price, R_multiple=t.R_multiple)

    def run(self, candles, on_close=None):
        if self.used:
            raise ValueError("Use a fresh BacktestEngine for each run")
        self.used = True
        validate_candles(candles, self.config.data_gaps)
        for bar in candles:
            # Open-next orders were committed at the preceding close. Their
            # entry at this open precedes every current-close structural event.
            if self.pending_entry is not None:
                self._enter(self.pending_entry, bar.open, bar.timestamp)
                self.pending_entry = None
            self._exits(bar)
            self.history.append(bar)
            h4_bar = self.aggregator.update(bar)
            if h4_bar:
                self._h4_update(h4_bar)
            pivots, breaks = self.m15.update(bar)
            for p in pivots:
                self.log(bar.available_at, "PIVOT_15M_CONFIRMED", pivot=asdict(p))
            s = self.setup
            if s and s.stage != "DONE" and bar.timestamp >= s.bos_time:
                self._step_setup(s, bar, breaks)
            if h4_bar:
                self._extend_h4_range(h4_bar)
            if on_close is not None:
                on_close(self, bar)
        return self

    def _step_setup(self, s, bar, breaks):
        if s.stage == "WAIT_ZONE":
            if not s.inside_zone(bar, self.config):
                return
            s.zone_time = bar.available_at
            s.stage = "WAIT_CHOCH"
            self.log(bar.available_at, "ZONE_ENTERED", s,
                     zone="DISCOUNT" if s.direction == "LONG" else "PREMIUM",
                     range_low=s.range_low, range_high=s.range_high,
                     midpoint=(s.range_low+s.range_high)/2)
            if self.config.choch_timing == "later_candle":
                return
        if s.stage == "WAIT_CHOCH":
            matching = [b for b in breaks if b.direction == s.direction]
            if not matching:
                return
            event = matching[0]
            self.log(bar.available_at, "CHOCH_15M_DETECTED", s,
                     broken_swing=asdict(event.broken))
            leg = select_leg(s.direction, event.origin, self.history, self.config)
            if leg is None:
                self.log(bar.available_at, "CHOCH_WITHOUT_VALID_ORIGIN", s)
                return
            s.leg, s.choch_time, s.stage = leg, bar.available_at, "WAIT_TOUCH_CONFIRM"
            if self.config.correction_start == "after_fib_extreme":
                correction = [b for b in self.history if b.timestamp > leg.end_time]
                if correction:
                    s.correction_extreme = (min(b.low for b in correction) if s.direction == "LONG"
                                            else max(b.high for b in correction))
            self.log(bar.available_at, "FIB_LEG_SELECTED", s, fib_start=leg.start,
                     fib_end=leg.end, fib_start_time=leg.start_time, fib_end_time=leg.end_time)
            self.log(bar.available_at, "FIB_0618_CALCULATED", s, fib_0618=leg.level)
            return
        if s.stage == "WAIT_TOUCH_CONFIRM":
            events, confirmed = update_confirmation(s, bar, self.config)
            for name, details in events:
                self.log(bar.available_at, name, s, **details)
            if confirmed:
                if self.config.entry_mode == "confirmation_close":
                    self._enter(s, bar.close, bar.available_at)
                else:
                    self.pending_entry = deepcopy(s)
                    self.log(bar.available_at, "NEXT_OPEN_ORDER_QUEUED", s)
                s.stage = "DONE"
                if self.config.setups_per_bos == "repeat":
                    self.setup = self._new_setup({"direction": s.direction, "bos_time": s.bos_time,
                                                  "low": s.range_low, "high": s.range_high})

    def snapshot(self):
        """Canonical state for prefix invariance/replay tests, no EOD settlement."""
        return serial({"trades": [asdict(t) for t in self.trades], "events": self.events,
                       "setup": asdict(self.setup) if self.setup else None,
                       "pending_entry": asdict(self.pending_entry) if self.pending_entry else None})
