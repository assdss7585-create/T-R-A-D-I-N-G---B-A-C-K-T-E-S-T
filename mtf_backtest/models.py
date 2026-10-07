from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class Candle:
    """timestamp is the candle OPEN; available_at is its CLOSE, both UTC."""
    timestamp: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Pivot:
    kind: str
    price: float
    timestamp: datetime
    confirmed_at: datetime


@dataclass(frozen=True)
class Break:
    direction: Direction
    time: datetime
    broken: Pivot
    origin: Pivot | None


@dataclass
class Trade:
    trade_id: int
    setup_id: int
    direction: Direction
    bos_time_4h: datetime
    direction_4h: str
    zone_entry_time: datetime
    choch_time_15m: datetime
    fib_start: float
    fib_end: float
    fib_0618: float
    fib_start_time: datetime
    fib_end_time: datetime
    touch_candle_time: datetime
    touch_candle_high: float
    touch_candle_low: float
    confirmation_time: datetime
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    result: str = "OPEN"
    R_multiple: float | None = None

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)
