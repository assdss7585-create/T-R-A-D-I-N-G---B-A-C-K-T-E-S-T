import csv
import hashlib
import html
import json
import platform
from dataclasses import asdict, fields
from pathlib import Path

from .. import __version__
from ..backtest.engine import serial
from ..models import Trade
from .statistics import statistics


def debug_trade(engine, trade_id):
    trade = next((t for t in engine.trades if t.trade_id == trade_id), None)
    if trade is None:
        raise ValueError(f"Trade {trade_id} does not exist")
    selected = [e for e in engine.events if e.get("setup_id") == trade.setup_id
                or e.get("trade_id") == trade_id]
    lines = [f"Trade #{trade_id}: {trade.direction} / {trade.result}",
             f"Profile: {engine.config.profile_label}"]
    for e in selected:
        detail = {k: v for k, v in e.items() if k not in {"time", "event", "setup_id"}}
        lines.append(f"{e['time']} | {e['event']} | {json.dumps(detail, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def export_run(engine, output, source_path=None, chart_ids=()):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "trades.csv").open("w", newline="", encoding="utf-8-sig") as file:
        names = [f.name for f in fields(Trade)]
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        writer.writerows(serial(asdict(t)) for t in engine.trades)
    stats = statistics(engine.trades)
    manifest = {
        "engine_version": __version__, "python": platform.python_version(),
        "config": engine.config.to_dict(),
        "data_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest() if source_path else None,
        "base_candles": len(engine.history), "complete_4h_candles": len(engine.h4_history),
        "discarded_incomplete_4h": engine.aggregator.discarded_buckets,
        "unfinished_4h_bars": len(engine.aggregator.bars),
        "first_open": engine.history[0].timestamp.isoformat(),
        "last_close": engine.history[-1].available_at.isoformat(),
        "pending_next_open_order": engine.pending_entry is not None,
        "timestamps": "UTC ISO 8601; candle times=open, decision times=close; gap exit time=open",
        "warning": "Research simulation. Demo choices are not approved strategy rules. Synthetic results are not performance evidence.",
    }
    for filename, value in (("summary.json", stats), ("run_manifest.json", manifest)):
        (output / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                                 allow_nan=False) + "\n", encoding="utf-8")
    (output / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                                 for e in engine.events), encoding="utf-8")
    for t in engine.trades:
        (output / f"debug_trade_{t.trade_id}.txt").write_text(debug_trade(engine, t.trade_id), encoding="utf-8")
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
                   for k, v in stats.items() if k not in {"metric_scope", "ordering"})
    links = ""
    for t in engine.trades:
        chart = f' · <a href="trade_{t.trade_id}.svg">Chart</a>' if t.trade_id in chart_ids else ''
        links += (f'<li>#{t.trade_id} {t.direction} — {t.result}: '
                  f'<a href="debug_trade_{t.trade_id}.txt">Debug</a>{chart}</li>')
    doc = f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
<title>تقرير اختبار الاستراتيجية</title><style>
body{{font:17px system-ui;max-width:1000px;margin:35px auto;padding:24px;background:#f3f6fa;color:#172638}}
table{{width:100%;border-collapse:collapse;direction:ltr;background:white}}td{{padding:9px;border-bottom:1px solid #dce3eb}}
h1{{color:#146d71}}a{{color:#09648e}}pre{{direction:ltr;text-align:left;white-space:pre-wrap;background:#fff;padding:20px}}
.note{{background:#fff2ca;padding:16px;border-radius:8px}}</style>
<h1>اختبار 4H → 15m</h1><p class="note">{html.escape(engine.config.profile_label)}<br>
الإعدادات التجريبية ليست قواعد نهائية معتمدة. النتائج المصطنعة لفحص المنطق فقط.</p>
<p>المؤشرات مبنية على الصفقات المحسومة فقط؛ الصفقات الغامضة والمفتوحة مستبعدة من الربح والخسارة.
الأرقام بوحدة R قبل الرسوم والسبريد والانزلاق. السحب الأقصى محسوب من النتائج المحققة.</p>
<table>{rows}</table><h2>الصفقات</h2><ul>{links}</ul>
<p><a href="trades.csv">سجل الصفقات</a> · <a href="events.jsonl">سجل الأحداث</a> ·
<a href="run_manifest.json">الإعدادات وهوية البيانات</a></p>
<details><summary>الإعدادات الفعلية</summary><pre>{html.escape(json.dumps(engine.config.to_dict(), indent=2))}</pre></details></html>'''
    (output / "report.html").write_text(doc, encoding="utf-8")
    return stats
