from collections import Counter


def statistics(trades):
    counts = Counter(t.result for t in trades)
    # Realized sequence uses EXIT observation time, not entry time. Same-time
    # exits form one equity point; streaks use trade_id as a disclosed tie-break.
    resolved = sorted((t for t in trades if t.result in {"WIN", "LOSS"}),
                      key=lambda t: (t.exit_time, t.trade_id))
    winners = [t.R_multiple for t in resolved if t.R_multiple > 0]
    losers = [t.R_multiple for t in resolved if t.R_multiple < 0]
    gains, losses = sum(winners), -sum(losers)
    total = gains - losses
    equity = peak = max_dd = 0.0
    grouped = {}
    for t in resolved:
        grouped[t.exit_time] = grouped.get(t.exit_time, 0.0) + t.R_multiple
    for change in grouped.values():
        equity += change
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    max_wins = max_losses = win_streak = loss_streak = 0
    for t in resolved:
        if t.R_multiple > 0:
            win_streak, loss_streak = win_streak + 1, 0
        else:
            loss_streak, win_streak = loss_streak + 1, 0
        max_wins, max_losses = max(max_wins, win_streak), max(max_losses, loss_streak)
    # JSON-safe string instead of a non-standard Infinity numeric literal.
    pf = gains / losses if losses else ("Infinity" if gains else None)
    return {
        "total_trades": len(trades), "resolved_trades": len(resolved),
        "wins": len(winners), "losses": len(losers),
        "win_rate_pct": 100 * len(winners) / len(resolved) if resolved else None,
        "profit_factor": pf, "expectancy_r": total / len(resolved) if resolved else None,
        "total_r": total, "average_winner_r": gains / len(winners) if winners else None,
        "average_loser_r": -losses / len(losers) if losers else None,
        "max_drawdown_r": max_dd, "maximum_consecutive_wins": max_wins,
        "maximum_consecutive_losses": max_losses,
        "long_trades": sum(t.direction == "LONG" for t in trades),
        "short_trades": sum(t.direction == "SHORT" for t in trades),
        "ambiguous_intrabar": counts["AMBIGUOUS_INTRABAR"],
        "gap_unresolved": counts["GAP_UNRESOLVED"], "open_trades": counts["OPEN"],
        "metric_scope": "Resolved trades only; gross R; no fees/spread/slippage; realized-equity drawdown",
        "ordering": "Exit observation time; simultaneous exits grouped for drawdown; trade_id breaks streak ties",
    }
