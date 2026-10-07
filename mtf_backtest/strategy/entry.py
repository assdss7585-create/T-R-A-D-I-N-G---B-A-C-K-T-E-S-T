from dataclasses import dataclass
from datetime import datetime

from ..models import Candle
from .fibonacci import FibLeg


@dataclass
class Setup:
    setup_id: int
    direction: str
    bos_time: datetime
    range_low: float
    range_high: float
    stage: str = "WAIT_ZONE"
    zone_time: datetime | None = None
    choch_time: datetime | None = None
    leg: FibLeg | None = None
    correction_extreme: float | None = None
    touch: Candle | None = None
    confirmation: Candle | None = None

    def inside_zone(self, bar, config):
        mid = (self.range_low + self.range_high) / 2
        lower, upper = ((self.range_low, mid) if self.direction == "LONG"
                        else (mid, self.range_high))
        if config.zone_detection == "close_inside":
            hit = lower <= bar.close <= upper
            midpoint_only = bar.close == mid
        else:
            hit = bar.high >= lower and bar.low <= upper
            midpoint_only = bar.low == mid if self.direction == "LONG" else bar.high == mid
        return hit and not (config.zone_midpoint == "exclude" and midpoint_only)


def update_confirmation(setup, bar, config):
    """Only called AFTER the CHOCH candle. Returns audit events and a signal.

    On extending a fib high/low and a possible touch in the same OHLC bar,
    order is unknowable: terminate as an unresolved setup, never infer order.
    """
    events = []
    long = setup.direction == "LONG"
    leg = setup.leg
    if setup.touch is None and config.fib_end == "extend_until_touch":
        extends = bar.high > leg.end if long else bar.low < leg.end
        if extends:
            old_level = leg.level
            leg.end = bar.high if long else bar.low
            leg.end_time = bar.timestamp
            if bar.low <= leg.level <= bar.high or bar.low <= old_level <= bar.high:
                setup.stage = "DONE"
                return [("AMBIGUOUS_FIB_UPDATE_TOUCH", {"old_level": old_level,
                                                       "new_level": leg.level})], False
            setup.correction_extreme = None
            return [("FIB_EXTENDED", {"fib_end": leg.end, "fib_0618": leg.level})], False
    extreme = bar.low if long else bar.high
    prior = setup.correction_extreme
    eligible = prior is None or (extreme <= prior if long else extreme >= prior)
    if config.touch_extreme_ties == "strict" and prior is not None:
        eligible = extreme < prior if long else extreme > prior
    setup.correction_extreme = extreme if prior is None else (min(extreme, prior) if long else max(extreme, prior))
    touched = bar.low <= leg.level <= bar.high
    if setup.touch is None:
        if touched and eligible:
            setup.touch = bar
            events.append(("TOUCH_DETECTED", {"touch_time": bar.timestamp, "high": bar.high,
                                               "low": bar.low, "fib_0618": leg.level}))
        elif touched:
            events.append(("INELIGIBLE_FIRST_TOUCH", {"correction_extreme": prior}))
            if config.failed_first_touch == "cancel_setup":
                setup.stage = "DONE"
        return events, False  # the touch candle can NEVER confirm itself
    new_extreme = bar.low < setup.touch.low if long else bar.high > setup.touch.high
    if new_extreme:
        events.append(("POST_TOUCH_NEW_EXTREME", {"policy": config.post_touch_extreme}))
        if config.post_touch_extreme == "cancel_setup":
            setup.stage = "DONE"
            return events, False
        if config.post_touch_extreme == "replace_if_retouch":
            if touched and eligible:
                setup.touch = bar
                events.append(("TOUCH_REPLACED", {"touch_time": bar.timestamp,
                                                 "high": bar.high, "low": bar.low}))
            else:
                setup.stage = "DONE"
            return events, False
    confirmed = bar.close > setup.touch.high if long else bar.close < setup.touch.low
    if confirmed:
        setup.confirmation = bar
        events.append(("CONFIRMATION_DETECTED", {"price": bar.close}))
    return events, confirmed
