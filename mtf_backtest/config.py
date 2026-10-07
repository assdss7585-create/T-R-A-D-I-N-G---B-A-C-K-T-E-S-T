"""Unspecified strategy choices are REQUIRED, never silently defaulted."""
import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from zoneinfo import ZoneInfo

POLICIES = {
    "structural_break_mode": {"once_per_pivot", "every_qualifying_close"},
    "h4_origin": {"last_confirmed_opposite_pivot"},
    "h4_range_end": {"freeze_at_bos", "extend_until_zone"},
    "zone_detection": {"range_overlap", "close_inside"},
    "zone_midpoint": {"include", "exclude"},
    "choch_timing": {"later_candle", "zone_candle_close"},
    "fib_origin": {"last_confirmed_opposite_pivot", "last_candle_extreme"},
    "fib_end": {"freeze_at_choch", "extend_until_touch"},
    "correction_start": {"after_choch", "after_fib_extreme"},
    "touch_extreme_ties": {"allow_equal", "strict"},
    "failed_first_touch": {"cancel_setup", "seek_next_eligible"},
    "post_touch_extreme": {"keep_first", "cancel_setup", "replace_if_retouch"},
    "setups_per_bos": {"one", "repeat"},
    "new_bos_pending": {"cancel", "keep_same_direction"},
    "concurrent_positions": {"allow", "block"},
    "gap_execution": {"open_price", "mark_unresolved"},
}


@dataclass
class Config:
    timezone: str = "UTC"
    source_timezone: str = "UTC"
    timestamp_label: str = "open"
    h4_anchor_minutes: int = 0
    data_gaps: str = "error"
    risk_reward: float = 2.0
    entry_mode: str = "confirmation_close"
    stop_mode: str = "touch_extreme"
    stop_buffer: float | None = None
    structural_break_mode: str | None = None
    h4_origin: str | None = None
    h4_range_end: str | None = None
    zone_detection: str | None = None
    zone_midpoint: str | None = None
    choch_timing: str | None = None
    fib_origin: str | None = None
    fib_end: str | None = None
    correction_start: str | None = None
    touch_extreme_ties: str | None = None
    failed_first_touch: str | None = None
    post_touch_extreme: str | None = None
    setups_per_bos: str | None = None
    new_bos_pending: str | None = None
    concurrent_positions: str | None = None
    gap_execution: str | None = None
    profile_label: str = "UNRESOLVED: user decisions required"

    def validate(self):
        missing = [k for k in POLICIES if getattr(self, k) is None]
        if self.stop_buffer is None:
            missing.append("stop_buffer (positive absolute price distance)")
        if missing:
            raise ValueError("Unresolved strategy choices: " + ", ".join(missing)
                             + ". See docs/DECISIONS_AR.md; demo choices are not your final rules.")
        for key, options in POLICIES.items():
            if getattr(self, key) not in options:
                raise ValueError(f"{key} must be one of {sorted(options)}")
        if not math.isfinite(self.risk_reward) or self.risk_reward <= 0:
            raise ValueError("risk_reward must be positive and finite")
        if not math.isfinite(self.stop_buffer) or self.stop_buffer <= 0:
            raise ValueError("stop_buffer must be > 0 (below / above, not at the candle extreme)")
        if self.entry_mode not in {"confirmation_close", "next_open"}:
            raise ValueError("entry_mode: confirmation_close or next_open; limit entry is not implemented")
        if self.stop_mode != "touch_extreme":
            raise ValueError("Only the requested experimental touch_extreme stop is implemented")
        if self.timestamp_label not in {"open", "close"}:
            raise ValueError("timestamp_label must be open or close")
        if self.data_gaps not in {"error", "allow"}:
            raise ValueError("data_gaps must be error or allow")
        if not isinstance(self.h4_anchor_minutes, int) or self.h4_anchor_minutes % 15:
            raise ValueError("h4_anchor_minutes must be an integer multiple of 15")
        ZoneInfo(self.timezone)
        ZoneInfo(self.source_timezone)
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_file(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        return cls(**raw).validate()
