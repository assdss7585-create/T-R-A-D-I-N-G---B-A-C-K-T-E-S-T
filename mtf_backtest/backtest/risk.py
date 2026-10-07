def levels(direction, entry, touch, config):
    long = direction == "LONG"
    stop = touch.low - config.stop_buffer if long else touch.high + config.stop_buffer
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        raise ValueError("Entry has zero/negative risk relative to the selected stop")
    target = entry + risk * config.risk_reward if long else entry - risk * config.risk_reward
    return stop, target


def evaluate_exit(trade, bar, config):
    """Open gaps have known ordering; otherwise dual touches are unresolved.

    available_at timestamps denote observation, not an invented intrabar time.
    Entry-close trades may only be evaluated on later candles.
    """
    if bar.timestamp < trade.entry_time:
        return None
    long = trade.direction == "LONG"
    gap_stop = bar.open <= trade.stop_loss if long else bar.open >= trade.stop_loss
    gap_target = bar.open >= trade.take_profit if long else bar.open <= trade.take_profit
    if gap_stop or gap_target:
        if config.gap_execution == "mark_unresolved":
            return "GAP_UNRESOLVED", None, None, bar.timestamp
        price = bar.open
        r = (price - trade.entry_price) / trade.risk * (1 if long else -1)
        return ("WIN" if r > 0 else "LOSS"), price, r, bar.timestamp
    stop_hit = bar.low <= trade.stop_loss if long else bar.high >= trade.stop_loss
    target_hit = bar.high >= trade.take_profit if long else bar.low <= trade.take_profit
    if stop_hit and target_hit:
        return "AMBIGUOUS_INTRABAR", None, None, bar.available_at
    if stop_hit:
        return "LOSS", trade.stop_loss, -1.0, bar.available_at
    if target_hit:
        return "WIN", trade.take_profit, trade.risk_reward, bar.available_at
    return None
