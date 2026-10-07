"""Dependency-free SVG candlestick plots; exact values, no charting service."""
import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def plot_trade(candles, trade, path, timezone="UTC", padding=12):
    zone = ZoneInfo(timezone)
    left_time = min(trade.fib_start_time, trade.touch_candle_time)
    right_time = trade.exit_time or trade.entry_time
    indices = [i for i, b in enumerate(candles) if b.available_at >= left_time and b.timestamp <= right_time]
    if not indices:
        raise ValueError("No candles in trade range")
    selected = candles[max(0, indices[0]-padding):min(len(candles), indices[-1]+padding+1)]
    width, height = 1400, 820
    x0, y0, pw, ph = 95, 105, 1040, 585
    lo = min(min(b.low for b in selected), trade.stop_loss, trade.take_profit)
    hi = max(max(b.high for b in selected), trade.stop_loss, trade.take_profit)
    margin = (hi - lo) * .08 or 1
    lo, hi = lo-margin, hi+margin
    def y(price): return y0 + (hi-price)/(hi-lo)*ph
    def x(i): return x0+(i+.5)*pw/len(selected)
    def at(time, decision=False):
        if decision:
            found = [i for i, b in enumerate(selected) if b.available_at == time]
        else:
            found = [i for i, b in enumerate(selected) if b.timestamp == time]
        return x(found[0]) if found else None
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#101d2c"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#d9e4ef} .small{font-size:12px}</style>',
             f'<text x="30" y="35" font-size="23">Trade #{trade.trade_id} · {trade.direction} · 4H {trade.direction_4h} · {trade.result}</text>',
             f'<text x="30" y="62" font-size="15">BOS {trade.bos_time_4h.astimezone(zone).isoformat()} | RR 1:{trade.risk_reward:g} | {html.escape(timezone)}</text>']
    for j in range(9):
        price = lo+(hi-lo)*j/8
        parts.append(f'<line x1="{x0}" y1="{y(price)}" x2="{x0+pw}" y2="{y(price)}" stroke="#263748"/>')
        parts.append(f'<text x="8" y="{y(price)+4}" class="small">{price:.5f}</text>')
    body_width = max(1, min(12, pw/len(selected)*.62))
    for i, b in enumerate(selected):
        color = "#35d0a3" if b.close >= b.open else "#ed7885"
        parts.append(f'<line x1="{x(i)}" y1="{y(b.high)}" x2="{x(i)}" y2="{y(b.low)}" stroke="{color}"/>')
        parts.append(f'<rect x="{x(i)-body_width/2}" y="{y(max(b.open,b.close))}" width="{body_width}" height="{max(1,abs(y(b.close)-y(b.open)))}" fill="{color}"/>')
        if i % max(1, len(selected)//9) == 0:
            stamp = b.timestamp.astimezone(zone).strftime("%m-%d %H:%M")
            parts.append(f'<text x="{x(i)-30}" y="{y0+ph+25}" class="small">{stamp}</text>')
    price_labels = []
    for label, value, color in (("Fib 0.618", trade.fib_0618, "#c69cfa"),
                                ("Entry", trade.entry_price, "#70bbff"),
                                ("Stop Loss", trade.stop_loss, "#ff6678"),
                                ("Take Profit", trade.take_profit, "#5cdea4")):
        parts.append(f'<line x1="{x0}" y1="{y(value)}" x2="{x0+pw}" y2="{y(value)}" stroke="{color}" stroke-dasharray="6 4"/>')
        price_labels.append((y(value), label, value, color))
    previous_y = -1000
    for yy, label, value, color in sorted(price_labels):
        label_y = max(yy, previous_y + 21)
        parts.append(f'<path d="M {x0+pw} {yy} L {x0+pw+10} {label_y}" fill="none" stroke="{color}"/>')
        parts.append(f'<text x="{x0+pw+14}" y="{label_y+4}" font-size="14" style="fill:{color}">{label} {value:.5f}</text>')
        previous_y = label_y
    fs, fe = at(trade.fib_start_time), at(trade.fib_end_time)
    if fs is not None and fe is not None:
        parts.append(f'<line x1="{fs}" y1="{y(trade.fib_start)}" x2="{fe}" y2="{y(trade.fib_end)}" stroke="#f6d078" stroke-width="3"/>')
        for xx, val in ((fs, trade.fib_start), (fe, trade.fib_end)):
            parts.append(f'<circle cx="{xx}" cy="{y(val)}" r="5" fill="#f6d078"/>')
    markers = [("CHOCH", trade.choch_time_15m, True, "#f6d078"),
               ("Touch", trade.touch_candle_time, False, "#c69cfa"),
               ("Confirm", trade.confirmation_time, True, "#70bbff")]
    for j, (label, time, decision, color) in enumerate(markers):
        xx = at(time, decision)
        if xx is not None:
            parts.append(f'<line x1="{xx}" y1="{y0}" x2="{xx}" y2="{y0+ph}" stroke="{color}" opacity=".5" stroke-dasharray="3 5"/>')
            parts.append(f'<text x="{xx+4}" y="{y0+17+j*18}" font-size="13" style="fill:{color}">{label}</text>')
    parts.append('<text x="95" y="766" font-size="14">Gold diagonal: selected impulse leg | Vertical markers identify actual candles | X axis: candle-open time</text>')
    parts.append('<text x="95" y="790" font-size="13">Synthetic/demo profiles validate code only. Gross R excludes trading costs. Unresolved trades have no assigned P/L.</text></svg>')
    Path(path).write_text("\n".join(parts), encoding="utf-8")
    return Path(path)
