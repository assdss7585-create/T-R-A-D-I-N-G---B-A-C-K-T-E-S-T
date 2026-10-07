import argparse
import json
import sys
from pathlib import Path

from .backtest.engine import BacktestEngine
from .config import Config, POLICIES
from .data.csv_loader import load_csv
from .demo import generate
from .reports.export import debug_trade, export_run
from .reports.plot import plot_trade


def run(csv_path, config_path, output, plot_id=None, debug_id=None, all_charts=False):
    config = Config.from_file(config_path)
    candles = load_csv(csv_path, config)
    engine = BacktestEngine(config).run(candles)
    Path(output).mkdir(parents=True, exist_ok=True)
    chart_ids = [t.trade_id for t in engine.trades] if all_charts else ([plot_id] if plot_id else [])
    if all_charts:
        for trade in engine.trades:
            plot_trade(candles, trade, Path(output)/f"trade_{trade.trade_id}.svg", config.timezone)
    elif plot_id is not None:
        trade = next((t for t in engine.trades if t.trade_id == plot_id), None)
        if trade is None:
            raise ValueError(f"Trade {plot_id} does not exist")
        plot_trade(candles, trade, Path(output)/f"trade_{plot_id}.svg", config.timezone)
    stats = export_run(engine, output, csv_path, chart_ids)
    if debug_id is not None:
        print(debug_trade(engine, debug_id))
    print(json.dumps(stats, indent=2, ensure_ascii=False, allow_nan=False))
    return engine


def main(argv=None):
    parser = argparse.ArgumentParser(description="Causal 4H / 15m strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Generate and run synthetic scenarios")
    demo.add_argument("--root", default=".")
    test = sub.add_parser("run", help="Backtest a 15m OHLCV CSV")
    test.add_argument("--csv", required=True)
    test.add_argument("--config", required=True)
    test.add_argument("--out", required=True)
    test.add_argument("--debug-trade", type=int)
    test.add_argument("--plot-trade", type=int)
    test.add_argument("--all-charts", action="store_true")
    sub.add_parser("choices", help="List unresolved policy settings and supported values")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            root = Path(args.root)
            for name, _, _ in generate(root):
                print(f"\nSYNTHETIC SCENARIO: {name}")
                run(root/"data"/f"{name}.csv", root/"configs/demo.json", root/"outputs"/name,
                    all_charts=True)
        elif args.command == "choices":
            print(json.dumps({key: sorted(value) for key, value in POLICIES.items()}, indent=2))
        else:
            run(args.csv, args.config, args.out, args.plot_trade, args.debug_trade, args.all_charts)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
