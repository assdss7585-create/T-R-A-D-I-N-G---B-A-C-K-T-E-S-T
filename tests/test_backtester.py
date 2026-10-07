import csv
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mtf_backtest.backtest.engine import BacktestEngine
from mtf_backtest.backtest.risk import evaluate_exit, levels
from mtf_backtest.config import Config
from mtf_backtest.data.csv_loader import load_csv, parse_timestamp, validate_candles, write_csv
from mtf_backtest.data.resample import FourHourAggregator
from mtf_backtest.demo import demo_config, synthetic
from mtf_backtest.models import Candle
from mtf_backtest.reports.export import debug_trade, export_run
from mtf_backtest.reports.plot import plot_trade
from mtf_backtest.reports.statistics import statistics
from mtf_backtest.strategy.entry import Setup, update_confirmation
from mtf_backtest.strategy.fibonacci import FibLeg
from mtf_backtest.structure.market import MarketStructure
from mtf_backtest.structure.pivots import PivotTracker

START = datetime(2025, 1, 6, tzinfo=timezone.utc)


def bar(i, high=105, low=95, close=100, op=None):
    stamp = START + timedelta(minutes=15*i)
    return Candle(stamp, stamp+timedelta(minutes=15), close if op is None else op, high, low, close, 100)


def engine(direction="LONG", outcome="WIN", config=None):
    return BacktestEngine(config or demo_config()).run(synthetic(direction, outcome))


class PivotAndStructureTests(unittest.TestCase):
    def test_pivot_waits_for_two_closed_right_candles(self):
        tracker = PivotTracker()
        bars = [bar(i, high=h) for i, h in enumerate([101, 102, 110, 103, 104])]
        for b in bars[:4]:
            self.assertEqual(tracker.update(b), [])
            self.assertIsNone(tracker.high)
        confirmed = tracker.update(bars[4])
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].timestamp, bars[2].timestamp)
        self.assertEqual(confirmed[0].confirmed_at, bars[4].available_at)

    def test_pivot_low_and_strict_ties(self):
        tracker = PivotTracker()
        for i, low in enumerate([95, 94, 90, 93, 92]):
            tracker.update(bar(i, low=low))
        self.assertEqual(tracker.low.price, 90)
        equal = PivotTracker()
        for i, high in enumerate([101, 110, 110, 103, 104]):
            equal.update(bar(i, high=high))
        self.assertIsNone(equal.high)

    def test_wick_and_equal_close_do_not_break(self):
        structure = MarketStructure()
        for i, high in enumerate([102, 105, 110, 108, 107]):
            structure.update(bar(i, high=high))
        self.assertEqual(structure.update(bar(5, high=112, close=109))[1], [])
        self.assertEqual(structure.update(bar(6, high=112, close=110))[1], [])
        breaks = structure.update(bar(7, high=113, close=111))[1]
        self.assertEqual([b.direction for b in breaks], ["LONG"])
        self.assertEqual(structure.update(bar(8, high=114, close=112))[1], [])

    def test_close_below_low_short(self):
        structure = MarketStructure()
        for i, low in enumerate([98, 95, 90, 94, 96]):
            structure.update(bar(i, low=low))
        self.assertEqual(structure.update(bar(5, low=89, close=91))[1], [])
        self.assertEqual(structure.update(bar(6, low=88, close=89))[1][0].direction, "SHORT")

    def test_unconfirmed_high_never_available(self):
        tracker = PivotTracker()
        for i, high in enumerate([102, 104, 110, 103, 111]):
            tracker.update(bar(i, high=high))
        self.assertIsNone(tracker.high)


class DataTests(unittest.TestCase):
    def test_h4_emits_only_after_sixteen_closes(self):
        agg = FourHourAggregator(demo_config())
        bars = synthetic()[:16]
        for b in bars[:15]:
            self.assertIsNone(agg.update(b))
        result = agg.update(bars[15])
        self.assertEqual(result.timestamp, START)
        self.assertEqual(result.available_at, START+timedelta(hours=4))
        self.assertEqual((result.open, result.high, result.low, result.close, result.volume),
                         (100, 102, 98, 100, 1600))

    def test_missing_candle_does_not_create_partial_h4(self):
        agg = FourHourAggregator(demo_config())
        bars = synthetic()[:16]
        results = [agg.update(b) for i, b in enumerate(bars) if i != 7]
        self.assertTrue(all(r is None for r in results))
        self.assertEqual(agg.discarded_buckets, 1)

    def test_partial_first_and_last_h4_discarded(self):
        agg = FourHourAggregator(demo_config())
        emitted = [r for b in synthetic()[5:31] if (r := agg.update(b))]
        self.assertEqual(emitted, [])
        self.assertEqual(len(agg.bars), 15)

    def test_timezone_changes_h4_alignment(self):
        config = demo_config()
        config.timezone = "Asia/Riyadh"
        agg = FourHourAggregator(config)
        self.assertEqual(agg.bucket(START), START-timedelta(hours=3))

    def test_timestamp_offset_normalization(self):
        expected = START
        self.assertEqual(parse_timestamp("2025-01-06T03:00:00+03:00", "UTC"), expected)
        self.assertEqual(parse_timestamp("2025-01-06T03:00:00", "Asia/Riyadh"), expected)

    def test_dst_ambiguous_and_nonexistent_naive_rejected(self):
        for value in ("2025-11-02T01:30:00", "2025-03-09T02:30:00"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "DST"):
                parse_timestamp(value, "America/New_York")

    def test_dst_aware_is_unambiguous(self):
        a = parse_timestamp("2025-11-02T01:30:00-04:00", "UTC")
        b = parse_timestamp("2025-11-02T01:30:00-05:00", "UTC")
        self.assertEqual(b-a, timedelta(hours=1))

    def test_csv_round_trip_and_close_timestamps(self):
        data = synthetic()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"prices.csv"
            write_csv(path, data)
            self.assertEqual(load_csv(path, demo_config()), data)
            config = demo_config()
            config.timestamp_label = "close"
            shifted = [replace(b, timestamp=b.timestamp+timedelta(minutes=15),
                               available_at=b.available_at+timedelta(minutes=15)) for b in data]
            write_csv(path, shifted)
            self.assertEqual(load_csv(path, config), data)

    def test_duplicate_unsorted_missing_and_nonfinite_rejected(self):
        cases = [[bar(0),bar(0)], [bar(1),bar(0)], [bar(0),bar(2)],
                 [replace(bar(0), close=float("nan"))], [replace(bar(0), low=101)],
                 [replace(bar(0), volume=-1)]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_candles(rows)
        validate_candles([bar(0),bar(2)], "allow")

    def test_required_csv_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"bad.csv"
            path.write_text("timestamp,close\n2025-01-06T00:00:00Z,100\n")
            with self.assertRaisesRegex(ValueError, "Required columns"):
                load_csv(path, demo_config())


class EntryTests(unittest.TestCase):
    def setup_leg(self, direction="LONG"):
        s = Setup(1, direction, START, 90, 120, "WAIT_TOUCH_CONFIRM")
        s.choch_time = START
        s.leg = FibLeg(direction, 98 if direction == "LONG" else 202,
                       112 if direction == "LONG" else 188, START, START)
        return s

    def test_fib_from_end_back_to_start(self):
        self.assertAlmostEqual(self.setup_leg().leg.level, 103.348)
        self.assertAlmostEqual(self.setup_leg("SHORT").leg.level, 196.652)

    def test_long_touch_cannot_confirm_itself(self):
        s = self.setup_leg()
        events, signal = update_confirmation(s, bar(1,high=108,low=103,close=107),demo_config())
        self.assertFalse(signal)
        self.assertEqual(events[0][0], "TOUCH_DETECTED")
        _, signal = update_confirmation(s, bar(2, high=109,low=104,close=108),demo_config())
        self.assertFalse(signal)
        _, signal = update_confirmation(s, bar(3, high=110,low=104,close=109),demo_config())
        self.assertTrue(signal)

    def test_short_confirmation_strict_close_not_wick(self):
        s = self.setup_leg("SHORT")
        _, signal = update_confirmation(s, bar(1,high=197,low=192,close=194,op=195),demo_config())
        self.assertFalse(signal)
        _, signal = update_confirmation(s, bar(2,high=196,low=190,close=192,op=193),demo_config())
        self.assertFalse(signal)
        _, signal = update_confirmation(s, bar(3,high=195,low=190,close=191,op=193),demo_config())
        self.assertTrue(signal)

    def test_first_touch_must_be_lowest_so_far(self):
        s = self.setup_leg()
        update_confirmation(s, bar(1,high=103,low=100,close=102),demo_config())
        events, signal = update_confirmation(s, bar(2,high=108,low=102,close=104),demo_config())
        self.assertFalse(signal)
        self.assertEqual(events[0][0], "INELIGIBLE_FIRST_TOUCH")
        self.assertEqual(s.stage, "DONE")

    def test_equal_extreme_policy_explicit(self):
        s = self.setup_leg()
        s.correction_extreme = 103
        config = demo_config()
        config.touch_extreme_ties = "strict"
        events, _ = update_confirmation(s,bar(1,high=108,low=103,close=104),config)
        self.assertEqual(events[0][0], "INELIGIBLE_FIRST_TOUCH")

    def test_new_low_after_touch_all_policies(self):
        for policy in ("keep_first", "cancel_setup", "replace_if_retouch"):
            s = self.setup_leg()
            config = demo_config()
            config.post_touch_extreme = policy
            first = bar(1,high=108,low=103,close=104)
            update_confirmation(s,first,config)
            second = bar(2,high=110,low=102,close=109)
            _, signal = update_confirmation(s,second,config)
            self.assertEqual(signal, policy == "keep_first")
            if policy == "replace_if_retouch":
                self.assertEqual(s.touch, second)
            elif policy == "cancel_setup":
                self.assertEqual(s.stage,"DONE")

    def test_fib_extension_touch_order_unresolved(self):
        s = self.setup_leg()
        config = demo_config()
        config.fib_end = "extend_until_touch"
        events, signal = update_confirmation(s,bar(1,high=120,low=100,close=115),config)
        self.assertFalse(signal)
        self.assertEqual(events[0][0], "AMBIGUOUS_FIB_UPDATE_TOUCH")
        self.assertEqual(s.stage,"DONE")

    def test_premium_discount_bounded_and_midpoint_policy(self):
        s = Setup(1,"LONG",START,90,110)
        self.assertTrue(s.inside_zone(bar(1,high=105,low=100,close=103),demo_config()))
        config = demo_config()
        config.zone_midpoint = "exclude"
        self.assertFalse(s.inside_zone(bar(1,high=105,low=100,close=103),config))
        self.assertFalse(s.inside_zone(bar(1,high=85,low=80,close=83,op=82),config))


class EndToEndTests(unittest.TestCase):
    def test_long_and_short_win_loss_ambiguous(self):
        for direction in ("LONG","SHORT"):
            for outcome, expected_r in (("WIN",2.0),("LOSS",-1.0),("AMBIGUOUS_INTRABAR",None)):
                with self.subTest(direction=direction,outcome=outcome):
                    e = engine(direction,outcome)
                    self.assertEqual(len(e.trades),1)
                    t = e.trades[0]
                    self.assertEqual((t.direction,t.result,t.R_multiple),(direction,outcome,expected_r))
                    self.assertEqual(t.risk_reward,2.0)
                    self.assertGreater(t.confirmation_time,t.touch_candle_time+timedelta(minutes=15))
                    self.assertGreater(t.choch_time_15m,t.zone_entry_time)
                    self.assertGreater(t.zone_entry_time,t.bos_time_4h)

    def test_exact_long_prices_and_times(self):
        t = engine().trades[0]
        self.assertEqual((t.fib_start,t.fib_end,t.entry_price),(98,112,109))
        self.assertAlmostEqual(t.fib_0618,103.348)
        self.assertAlmostEqual(t.stop_loss,102.9)
        self.assertAlmostEqual(t.take_profit,121.2)
        self.assertEqual(t.bos_time_4h,START+timedelta(hours=36))
        self.assertEqual(t.touch_candle_time,START+timedelta(hours=38,minutes=15))
        self.assertEqual(t.confirmation_time,START+timedelta(hours=38,minutes=45))

    def test_short_is_price_mirror(self):
        long, short = engine().trades[0],engine("SHORT").trades[0]
        for field in ("entry_price","stop_loss","take_profit","fib_start","fib_end","fib_0618"):
            self.assertAlmostEqual(getattr(long,field)+getattr(short,field),300)

    def test_no_exit_using_confirmation_candle_extremes(self):
        rows = synthetic()
        # Large confirmation high crosses the eventual target; earlier prices
        # in this candle cannot settle an entry at its CLOSE.
        rows[154] = replace(rows[154],high=200)
        e = BacktestEngine(demo_config()).run(rows[:155])
        self.assertEqual(len(e.trades),1)
        self.assertEqual(e.trades[0].result,"OPEN")

    def test_next_open_changes_entry_and_recomputes_target(self):
        rows = synthetic()
        rows[155] = replace(rows[155],open=110)
        config = demo_config()
        config.entry_mode = "next_open"
        t = BacktestEngine(config).run(rows).trades[0]
        self.assertEqual(t.entry_price,110)
        self.assertAlmostEqual(t.take_profit,124.2)

    def test_last_confirmation_next_open_order_remains_pending(self):
        config = demo_config()
        config.entry_mode = "next_open"
        e = BacktestEngine(config).run(synthetic()[:155])
        self.assertEqual(e.trades,[])
        self.assertIsNotNone(e.pending_entry)

    def test_entry_next_open_can_exit_same_candle(self):
        config = demo_config()
        config.entry_mode = "next_open"
        t = engine(config=config).trades[0]
        self.assertEqual(t.result,"WIN")
        self.assertEqual(t.exit_time-t.entry_time,timedelta(minutes=15))

    def test_incomplete_4h_future_high_not_used(self):
        prefix = synthetic()[:143]  # one 15m close short of 4H BOS
        e = BacktestEngine(demo_config()).run(prefix)
        self.assertFalse(any(x["event"] == "BOS_4H_DETECTED" for x in e.events))

    def test_new_bos_cancels_pending_setup_not_open_trade(self):
        e = engine()
        previous_id = e.setup.setup_id
        e.setup.stage = "WAIT_TOUCH_CONFIRM"
        e.trades[0].result = "OPEN"
        stamp = e.h4_history[-1].available_at
        reversal = Candle(stamp,stamp+timedelta(hours=4),110,125,85,89,1600)
        e._h4_update(reversal)
        self.assertTrue(any(ev["event"] == "SETUP_CANCELLED_NEW_BOS" and ev["setup_id"] == previous_id
                            for ev in e.events))
        self.assertEqual(e.setup.direction,"SHORT")
        self.assertEqual(e.trades[0].result,"OPEN")


class CausalityTests(unittest.TestCase):
    def test_every_prefix_identical_to_full_run_snapshot(self):
        for direction in ("LONG","SHORT"):
            rows = synthetic(direction)
            snapshots = []
            BacktestEngine(demo_config()).run(rows,on_close=lambda e,b:snapshots.append(e.snapshot()))
            for count in range(1,len(rows)+1):
                prefix = BacktestEngine(demo_config()).run(rows[:count])
                with self.subTest(direction=direction,prefix=count):
                    self.assertEqual(prefix.snapshot(),snapshots[count-1])

    def test_future_mutation_does_not_change_past(self):
        rows = synthetic()
        for count in (64, 128, 143, 144, 146, 152, 154, 155):
            mutated = rows[:count] + [replace(b,open=b.open+1000,high=b.high+1000,
                                                low=b.low+1000,close=b.close+1000) for b in rows[count:]]
            snapshots = []
            BacktestEngine(demo_config()).run(mutated,on_close=lambda e,b:snapshots.append(e.snapshot()))
            self.assertEqual(snapshots[count-1],BacktestEngine(demo_config()).run(rows[:count]).snapshot())

    def test_pivot_confirmation_never_postdates_decision(self):
        for direction in ("LONG","SHORT"):
            for event in engine(direction).events:
                for key in ("pivot","broken_swing","origin"):
                    pivot = event.get(key)
                    if pivot:
                        self.assertLessEqual(pivot["confirmed_at"],event["time"])

    def test_no_same_bar_reuse_of_new_4h_zone(self):
        e = engine()
        for t in e.trades:
            self.assertGreaterEqual(t.zone_entry_time,t.bos_time_4h+timedelta(minutes=15))


class RiskAndStatisticsTests(unittest.TestCase):
    def test_default_rr_is_two(self):
        self.assertEqual(Config().risk_reward,2.0)
        for direction in ("LONG","SHORT"):
            t = engine(direction).trades[0]
            self.assertAlmostEqual(abs(t.take_profit-t.entry_price)/t.risk,2.0)

    def test_custom_rr_explicit_override(self):
        config = demo_config()
        config.risk_reward = 2.5  # unit test of configurability, not a demo run
        stop, target = levels("LONG",109,bar(0,high=108,low=103,close=104),config)
        self.assertAlmostEqual(target-109,(109-stop)*2.5)

    def test_stop_strictly_outside_touch(self):
        long, short = engine().trades[0],engine("SHORT").trades[0]
        self.assertLess(long.stop_loss,long.touch_candle_low)
        self.assertGreater(short.stop_loss,short.touch_candle_high)

    def test_gap_stop_fills_open_not_optimistic_stop(self):
        t = engine().trades[0]
        gap = Candle(t.entry_time,t.entry_time+timedelta(minutes=15),100,105,99,104)
        result, price, r, _ = evaluate_exit(t,gap,demo_config())
        self.assertEqual((result,price),("LOSS",100))
        self.assertLess(r,-1)

    def test_gap_unresolved_mode(self):
        t = engine().trades[0]
        config = demo_config()
        config.gap_execution = "mark_unresolved"
        gap = Candle(t.entry_time,t.entry_time+timedelta(minutes=15),100,105,99,104)
        self.assertEqual(evaluate_exit(t,gap,config)[0],"GAP_UNRESOLVED")

    def test_dual_touch_never_winner(self):
        t = engine(outcome="AMBIGUOUS_INTRABAR").trades[0]
        self.assertEqual(t.result,"AMBIGUOUS_INTRABAR")
        self.assertIsNone(t.exit_price)
        self.assertIsNone(t.R_multiple)

    def test_statistics_exclude_unresolved_and_open(self):
        trades = [engine().trades[0],engine(outcome="LOSS").trades[0],
                  engine(outcome="AMBIGUOUS_INTRABAR").trades[0]]
        open_trade = deepcopy(trades[0])
        open_trade.result,open_trade.R_multiple,open_trade.exit_time = "OPEN",None,None
        stats = statistics(trades+[open_trade])
        self.assertEqual((stats["total_trades"],stats["resolved_trades"],stats["wins"],stats["losses"]),(4,2,1,1))
        self.assertEqual((stats["win_rate_pct"],stats["profit_factor"],stats["expectancy_r"],stats["total_r"]),(50,2,.5,1))

    def test_drawdown_and_streaks_by_exit_order(self):
        base = engine().trades[0]
        values = [2,-1,-1,2,2,-1]
        trades = [replace(base,trade_id=i+1,R_multiple=r,result="WIN" if r>0 else "LOSS",
                          exit_time=START+timedelta(hours=i)) for i,r in enumerate(values)]
        stats = statistics(list(reversed(trades)))
        self.assertEqual((stats["max_drawdown_r"],stats["maximum_consecutive_wins"],stats["maximum_consecutive_losses"]),(2,2,2))
        self.assertEqual((stats["average_winner_r"],stats["average_loser_r"]),(2,-1))

    def test_empty_statistics_are_json_safe(self):
        stats = statistics([])
        self.assertIsNone(stats["win_rate_pct"])
        self.assertIsNone(stats["profit_factor"])
        json.dumps(stats,allow_nan=False)


class ConfigAndReportTests(unittest.TestCase):
    def test_unresolved_choices_rejected(self):
        with self.assertRaisesRegex(ValueError,"Unresolved strategy choices"):
            Config().validate()

    def test_invalid_config_and_limit_fail_explicitly(self):
        for key,value in (("risk_reward",0),("risk_reward",float("inf")),("stop_buffer",0),
                          ("entry_mode","limit"),("post_touch_extreme","invented")):
            config = demo_config()
            setattr(config,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):
                config.validate()

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"config.json"
            p.write_text('{"typo":1}')
            with self.assertRaisesRegex(ValueError,"Unknown config"):
                Config.from_file(p)

    def test_exports_contain_full_trade_and_debug_sequence(self):
        e = engine()
        with tempfile.TemporaryDirectory() as d:
            export_run(e,d)
            with open(Path(d)/"trades.csv",encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows),1)
            self.assertTrue(set(asdict(e.trades[0])).issubset(rows[0]))
            self.assertEqual(float(rows[0]["risk_reward"]),2)
            debug = debug_trade(e,1)
            order = ["BOS_4H_DETECTED","ZONE_ENTERED","CHOCH_15M_DETECTED","FIB_LEG_SELECTED",
                     "FIB_0618_CALCULATED","TOUCH_DETECTED","CONFIRMATION_DETECTED","ENTRY","EXIT"]
            positions = [debug.index("| "+name+" |") for name in order]
            self.assertEqual(positions,sorted(positions))
            for file in ("summary.json","run_manifest.json"):
                json.loads((Path(d)/file).read_text())

    def test_plot_contains_all_required_markers(self):
        e = engine()
        with tempfile.TemporaryDirectory() as d:
            p = plot_trade(synthetic(),e.trades[0],Path(d)/"trade.svg")
            text = p.read_text()
            for label in ("4H BULLISH","CHOCH","Touch","Confirm","Entry","Stop Loss","Take Profit","Fib 0.618"):
                self.assertIn(label,text)


if __name__ == "__main__":
    unittest.main()
