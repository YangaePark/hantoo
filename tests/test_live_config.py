import unittest
import tempfile
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig
from semibot_live.trader import (
    DEFAULT_MARKET,
    OVERSEAS_MARKET,
    LiveConfig,
    LiveTrader,
    live_report_dir,
)


class LiveConfigTests(unittest.TestCase):
    def test_auto_select_defaults_on(self):
        config = LiveConfig.from_dict({})

        self.assertTrue(config.auto_select)
        self.assertEqual(config.max_symbols, 12)
        self.assertEqual(config.max_positions, 1)
        self.assertEqual(config.poll_interval_sec, 15)
        self.assertEqual(config.selection_refresh_sec, 300)
        self.assertEqual(config.min_selection_hold_sec, 1800)
        self.assertEqual(config.min_bars_before_evaluate, 20)
        self.assertEqual(config.seed_capital, 1_000_000.0)
        self.assertEqual(config.seed_source, "manual")
        self.assertFalse(config.auto_start)

    def test_max_positions_can_be_configured(self):
        config = LiveConfig.from_dict({"max_positions": 5})

        self.assertEqual(config.max_positions, 5)
        self.assertEqual(config.to_dict()["max_positions"], 5)

    def test_old_fast_selection_refresh_is_migrated(self):
        config = LiveConfig.from_dict(
            {
                "poll_interval_sec": 10,
                "max_symbols": 20,
                "selection_refresh_sec": 60,
                "min_selection_hold_sec": 600,
            }
        )

        self.assertEqual(config.poll_interval_sec, 15)
        self.assertEqual(config.max_symbols, 12)
        self.assertEqual(config.selection_refresh_sec, 300)
        self.assertEqual(config.min_selection_hold_sec, 1800)

    def test_seed_capital_can_be_configured(self):
        config = LiveConfig.from_dict({"seed_capital": "1500000"})

        self.assertEqual(config.seed_capital, 1_500_000.0)

    def test_invalid_seed_capital_falls_back_to_default(self):
        config = LiveConfig.from_dict({"seed_capital": "-10"})

        self.assertEqual(config.seed_capital, 1_000_000.0)

    def test_balance_max_seed_source_can_be_configured(self):
        config = LiveConfig.from_dict({"seed_source": "balance_max"})

        self.assertEqual(config.seed_source, "balance_max")

    def test_unknown_seed_source_falls_back_to_manual(self):
        config = LiveConfig.from_dict({"seed_source": "something_else"})

        self.assertEqual(config.seed_source, "manual")

    def test_auto_start_can_be_configured(self):
        config = LiveConfig.from_dict({"auto_start": True})

        self.assertTrue(config.auto_start)
        self.assertTrue(config.to_dict()["auto_start"])
        self.assertEqual(config.market, DEFAULT_MARKET)

    def test_manual_watchlist_payload_is_ignored(self):
        config = LiveConfig.from_dict(
            {
                "auto_select": False,
                "watchlist": "005930,000660\n042700",
            }
        )

        self.assertTrue(config.auto_select)
        self.assertFalse(hasattr(config, "watchlist"))

    def test_overseas_config_uses_nasdaq_scanner_defaults(self):
        config = LiveConfig.from_dict(
            {
                "market": "overseas",
                "symbol": "aapl",
                "exchange_code": "NAS",
                "price_exchange_code": "NASD",
                "currency": "EUR",
            }
        )

        self.assertEqual(config.market, OVERSEAS_MARKET)
        self.assertEqual(config.symbol, "")
        self.assertTrue(config.auto_select)
        self.assertEqual(config.exchange_code, "NASD")
        self.assertEqual(config.price_exchange_code, "NAS")
        self.assertEqual(config.currency, "USD")
        self.assertEqual(config.seed_capital, 10_000.0)
        self.assertEqual(config.clock_offset_hours, -7)
        self.assertEqual(config.max_positions, 1)
        self.assertFalse(config.overseas_premarket_enabled)

    def test_overseas_premarket_can_be_enabled(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})

        self.assertTrue(config.overseas_premarket_enabled)
        self.assertTrue(config.to_dict()["overseas_premarket_enabled"])

    def test_overseas_report_path_is_separate(self):
        self.assertNotEqual(live_report_dir(DEFAULT_MARKET), live_report_dir(OVERSEAS_MARKET))

    def test_entry_wait_message_explains_force_exit_time(self):
        strategy = StockScannerConfig()
        trader = LiveTrader(LiveConfig(), strategy)
        trader.active_symbols = ["005930"]

        message = trader._entry_wait_message(datetime(2026, 4, 29, 18, 30))

        self.assertIn("15:15 이후", message)

    def test_symbol_entry_reason_explains_low_volume(self):
        strategy = replace(StockScannerConfig(), volume_sma=3, observation_minutes=5, atr_period=3)
        trader = LiveTrader(LiveConfig(), strategy)
        start = datetime(2026, 4, 29, 9, 0)
        trader.bars = [
            StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
            StockBar("005930", start, 103.0, 104.0, 102.0, 103.5, 1000),
            StockBar("005930", start + timedelta(minutes=5), 103.5, 105.0, 103.0, 104.5, 1000),
            StockBar("005930", start + timedelta(minutes=10), 104.5, 106.0, 104.0, 105.5, 1000),
            StockBar("005930", start + timedelta(minutes=15), 105.5, 107.0, 105.0, 106.5, 1000),
            StockBar("005930", start + timedelta(minutes=20), 106.5, 108.0, 106.0, 107.5, 1000),
        ]

        message = trader._symbol_entry_reason("005930", start + timedelta(minutes=21))

        self.assertIn("거래량", message)

    def test_symbol_entry_reason_uses_current_move_not_open_gap(self):
        strategy = replace(StockScannerConfig(), volume_sma=3, observation_minutes=5, atr_period=3)
        trader = LiveTrader(LiveConfig(), strategy)
        start = datetime(2026, 4, 29, 9, 0)
        trader.bars = [
            StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
            StockBar("005930", start, 100.4, 101.0, 100.0, 100.5, 1000),
            StockBar("005930", start + timedelta(minutes=5), 100.5, 103.0, 100.5, 102.5, 1000),
            StockBar("005930", start + timedelta(minutes=10), 102.5, 104.0, 102.0, 103.5, 1000),
            StockBar("005930", start + timedelta(minutes=15), 103.5, 105.0, 103.0, 104.5, 1000),
        ]

        message = trader._symbol_entry_reason("005930", start + timedelta(minutes=16))

        self.assertNotIn("갭 0.4%", message)

    def test_symbol_entry_reason_shows_observation_progress(self):
        strategy = replace(StockScannerConfig(), observation_minutes=20)
        trader = LiveTrader(LiveConfig(), strategy)
        start = datetime(2026, 4, 30, 9, 0)
        trader.bars = [
            StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
            StockBar("005930", start, 103.0, 104.0, 102.0, 103.5, 1000),
            StockBar("005930", start + timedelta(minutes=5), 103.5, 105.0, 103.0, 104.5, 1000),
            StockBar("005930", start + timedelta(minutes=10), 104.5, 106.0, 104.0, 105.5, 1000),
        ]

        message = trader._symbol_entry_reason("005930", start + timedelta(minutes=10))

        self.assertIn("진입 전 관찰 중 (10/20분)", message)

    def test_add_tick_builds_bars_from_tick_price_and_volume_delta(self):
        trader = LiveTrader(LiveConfig(), StockScannerConfig())
        start = datetime(2026, 4, 30, 10, 0)

        trader._add_tick(
            "005930",
            start,
            {"price": 100.0, "open": 95.0, "high": 120.0, "low": 90.0, "volume": 1000, "prev_rate_pct": 3.0},
        )
        trader._add_tick(
            "005930",
            start + timedelta(minutes=1),
            {"price": 101.0, "open": 95.0, "high": 120.0, "low": 90.0, "volume": 1300, "prev_rate_pct": 4.0},
        )
        trader._add_tick(
            "005930",
            start + timedelta(minutes=5),
            {"price": 102.0, "open": 95.0, "high": 120.0, "low": 90.0, "volume": 1800, "prev_rate_pct": 5.0},
        )

        current_bars = [bar for bar in trader.bars if bar.session == start.date()]

        self.assertEqual(len(current_bars), 2)
        self.assertEqual(current_bars[0].open, 100.0)
        self.assertEqual(current_bars[0].high, 101.0)
        self.assertEqual(current_bars[0].low, 100.0)
        self.assertEqual(current_bars[0].close, 101.0)
        self.assertEqual(current_bars[0].volume, 300)
        self.assertEqual(current_bars[1].open, 102.0)
        self.assertEqual(current_bars[1].high, 102.0)
        self.assertEqual(current_bars[1].low, 102.0)
        self.assertEqual(current_bars[1].volume, 500)

    def test_selected_symbols_are_kept_for_minimum_hold(self):
        config = LiveConfig(max_symbols=3, min_selection_hold_sec=600)
        trader = LiveTrader(config, StockScannerConfig())
        trader.active_symbols = ["111111", "222222"]
        trader.selected_since = {"111111": 1000.0, "222222": 500.0}

        selected = trader._merge_selected_symbols(["333333"], 1200.0)

        self.assertEqual(selected, ["111111", "333333"])
        self.assertIn("111111", trader.selected_since)
        self.assertNotIn("222222", trader.selected_since)

    def test_overseas_selector_uses_nasdaq_rankings(self):
        config = LiveConfig.from_dict({"market": "overseas", "symbol": "MSFT", "max_symbols": 2, "candidate_pool_size": 10})
        strategy = StockScannerConfig()
        trader = LiveTrader(config, strategy)

        selected = trader._select_symbols(FakeOverseasRankClient())

        self.assertEqual(len(selected), 2)
        self.assertIn("AAPL", selected)
        self.assertNotIn("MSFT", selected)
        self.assertNotIn("QQQ", selected)
        self.assertIn("NASDAQ 자동선별", trader.status["selector_message"])

    def test_overseas_selector_tracks_ranked_symbols_before_entry_filter_passes(self):
        config = LiveConfig.from_dict({"market": "overseas", "max_symbols": 2, "candidate_pool_size": 10})
        trader = LiveTrader(config, StockScannerConfig())

        selected = trader._select_symbols(WeakOverseasRankClient())

        self.assertEqual(len(selected), 2)
        self.assertIn("AAPL", selected)
        self.assertIn("TSLA", selected)

    def test_overseas_selector_keeps_tracking_when_one_price_lookup_fails(self):
        config = LiveConfig.from_dict({"market": "overseas", "max_symbols": 2, "candidate_pool_size": 10})
        trader = LiveTrader(config, StockScannerConfig())

        selected = trader._select_symbols(FlakyOverseasPriceClient())

        self.assertEqual(len(selected), 2)
        self.assertIn("AAPL", selected)
        self.assertIn("TSLA", selected)

    def test_overseas_premarket_strategy_is_stricter(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())
        strategy = trader._active_strategy(datetime(2026, 4, 30, 8, 0))

        self.assertEqual(trader._market_session(datetime(2026, 4, 30, 8, 0)), "premarket")
        self.assertEqual(strategy.observation_minutes, 30)
        self.assertLessEqual(strategy.max_position_pct, 0.5)
        self.assertGreaterEqual(strategy.volume_factor, 2.2)
        self.assertLessEqual(strategy.max_trades_per_day, 2)
        self.assertGreaterEqual(strategy.partial_take_profit_pct, 0.012)
        self.assertGreaterEqual(strategy.time_stop_minutes, 45)

    def test_overseas_live_strategy_uses_defensive_limits(self):
        config = LiveConfig.from_dict({"market": "overseas", "mode": "live"})
        trader = LiveTrader(config, StockScannerConfig(max_trades_per_day=6))

        strategy = trader._active_strategy(datetime(2026, 4, 30, 10, 0))

        self.assertEqual(config.max_positions, 1)
        self.assertLessEqual(strategy.max_trades_per_day, 2)
        self.assertGreaterEqual(strategy.partial_take_profit_pct, 0.012)
        self.assertGreaterEqual(strategy.time_stop_minutes, 45)

    def test_domestic_live_strategy_is_more_active(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        strategy = trader._active_strategy(datetime(2026, 4, 30, 12, 0))

        self.assertEqual(strategy.observation_minutes, 10)
        self.assertEqual(strategy.top_value_rank, 8)
        self.assertLessEqual(strategy.gap_min_pct, 0.008)
        self.assertLessEqual(strategy.volume_factor, 1.3)
        self.assertLessEqual(strategy.max_trades_per_day, 3)
        self.assertGreaterEqual(strategy.min_edge_bps, 35.0)
        self.assertGreaterEqual(strategy.loss_cooldown_minutes, 60)
        self.assertGreaterEqual(strategy.partial_take_profit_pct, 0.012)

    def test_domestic_live_entry_risk_blocks_weak_index_proxy(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        start = datetime(2026, 4, 30, 9, 40)
        trader.bars = _domestic_proxy_bars(start, bullish=False)
        strategy = StockScannerConfig(entry_start_time="09:00", entry_cutoff_time="15:00")

        message = trader._entry_risk_block(start + timedelta(minutes=10), strategy)

        self.assertEqual(message, "국내 지수 필터 미충족")

    def test_entry_block_tone_blocks_adaptive_entries(self):
        trader = LiveTrader(LiveConfig(mode="paper"), StockScannerConfig())
        trader.status["strategy_tone"] = "entry_block"
        strategy = StockScannerConfig(
            adaptive_market_regime=True,
            entry_start_time="09:00",
            entry_cutoff_time="15:00",
        )

        message = trader._entry_risk_block(datetime(2026, 4, 30, 10, 0), strategy)

        self.assertEqual(message, "신규진입 차단")

    def test_same_symbol_reentry_waits_after_any_full_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-04-30 09:05:00,BUY,005930,1,100,100,0,0,999900,live_momentum_entry,live,{},k1\n"
                "2026-04-30 09:20:00,SELL_ALL,005930,1,103,103,0,3,1000003,live_take_profit,live,{},k2\n",
                encoding="utf-8",
            )
            trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig(), report_dir=report_dir)
            trader.bars = _domestic_proxy_bars(datetime(2026, 4, 30, 9, 30), bullish=True)
            strategy = StockScannerConfig(
                adaptive_market_regime=False,
                entry_start_time="09:00",
                entry_cutoff_time="15:00",
            )

            allowed = trader._can_open_position("005930", datetime(2026, 4, 30, 9, 45), strategy)

            self.assertFalse(allowed)
            self.assertIn("매도 후 재진입 대기", trader.snapshot()["trade_message"])

    def test_market_tone_stays_normal_in_strong_market(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        strategy = StockScannerConfig(adaptive_market_regime=True)
        start = datetime(2026, 4, 30, 9, 0)
        trader.active_symbols = ["000001", "000002", "000003"]
        trader.bars = _tone_bars(trader.active_symbols, start, [101.0, 101.0, 101.0])

        self.assertEqual(trader._stable_tone(start, strategy), "normal")
        self.assertEqual(trader._stable_tone(start + timedelta(minutes=9), strategy), "normal")
        self.assertEqual(trader._stable_tone(start + timedelta(minutes=10), strategy), "normal")

    def test_market_tone_blocks_entries_after_weak_confirm(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        strategy = StockScannerConfig(adaptive_market_regime=True)
        start = datetime(2026, 4, 30, 9, 0)
        trader.active_symbols = ["000001", "000002", "000003"]
        trader.bars = _tone_bars(trader.active_symbols, start, [100.1, 100.1, 100.1])
        self.assertEqual(trader._stable_tone(start, strategy), "normal")
        self.assertEqual(trader._stable_tone(start + timedelta(minutes=3), strategy), "normal")
        self.assertEqual(trader._stable_tone(start + timedelta(minutes=4), strategy), "entry_block")

    def test_market_tone_can_block_entries_near_daily_stop(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        strategy = StockScannerConfig(adaptive_market_regime=True, daily_stop_loss_pct=0.02)
        now = datetime(2026, 4, 30, 10, 0)
        trader.active_symbols = ["000001", "000002", "000003"]
        trader.bars = _tone_bars(trader.active_symbols, now, [100.1, 100.1, 100.1])
        trader._tone_current = "normal"
        trader._tone_current_since = now
        trader.day_state_date = now.date()
        trader.day_start_cash = 1000.0
        trader.cash = 981.0

        self.assertEqual(trader._stable_tone(now, strategy), "entry_block")

    def test_entry_wait_message_summarizes_all_active_symbol_reasons(self):
        strategy = replace(StockScannerConfig(), observation_minutes=20)
        trader = LiveTrader(LiveConfig(), strategy)
        start = datetime(2026, 4, 30, 9, 0)
        trader.active_symbols = ["000001", "000002", "000003", "000004", "000005", "000006"]
        trader.bars = [
            StockBar(symbol, start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1)
            for symbol in trader.active_symbols
        ] + [
            StockBar(symbol, start, 103.0, 103.0, 103.0, 103.0, 1000)
            for symbol in trader.active_symbols
        ]

        message = trader._entry_wait_message(start + timedelta(minutes=5))

        self.assertIn("외 1종목", message)
        self.assertIn("요약: 관찰중 6", message)

    def test_overseas_premarket_disabled_waits_for_regular_session(self):
        config = LiveConfig.from_dict({"market": "overseas"})
        trader = LiveTrader(config, StockScannerConfig())

        self.assertEqual(trader._market_session(datetime(2026, 4, 30, 8, 0)), "closed")
        self.assertEqual(trader._market_session(datetime(2026, 4, 30, 10, 0)), "regular")
        self.assertEqual(trader._market_session(datetime(2026, 5, 2, 10, 0)), "closed")

    def test_overseas_strategy_now_uses_new_york_timezone(self):
        trader = LiveTrader(LiveConfig.from_dict({"market": "overseas"}), StockScannerConfig())

        summer = trader._strategy_now(datetime(2026, 5, 6, 22, 30))
        winter = trader._strategy_now(datetime(2026, 1, 6, 23, 30))

        self.assertEqual(summer.strftime("%Y-%m-%d %H:%M"), "2026-05-06 09:30")
        self.assertEqual(winter.strftime("%Y-%m-%d %H:%M"), "2026-01-06 09:30")

    def test_domestic_market_wait_status_uses_domestic_label(self):
        trader = LiveTrader(LiveConfig.from_dict({"market": "domestic"}), StockScannerConfig())

        trader._set_market_wait_status(datetime(2026, 5, 6, 8, 30), datetime(2026, 5, 6, 8, 30))

        snapshot = trader.snapshot()
        self.assertEqual(snapshot["message"], "국내장 대기")
        self.assertEqual(snapshot["session_label"], "국내장 대기")
        self.assertIn("09:00", snapshot["selector_message"])

    def test_market_wait_clears_stale_price_error_count(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())
        trader.status["price_error_count"] = 3

        trader._set_market_wait_status(datetime(2026, 4, 30, 17, 0), datetime(2026, 4, 30, 17, 0))

        self.assertEqual(trader.snapshot()["price_error_count"], 0)

    def test_overseas_empty_rankings_fall_back_to_liquid_universe(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())

        candidates = trader._overseas_candidate_symbols(EmptyOverseasRankClient())

        self.assertIn("AAPL", candidates)
        self.assertIn("fallback", candidates["AAPL"]["_sources"])

    def test_empty_selection_waits_for_refresh_interval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LiveConfig.from_dict({"market": "domestic", "selection_refresh_sec": 60})
            trader = LiveTrader(config, StockScannerConfig(gap_min_pct=0.03, gap_max_pct=0.12), report_dir=Path(tmpdir))
            client = EmptyDomesticRankClient()
            now = datetime(2026, 4, 30, 10, 0)

            trader._run_cycle(client, now)
            first_calls = client.calls
            trader._run_cycle(client, now + timedelta(seconds=5))

            self.assertGreater(first_calls, 0)
            self.assertEqual(client.calls, first_calls)

    def test_live_cycle_writes_metrics_from_actual_cash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            config = LiveConfig.from_dict({"market": "domestic", "mode": "live", "selection_refresh_sec": 60})
            strategy = StockScannerConfig(initial_capital=200_000, gap_min_pct=0.03, gap_max_pct=0.12)
            trader = LiveTrader(config, strategy, report_dir=report_dir)
            trader.cash = 200_000

            trader._run_cycle(EmptyDomesticRankClient(), datetime(2026, 4, 30, 10, 0))

            metrics = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["initial_capital"], 200_000)
            self.assertEqual(metrics["final_equity"], 200_000)
            self.assertEqual(metrics["total_return_pct"], 0.0)
            self.assertIn("2026-04-30 10:00", (report_dir / "equity_curve.csv").read_text(encoding="utf-8"))

    def test_live_ignores_backtester_sell_signal_for_live_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime(2026, 4, 30, 10, 0)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", min_bars_before_evaluate=1),
                StockScannerConfig(entry_start_time="09:00", entry_cutoff_time="15:00"),
                report_dir=Path(tmpdir),
            )
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 100.5,
                "entry_time": (now - timedelta(minutes=10)).isoformat(sep=" "),
            }
            trader.bars = [StockBar("005930", now, 100.5, 100.6, 100.2, 100.5, 1000)]
            fake_trade = SimpleNamespace(
                timestamp=now,
                action="SELL",
                symbol="005930",
                shares=10,
                price=100.5,
                reason="backtest_stop_loss",
            )
            fake_result = SimpleNamespace(metrics={}, trades=[fake_trade], equity_curve=[])
            client = FakeDomesticOrderClient()

            with patch("semibot_live.trader.StockScannerBacktester") as backtester:
                backtester.return_value.run.return_value = fake_result
                trader._evaluate(client, now)

            self.assertEqual(client.orders, [])
            self.assertIsNotNone(trader.position)
            self.assertIn("실시간 청산 조건 대기", trader.snapshot()["trade_message"])

    def test_live_buy_keeps_estimated_cash_when_balance_cash_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000_000)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 9, 10)
            trader.cash = 1_000_000
            bar = StockBar("005930", now, 100.0, 101.0, 99.0, 100.0, 1000)
            client = FakeDomesticBalanceOrderClient(
                cash=1_000_000,
                holdings=[{"pdno": "005930", "hldg_qty": "8", "pchs_avg_pric": "101"}],
            )

            submitted = trader._submit_live_buy(client, now, strategy, bar, 10, "test_entry")

            expected_cash = round(1_000_000 - (8 * 101.0) - (8 * 101.0 * (strategy.commission_rate + strategy.slippage_rate)), 2)
            row = trader._live_equity_row(now)
            self.assertTrue(submitted)
            self.assertEqual(trader.positions[0]["shares"], 8)
            self.assertEqual(trader.positions[0]["entry_price"], 101.0)
            self.assertEqual(trader.cash, expected_cash)
            self.assertEqual(row["cash"], expected_cash)
            self.assertEqual(row["equity"], round(expected_cash + (8 * 101.0), 2))

    def test_regular_session_resets_premarket_bars_when_flat(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())
        day = datetime(2026, 4, 30)
        trader.bars = [
            StockBar("AAPL", day.replace(hour=8, minute=0), 100.0, 101.0, 99.0, 100.5, 1000),
            StockBar("AAPL", day.replace(hour=9, minute=30), 101.0, 102.0, 100.0, 101.5, 2000),
        ]

        trader._reset_premarket_bars_for_regular_if_flat(day.replace(hour=9, minute=31), "regular")

        self.assertEqual([bar.timestamp.hour for bar in trader.bars], [9])
        self.assertEqual(trader.bars[0].timestamp.minute, 30)

    def test_retriable_error_keeps_trader_running(self):
        trader = LiveTrader(LiveConfig(), StockScannerConfig())
        trader.running = True
        trader.active_symbols = ["005930"]
        now = datetime(2026, 4, 30, 4, 0, 22)

        trader._record_retriable_error(RuntimeError("Temporary failure in name resolution"), now)
        status = trader.snapshot()

        self.assertTrue(status["running"])
        self.assertEqual(status["message"], "통신 오류 재시도 대기")
        self.assertIn("Temporary failure", status["last_error"])
        self.assertEqual(status["active_symbols"], ["005930"])

    def test_startup_token_is_checked_before_market_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas"}),
                StockScannerConfig(),
                report_dir=Path(tmpdir),
            )
            client = FakeStartupTokenClient()
            now = datetime(2026, 4, 30, 3, 0)

            trader._ensure_startup_token(client, now)
            trader._ensure_startup_token(client, now)

            status = trader.snapshot()
            logs = _read_decision_logs(Path(tmpdir))
            self.assertEqual(client.token_checks, 1)
            self.assertTrue(trader.startup_token_checked)
            self.assertEqual(status["token_status"], "확인 완료")
            self.assertTrue(any(row["event"] == "token_ready" for row in logs))

    def test_live_direct_entry_orders_when_backtester_has_no_breakout_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(
                StockScannerConfig(),
                initial_capital=1_000_000,
                observation_minutes=5,
                gap_min_pct=0.003,
                gap_max_pct=0.12,
                volume_sma=2,
                volume_factor=1.0,
                min_atr_pct=0.0,
                max_atr_pct=0.2,
            )
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 0)
            trader.active_symbols = ["005930"]
            trader.cash = 1_000_000
            trader.bars = [
                StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("005930", start, 101.0, 101.5, 100.5, 101.0, 1000),
                StockBar("005930", start + timedelta(minutes=5), 101.0, 102.2, 100.8, 102.0, 1100),
                StockBar("005930", start + timedelta(minutes=10), 102.0, 102.1, 101.2, 101.6, 1200),
                StockBar("005930", start + timedelta(minutes=15), 101.6, 104.5, 101.5, 104.2, 1800),
            ] + _domestic_proxy_bars(start)
            client = FakeDomesticOrderClient()

            trader._evaluate(client, start + timedelta(minutes=16))

            self.assertEqual(len(client.orders), 1)
            self.assertEqual(client.orders[0]["side"], "buy")
            self.assertEqual(trader.position["symbol"], "005930")
            self.assertEqual(trader.snapshot()["orders"], 1)
            self.assertIn("live_momentum_reclaim_entry", trader.snapshot()["trade_message"])
            logs = _read_decision_logs(Path(tmpdir))
            self.assertTrue(any(row["event"] == "order_submitted" and row["side"] == "buy" for row in logs))

    def test_domestic_live_buy_caps_quantity_to_broker_market_orderable_qty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000_000)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 9, 10)
            trader.cash = 1_000_000
            bar = StockBar("005930", now, 100000.0, 100000.0, 100000.0, 100000.0, 1)
            client = FakeDomesticPsblOrderClient(orderable_quantity=7)

            submitted = trader._submit_live_buy(client, now, strategy, bar, 9, "test_entry")

            self.assertTrue(submitted)
            self.assertEqual(client.psbl_requests[0]["symbol"], "005930")
            self.assertEqual(client.psbl_requests[0]["order_division"], "01")
            self.assertEqual(client.orders[0]["quantity"], 7)
            logs = _read_decision_logs(Path(tmpdir))
            self.assertTrue(any(row["event"] == "order_shares_capped" and row["capped_shares"] == 7 for row in logs))

    def test_domestic_live_buy_skips_when_broker_orderable_qty_is_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000_000)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 9, 10)
            trader.cash = 1_000_000
            bar = StockBar("005930", now, 100000.0, 100000.0, 100000.0, 100000.0, 1)
            client = FakeDomesticPsblOrderClient(orderable_quantity=0)

            submitted = trader._submit_live_buy(client, now, strategy, bar, 9, "test_entry")

            self.assertFalse(submitted)
            self.assertEqual(client.orders, [])
            self.assertIn("주문 가능 수량 없음", trader.snapshot()["trade_message"])

    def test_live_direct_entry_honors_daily_trade_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-04-30 09:10:00,BUY,000660,1,100.0,100.0,0.0,0.0,999900.0,live_momentum_entry,live,{},buy-key\n"
                "2026-04-30 09:20:00,SELL_ALL,000660,1,101.0,101.0,0.0,1.0,1000001.0,live_take_profit,live,{},sell-key\n",
                encoding="utf-8",
            )
            strategy = replace(
                StockScannerConfig(),
                initial_capital=1_000_000,
                observation_minutes=5,
                gap_min_pct=0.003,
                gap_max_pct=0.12,
                volume_sma=2,
                volume_factor=1.0,
                min_atr_pct=0.0,
                max_atr_pct=0.2,
                max_trades_per_day=1,
            )
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=report_dir,
            )
            start = datetime(2026, 4, 30, 9, 0)
            trader.active_symbols = ["005930"]
            trader.cash = 1_000_000
            trader.bars = [
                StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("005930", start, 101.0, 101.5, 100.5, 101.0, 1000),
                StockBar("005930", start + timedelta(minutes=5), 101.0, 102.2, 100.8, 102.0, 1100),
                StockBar("005930", start + timedelta(minutes=10), 102.0, 102.1, 101.2, 101.6, 1200),
                StockBar("005930", start + timedelta(minutes=15), 101.6, 104.5, 101.5, 104.2, 1800),
            ] + _domestic_proxy_bars(start)
            client = FakeDomesticOrderClient()

            entered = trader._try_live_direct_entry(client, start + timedelta(minutes=16), strategy, {}, [])

            self.assertFalse(entered)
            self.assertEqual(client.orders, [])
            self.assertIn("일일 진입 한도 도달", trader.snapshot()["trade_message"])
            logs = _read_decision_logs(report_dir)
            self.assertTrue(any(row["event"] == "entry_skip" and row["reason"] == "daily_trade_limit" for row in logs))

    def test_domestic_live_direct_entry_blocks_second_position(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(
                StockScannerConfig(),
                initial_capital=900_000,
                observation_minutes=5,
                gap_min_pct=0.003,
                gap_max_pct=0.12,
                volume_sma=2,
                volume_factor=1.0,
                min_atr_pct=0.0,
                max_atr_pct=0.2,
            )
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", max_positions=3),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 0)
            trader.positions = [{"symbol": "000660", "shares": 10, "entry_price": 100.0, "highest_price": 100.0}]
            trader.active_symbols = ["000660", "005930"]
            trader.cash = 600_000
            trader.bars = [
                StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("005930", start, 101.0, 101.5, 100.5, 101.0, 1000),
                StockBar("005930", start + timedelta(minutes=5), 101.0, 102.2, 100.8, 102.0, 1100),
                StockBar("005930", start + timedelta(minutes=10), 102.0, 102.1, 101.2, 101.6, 1200),
                StockBar("005930", start + timedelta(minutes=15), 101.6, 104.5, 101.5, 104.2, 1800),
            ] + _domestic_proxy_bars(start)
            client = FakeDomesticOrderClient()

            entered = trader._try_live_direct_entry(client, start + timedelta(minutes=16), strategy, {}, [])

            self.assertFalse(entered)
            self.assertEqual(len(trader.positions), 1)
            self.assertEqual(client.orders, [])
            self.assertIn("최대 동시보유 도달", trader.snapshot()["trade_message"])

    def test_live_direct_entry_stops_at_max_positions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=900_000)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", max_positions=2),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 0)
            trader.positions = [
                {"symbol": "000660", "shares": 10, "entry_price": 100.0, "highest_price": 100.0},
                {"symbol": "005930", "shares": 10, "entry_price": 100.0, "highest_price": 100.0},
            ]
            trader.active_symbols = ["035420"]
            trader.bars = _domestic_proxy_bars(now, bullish=True)
            client = FakeDomesticOrderClient()

            entered = trader._try_live_direct_entry(client, now, strategy, {}, [])

            self.assertFalse(entered)
            self.assertEqual(client.orders, [])
            self.assertIn("최대 동시보유 도달", trader.snapshot()["trade_message"])

    def test_overseas_regular_direct_entry_uses_overseas_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(
                StockScannerConfig(),
                initial_capital=10_000,
                observation_minutes=5,
                gap_min_pct=0.003,
                gap_max_pct=0.12,
                volume_sma=2,
                volume_factor=1.1,
                max_extension_pct=0.05,
                stop_loss_pct=0.012,
            )
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 30)
            trader.active_symbols = ["AAPL"]
            trader.cash = 10_000
            trader.bars = [
                StockBar("AAPL", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("AAPL", start, 101.0, 101.2, 100.8, 101.0, 1000),
                StockBar("AAPL", start + timedelta(minutes=5), 101.0, 102.2, 100.9, 102.0, 1200),
                StockBar("AAPL", start + timedelta(minutes=10), 102.0, 102.1, 101.2, 101.6, 1500),
                StockBar("AAPL", start + timedelta(minutes=15), 101.6, 104.0, 101.5, 103.8, 2500),
                StockBar("QQQ", start - timedelta(days=1), 400.0, 400.0, 400.0, 400.0, 1),
                StockBar("QQQ", start, 401.0, 401.5, 400.7, 401.0, 1000),
                StockBar("QQQ", start + timedelta(minutes=5), 401.0, 402.2, 400.9, 402.0, 1200),
                StockBar("QQQ", start + timedelta(minutes=10), 402.0, 402.3, 401.2, 401.8, 1300),
                StockBar("QQQ", start + timedelta(minutes=15), 401.8, 403.0, 401.7, 402.5, 1400),
            ]
            client = FakeOverseasOrderClient()

            trader._evaluate(client, start + timedelta(minutes=16))

            self.assertEqual(len(client.orders), 1)
            self.assertEqual(client.orders[0]["symbol"], "AAPL")
            self.assertEqual(client.orders[0]["exchange_code"], "NASD")
            self.assertIn("live_overseas_momentum_entry", trader.snapshot()["trade_message"])

    def test_overseas_regular_direct_entry_blocks_when_qqq_is_weak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(
                StockScannerConfig(),
                initial_capital=10_000,
                observation_minutes=5,
                gap_min_pct=0.003,
                gap_max_pct=0.12,
                volume_sma=2,
                volume_factor=1.1,
                max_extension_pct=0.05,
                stop_loss_pct=0.012,
            )
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 30)
            trader.active_symbols = ["AAPL"]
            trader.cash = 10_000
            trader.bars = [
                StockBar("AAPL", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("AAPL", start, 101.0, 101.2, 100.8, 101.0, 1000),
                StockBar("AAPL", start + timedelta(minutes=5), 101.0, 102.2, 100.9, 102.0, 1200),
                StockBar("AAPL", start + timedelta(minutes=10), 102.0, 102.1, 101.2, 101.6, 1500),
                StockBar("AAPL", start + timedelta(minutes=15), 101.6, 104.0, 101.5, 103.8, 2500),
                StockBar("QQQ", start - timedelta(days=1), 400.0, 400.0, 400.0, 400.0, 1),
                StockBar("QQQ", start, 399.0, 399.5, 398.0, 399.0, 1000),
                StockBar("QQQ", start + timedelta(minutes=5), 399.0, 399.2, 397.5, 398.0, 1200),
                StockBar("QQQ", start + timedelta(minutes=10), 398.0, 398.2, 396.5, 397.0, 1300),
                StockBar("QQQ", start + timedelta(minutes=15), 397.0, 397.5, 395.8, 396.5, 1400),
            ]
            client = FakeOverseasOrderClient()

            trader._evaluate(client, start + timedelta(minutes=16))

            self.assertEqual(client.orders, [])
            self.assertIn("QQQ 시장 필터", trader._symbol_entry_reason("AAPL", start + timedelta(minutes=16)))

    def test_overseas_premarket_direct_entry_uses_strict_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=10_000)
            trader = LiveTrader(
                LiveConfig.from_dict(
                    {
                        "market": "overseas",
                        "mode": "live",
                        "account_no": "12345678",
                        "overseas_premarket_enabled": True,
                    }
                ),
                strategy,
                report_dir=Path(tmpdir),
            )
            strategy = trader._active_strategy(datetime(2026, 4, 30, 8, 35))
            start = datetime(2026, 4, 30, 8, 0)
            trader.active_symbols = ["NVDA"]
            trader.cash = 10_000
            trader.bars = [
                StockBar("NVDA", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("NVDA", start, 101.5, 101.8, 101.0, 101.4, 1000),
                StockBar("NVDA", start + timedelta(minutes=5), 101.4, 102.0, 101.3, 101.8, 1000),
                StockBar("NVDA", start + timedelta(minutes=10), 101.8, 102.2, 101.5, 102.0, 1000),
                StockBar("NVDA", start + timedelta(minutes=15), 102.0, 102.5, 101.8, 102.3, 1000),
                StockBar("NVDA", start + timedelta(minutes=20), 102.3, 103.0, 102.1, 102.7, 1000),
                StockBar("NVDA", start + timedelta(minutes=25), 102.7, 103.2, 102.5, 103.0, 1000),
                StockBar("NVDA", start + timedelta(minutes=30), 103.0, 105.5, 103.0, 105.2, 2600),
                StockBar("NVDA", start + timedelta(minutes=35), 105.2, 106.6, 105.1, 106.4, 3600),
            ]
            client = FakeOverseasOrderClient()

            trader._try_live_direct_entry(client, start + timedelta(minutes=36), strategy, {}, [])

            self.assertEqual(len(client.orders), 1)
            self.assertLessEqual(client.orders[0]["quantity"] * 106.4, 5_000)
            self.assertIn("live_premarket_momentum_entry", trader.snapshot()["trade_message"])

    def test_overseas_premarket_direct_entry_rejects_weak_breakout(self):
        config = LiveConfig.from_dict(
            {
                "market": "overseas",
                "mode": "live",
                "account_no": "12345678",
                "overseas_premarket_enabled": True,
            }
        )
        trader = LiveTrader(config, StockScannerConfig())
        start = datetime(2026, 4, 30, 8, 0)
        strategy = trader._active_strategy(start + timedelta(minutes=35))
        trader.bars = [
            StockBar("NVDA", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
            StockBar("NVDA", start, 101.5, 105.5, 101.0, 101.4, 1000),
            StockBar("NVDA", start + timedelta(minutes=5), 101.4, 102.0, 101.3, 101.8, 1000),
            StockBar("NVDA", start + timedelta(minutes=10), 101.8, 102.2, 101.5, 102.0, 1000),
            StockBar("NVDA", start + timedelta(minutes=15), 102.0, 102.5, 101.8, 102.3, 1000),
            StockBar("NVDA", start + timedelta(minutes=20), 102.3, 103.0, 102.1, 102.7, 1000),
            StockBar("NVDA", start + timedelta(minutes=25), 102.7, 103.2, 102.5, 103.0, 1000),
            StockBar("NVDA", start + timedelta(minutes=30), 103.0, 104.8, 103.0, 104.7, 1800),
            StockBar("NVDA", start + timedelta(minutes=35), 104.7, 105.0, 104.5, 104.9, 1900),
        ]

        self.assertIsNone(trader._live_direct_entry_candidate("NVDA", start + timedelta(minutes=36), strategy))

    def test_live_direct_exit_sells_direct_position_on_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 0)
            trader.position = {"symbol": "005930", "shares": 10, "entry_price": 100.0, "highest_price": 100.0}
            trader.bars = [StockBar("005930", now, 99.0, 99.0, 98.5, 98.8, 1000)]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy)

            self.assertTrue(sold)
            self.assertEqual(client.orders[0]["side"], "sell")
            self.assertIsNone(trader.position)
            self.assertIn("live_stop_loss", trader.snapshot()["trade_message"])
            logs = _read_decision_logs(Path(tmpdir))
            self.assertTrue(any(row["event"] == "order_submitted" and row["side"] == "sell" for row in logs))

    def test_live_direct_exit_defers_stop_during_entry_grace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 0)
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 100.0,
                "entry_time": (now - timedelta(seconds=30)).isoformat(sep=" "),
            }
            trader.bars = [StockBar("005930", now, 99.0, 99.0, 98.5, 98.8, 1000)]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy)

            self.assertFalse(sold)
            self.assertEqual(client.orders, [])
            self.assertIsNotNone(trader.position)

    def test_live_sell_keeps_estimated_cash_when_balance_cash_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01, take_profit_pct=0.005)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 0)
            trader.cash = 900_000
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 101.0,
                "entry_time": (now - timedelta(minutes=10)).isoformat(sep=" "),
            }
            trader.bars = [StockBar("005930", now, 101.0, 101.2, 100.9, 101.0, 1000)]
            client = FakeDomesticBalanceOrderClient(cash=900_000, holdings=[])

            sold = trader._try_live_direct_exit(client, now, strategy)

            expected_cash = round(900_000 + (10 * 101.0) - (10 * 101.0 * (strategy.commission_rate + strategy.sell_tax_rate + strategy.slippage_rate)), 2)
            self.assertTrue(sold)
            self.assertIsNone(trader.position)
            self.assertEqual(trader.cash, expected_cash)

    def test_live_direct_exit_ignores_pre_entry_low_on_entry_bar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", bar_minutes=5),
                strategy,
                report_dir=Path(tmpdir),
            )
            bar_start = datetime(2026, 4, 30, 10, 0)
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 100.0,
                "entry_time": (bar_start + timedelta(minutes=2)).isoformat(sep=" "),
            }
            trader.bars = [StockBar("005930", bar_start, 100.0, 101.0, 98.5, 100.2, 1000)]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, bar_start + timedelta(minutes=3), strategy)

            self.assertFalse(sold)
            self.assertEqual(client.orders, [])
            self.assertIsNotNone(trader.position)

    def test_live_direct_exit_uses_break_even_after_partial_profit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", bar_minutes=5),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 10)
            trader.position = {
                "symbol": "005930",
                "shares": 5,
                "entry_price": 100.0,
                "highest_price": 102.0,
                "partial_stages": 1,
                "entry_time": "2026-04-30 10:00:00",
            }
            trader.bars = [StockBar("005930", now, 100.5, 100.8, 99.8, 99.9, 1000)]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy)

            self.assertTrue(sold)
            self.assertEqual(client.orders[0]["side"], "sell")
            self.assertIn("live_break_even_stop", trader.snapshot()["trade_message"])

    def test_live_direct_exit_tracks_each_position_independently(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.01)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", max_positions=3),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 10, 0)
            trader.positions = [
                {"symbol": "005930", "shares": 10, "entry_price": 100.0, "highest_price": 100.0},
                {"symbol": "000660", "shares": 8, "entry_price": 100.0, "highest_price": 101.0},
            ]
            trader.bars = [
                StockBar("005930", now, 98.8, 99.0, 98.5, 98.8, 1000),
                StockBar("000660", now, 101.0, 101.5, 100.5, 101.0, 1000),
            ]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy, {"005930", "000660"})

            self.assertTrue(sold)
            self.assertEqual(client.orders[0]["symbol"], "005930")
            self.assertEqual(len(trader.positions), 1)
            self.assertEqual(trader.positions[0]["symbol"], "000660")

    def test_live_direct_exit_uses_time_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), initial_capital=1_000_000, stop_loss_pct=0.02, take_profit_pct=0.03, time_stop_minutes=15)
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "domestic", "mode": "live", "account_no": "12345678"}),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 30)
            now = start + timedelta(minutes=16)
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 100.0,
                "entry_time": start.isoformat(sep=" "),
            }
            trader.bars = [StockBar("005930", now, 100.4, 100.8, 100.2, 100.5, 1000)]
            client = FakeDomesticOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy, {"005930"})

            self.assertTrue(sold)
            self.assertEqual(client.orders[0]["side"], "sell")
            self.assertIsNone(trader.position)
            self.assertIn("live_time_stop", trader.snapshot()["trade_message"])

    def test_domestic_run_cycle_force_exits_position_after_selection_drops_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000_000, force_exit_time="15:15")
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678", auto_select=False),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 15, 16)
            trader.active_symbols = ["000660"]
            trader.position = {
                "symbol": "005930",
                "shares": 10,
                "entry_price": 100.0,
                "highest_price": 101.0,
                "entry_time": "2026-04-30 10:00:00",
            }
            client = FakeDomesticQuoteOrderClient()

            trader._run_cycle(client, now)

            self.assertEqual(client.orders[0]["side"], "sell")
            self.assertEqual(client.orders[0]["symbol"], "005930")
            self.assertIsNone(trader.position)
            self.assertIn("live_force_exit", trader.snapshot()["trade_message"])

    def test_position_symbol_is_polled_even_after_selection_drops_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                StockScannerConfig(),
                report_dir=Path(tmpdir),
            )
            trader.active_symbols = ["AAPL", "MSFT"]
            trader.position = {"symbol": "IREN", "shares": 6, "entry_price": 43.64, "highest_price": 44.4}

            self.assertEqual(trader._symbols_to_poll()[0], "IREN")
            self.assertIn("AAPL", trader._symbols_to_poll())

    def test_overseas_force_exit_sells_position_after_selection_drops_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000, force_exit_time="15:50")
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 4, 30, 15, 51)
            trader.active_symbols = ["AAPL", "MSFT"]
            trader.position = {
                "symbol": "IREN",
                "shares": 6,
                "entry_price": 43.64,
                "highest_price": 44.4,
                "entry_time": "2026-04-30 06:29:30",
            }
            trader.bars = [StockBar("IREN", now, 44.2, 44.3, 44.1, 44.2, 1000)]
            client = FakeOverseasOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy, {"IREN"})

            self.assertTrue(sold)
            self.assertEqual(client.orders[0]["symbol"], "IREN")
            self.assertIsNone(trader.position)
            self.assertIn("live_force_exit", trader.snapshot()["trade_message"])

    def test_overseas_overnight_position_exits_on_next_tradable_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = StockScannerConfig(initial_capital=1_000, force_exit_time="15:50")
            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                strategy,
                report_dir=Path(tmpdir),
            )
            now = datetime(2026, 5, 1, 9, 35)
            trader.position = {
                "symbol": "IREN",
                "shares": 6,
                "entry_price": 43.64,
                "highest_price": 44.4,
                "entry_time": "2026-04-30 06:29:30",
            }
            trader.bars = [StockBar("IREN", now, 43.9, 44.0, 43.8, 43.9, 1000)]
            client = FakeOverseasOrderClient()

            sold = trader._try_live_direct_exit(client, now, strategy, {"IREN"})

            self.assertTrue(sold)
            self.assertIsNone(trader.position)
            logs = _read_decision_logs(Path(tmpdir))
            self.assertTrue(any(row["reason"] == "live_overnight_force_exit" for row in logs if row["event"] == "order_submitted"))

    def test_open_position_is_restored_from_trade_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-04-30 06:29:30,BUY,IREN,6,43.64,261.84,0.13,0.0,405.12,live_premarket_momentum_entry,live,{},key\n",
                encoding="utf-8",
            )

            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                StockScannerConfig(initial_capital=667.09),
                report_dir=report_dir,
            )

            self.assertEqual(trader.position["symbol"], "IREN")
            self.assertEqual(trader.position["shares"], 6)
            self.assertEqual(trader.cash, 405.12)

    def test_multiple_open_positions_are_restored_from_trade_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-04-30 06:29:30,BUY,IREN,6,43.64,261.84,0.13,0.0,738.03,live_premarket_momentum_entry,live,{},key1\n"
                "2026-04-30 06:35:30,BUY,AAPL,2,170.00,340.00,0.17,0.0,397.86,live_overseas_momentum_entry,live,{},key2\n"
                "2026-04-30 06:40:30,SELL_ALL,IREN,6,44.00,264.00,0.13,2.03,661.73,live_take_profit,live,{},key3\n",
                encoding="utf-8",
            )

            trader = LiveTrader(
                LiveConfig.from_dict({"market": "overseas", "mode": "live", "account_no": "12345678"}),
                StockScannerConfig(initial_capital=1_000),
                report_dir=report_dir,
            )

            self.assertEqual(len(trader.positions), 1)
            self.assertEqual(trader.positions[0]["symbol"], "AAPL")
            self.assertEqual(trader.cash, 661.73)

    def test_live_direct_entry_rejections_are_logged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = replace(StockScannerConfig(), observation_minutes=5)
            trader = LiveTrader(
                LiveConfig(mode="live", account_no="12345678"),
                strategy,
                report_dir=Path(tmpdir),
            )
            start = datetime(2026, 4, 30, 9, 0)
            trader.active_symbols = ["005930"]
            trader.bars = [
                StockBar("005930", start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1),
                StockBar("005930", start, 100.0, 100.0, 100.0, 100.0, 1000),
                StockBar("005930", start + timedelta(minutes=5), 100.0, 100.1, 99.9, 100.0, 1000),
                StockBar("005930", start + timedelta(minutes=10), 100.0, 100.1, 99.9, 100.0, 1000),
            ] + _domestic_proxy_bars(start)

            entered = trader._try_live_direct_entry(FakeDomesticOrderClient(), start + timedelta(minutes=11), strategy, {}, [])

            self.assertFalse(entered)
            logs = _read_decision_logs(Path(tmpdir))
            self.assertTrue(any(row["event"] == "entry_rejected" for row in logs))

    def test_price_zero_logs_kis_response_summary(self):
        class ZeroPriceClient:
            def inquire_price(self, symbol):
                return {
                    "rt_cd": "0",
                    "msg_cd": "MCA00000",
                    "msg1": "정상처리 되었습니다.",
                    "output": {
                        "stck_prpr": "0",
                        "stck_oprc": "0",
                        "acml_vol": "0",
                    },
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            trader = LiveTrader(
                LiveConfig(auto_select=False),
                StockScannerConfig(),
                report_dir=Path(tmpdir),
            )
            trader.active_symbols = ["005930"]

            trader._run_cycle(ZeroPriceClient(), datetime(2026, 4, 30, 10, 0))

            logs = _read_decision_logs(Path(tmpdir))
            cycle = next(row for row in logs if row["event"] == "cycle")
            error = cycle["price_errors"][0]
            self.assertEqual(error["symbol"], "005930")
            self.assertEqual(error["error"], "price<=0")
            self.assertEqual(error["kis_response"]["rt_cd"], "0")
            self.assertEqual(error["kis_response"]["msg_cd"], "MCA00000")
            self.assertIn("stck_prpr", error["kis_response"]["output_keys"])
            self.assertEqual(trader.snapshot()["price_error_count"], 5)


class FakeOverseasRankClient:
    def overseas_trade_value_rank(self, **kwargs):
        return {
            "output2": [
                {"symb": "AAPL", "name": "Apple Inc", "tamt": "3500000000"},
                {"symb": "TSLA", "name": "Tesla Inc", "tamt": "2800000000"},
                {"symb": "QQQ", "name": "Invesco QQQ Trust", "tamt": "9000000000"},
            ]
        }

    def overseas_trade_volume_rank(self, **kwargs):
        return {"output2": [{"symb": "AAPL"}, {"symb": "TSLA"}]}

    def overseas_updown_rate_rank(self, **kwargs):
        return {"output2": [{"symb": "AAPL"}, {"symb": "TSLA"}]}

    def overseas_volume_surge_rank(self, **kwargs):
        return {"output2": [{"symb": "AAPL"}, {"symb": "TSLA"}]}

    def overseas_volume_power_rank(self, **kwargs):
        return {"output2": [{"symb": "AAPL", "powr": "155"}, {"symb": "TSLA", "powr": "130"}]}

    def inquire_overseas_price(self, exchange_code, symbol):
        prices = {
            "AAPL": {"last": "171.25", "open": "170.00", "high": "176.00", "low": "168.50", "tvol": "25000000", "tamt": "4200000000", "base": "165.00"},
            "TSLA": {"last": "252.00", "open": "249.00", "high": "260.00", "low": "247.00", "tvol": "18000000", "tamt": "4600000000", "base": "244.00"},
        }
        return {"output": prices[symbol]}


class WeakOverseasRankClient(FakeOverseasRankClient):
    def inquire_overseas_price(self, exchange_code, symbol):
        return {
            "output": {
                "last": "100.00",
                "open": "100.00",
                "high": "100.20",
                "low": "99.90",
                "tvol": "1000",
                "tamt": "100000",
                "base": "100.00",
            }
        }


class FlakyOverseasPriceClient(FakeOverseasRankClient):
    def inquire_overseas_price(self, exchange_code, symbol):
        if symbol == "AAPL":
            raise RuntimeError("temporary quote error")
        return super().inquire_overseas_price(exchange_code, symbol)


class EmptyOverseasRankClient:
    def overseas_trade_value_rank(self, **kwargs):
        return {"output2": []}

    def overseas_trade_volume_rank(self, **kwargs):
        return {"output2": []}

    def overseas_updown_rate_rank(self, **kwargs):
        return {"output2": []}

    def overseas_volume_surge_rank(self, **kwargs):
        return {"output2": []}

    def overseas_volume_power_rank(self, **kwargs):
        return {"output2": []}


class EmptyDomesticRankClient:
    def __init__(self):
        self.calls = 0

    def volume_rank(self, **kwargs):
        self.calls += 1
        return {"output": []}

    def fluctuation_rank(self, **kwargs):
        self.calls += 1
        return {"output": []}

    def volume_power_rank(self):
        self.calls += 1
        return {"output": []}

    def inquire_price(self, symbol):
        raise AssertionError("no symbols should be polled")


class FakeDomesticOrderClient:
    def __init__(self):
        self.orders = []

    def order_cash(self, **kwargs):
        self.orders.append(kwargs)
        return {"rt_cd": "0", "msg1": "정상"}


class FakeDomesticPsblOrderClient(FakeDomesticOrderClient):
    def __init__(self, orderable_quantity):
        super().__init__()
        self.orderable_quantity = orderable_quantity
        self.psbl_requests = []

    def inquire_psbl_order(self, *args, **kwargs):
        self.psbl_requests.append({"args": args, **kwargs})
        return {
            "rt_cd": "0",
            "msg1": "정상",
            "output": {
                "nrcvb_buy_qty": str(self.orderable_quantity),
                "nrcvb_buy_amt": str(self.orderable_quantity * 100000),
                "psbl_qty_calc_unpr": "130000",
                "max_buy_qty": "99",
            },
        }


class FakeDomesticBalanceOrderClient(FakeDomesticOrderClient):
    def __init__(self, cash, holdings):
        super().__init__()
        self.cash = cash
        self.holdings = holdings

    def inquire_balance(self, **kwargs):
        _ = kwargs
        return {
            "rt_cd": "0",
            "msg1": "정상",
            "output1": self.holdings,
            "output2": {"dnca_tot_amt": str(self.cash), "prvs_rcdl_excc_amt": str(self.cash)},
        }


class FakeDomesticQuoteOrderClient(FakeDomesticOrderClient):
    def inquire_price(self, symbol):
        prices = {
            "005930": "101.00",
            "000660": "95.00",
        }
        price = prices.get(symbol, "100.00")
        return {
            "output": {
                "stck_prpr": price,
                "stck_oprc": price,
                "stck_hgpr": price,
                "stck_lwpr": price,
                "acml_vol": "1000",
                "acml_tr_pbmn": "100000000",
                "prdy_ctrt": "1.0",
            }
        }


class FakeStartupTokenClient:
    access_token_expires_at = "2026-05-01T12:00:00+00:00"

    def __init__(self):
        self.token_checks = 0

    def ensure_token(self):
        self.token_checks += 1
        return "startup-token"


def _read_decision_logs(report_dir: Path):
    path = report_dir / "decision_log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _domestic_proxy_bars(start: datetime, bullish: bool = True) -> list[StockBar]:
    symbols = ("069500", "102110", "229200", "232080")
    closes = (101.0, 101.5, 101.8) if bullish else (99.5, 99.0, 98.7)
    bars: list[StockBar] = []
    for symbol in symbols:
        bars.append(StockBar(symbol, start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1))
        for idx, close in enumerate(closes):
            ts = start + timedelta(minutes=5 * idx)
            bars.append(StockBar(symbol, ts, close, close + 0.2, close - 0.2, close, 1000 + idx * 100))
    return bars


def _tone_bars(symbols, start: datetime, closes: list[float]) -> list[StockBar]:
    bars = []
    for symbol in symbols:
        bars.append(StockBar(symbol, start - timedelta(days=1), 100.0, 100.0, 100.0, 100.0, 1))
        for idx, close in enumerate(closes):
            bars.append(StockBar(symbol, start + timedelta(minutes=idx), close, close, close, close, 1000))
    return bars


class FakeOverseasOrderClient:
    def __init__(self):
        self.orders = []

    def order_overseas(self, **kwargs):
        self.orders.append(kwargs)
        return {"rt_cd": "0", "msg1": "정상"}


if __name__ == "__main__":
    unittest.main()
