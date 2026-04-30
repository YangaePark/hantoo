import unittest
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig
from semibot_live.trader import DEFAULT_MARKET, OVERSEAS_MARKET, LiveConfig, LiveTrader, live_report_dir


class LiveConfigTests(unittest.TestCase):
    def test_auto_select_defaults_on(self):
        config = LiveConfig.from_dict({})

        self.assertTrue(config.auto_select)
        self.assertEqual(config.max_symbols, 20)
        self.assertEqual(config.selection_refresh_sec, 300)
        self.assertEqual(config.min_selection_hold_sec, 1800)
        self.assertEqual(config.min_bars_before_evaluate, 20)
        self.assertEqual(config.seed_capital, 1_000_000.0)
        self.assertEqual(config.seed_source, "manual")
        self.assertFalse(config.auto_start)

    def test_old_fast_selection_refresh_is_migrated(self):
        config = LiveConfig.from_dict({"selection_refresh_sec": 60, "min_selection_hold_sec": 600})

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
        config = LiveConfig.from_dict({"market": "overseas", "symbol": "aapl"})

        self.assertEqual(config.market, OVERSEAS_MARKET)
        self.assertEqual(config.symbol, "")
        self.assertTrue(config.auto_select)
        self.assertEqual(config.exchange_code, "NASD")
        self.assertEqual(config.price_exchange_code, "NAS")
        self.assertEqual(config.currency, "USD")
        self.assertEqual(config.seed_capital, 10_000.0)
        self.assertEqual(config.clock_offset_hours, -7)
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

    def test_overseas_premarket_strategy_is_stricter(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())
        strategy = trader._active_strategy(datetime(2026, 4, 30, 8, 0))

        self.assertEqual(trader._market_session(datetime(2026, 4, 30, 8, 0)), "premarket")
        self.assertEqual(strategy.observation_minutes, 30)
        self.assertLessEqual(strategy.max_position_pct, 0.5)
        self.assertGreaterEqual(strategy.volume_factor, 2.2)

    def test_domestic_live_strategy_is_more_active(self):
        trader = LiveTrader(LiveConfig(mode="live"), StockScannerConfig())
        strategy = trader._active_strategy(datetime(2026, 4, 30, 12, 0))

        self.assertEqual(strategy.observation_minutes, 10)
        self.assertEqual(strategy.top_value_rank, 8)
        self.assertLessEqual(strategy.gap_min_pct, 0.008)
        self.assertLessEqual(strategy.volume_factor, 1.3)

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

    def test_overseas_empty_rankings_fall_back_to_liquid_universe(self):
        config = LiveConfig.from_dict({"market": "overseas", "overseas_premarket_enabled": True})
        trader = LiveTrader(config, StockScannerConfig())

        candidates = trader._overseas_candidate_symbols(EmptyOverseasRankClient())

        self.assertIn("AAPL", candidates)
        self.assertIn("fallback", candidates["AAPL"]["_sources"])

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
                StockBar("005930", start, 101.0, 110.0, 100.5, 101.0, 1000),
                StockBar("005930", start + timedelta(minutes=5), 101.0, 102.0, 100.8, 102.0, 1100),
                StockBar("005930", start + timedelta(minutes=10), 102.0, 103.2, 101.8, 103.0, 1200),
                StockBar("005930", start + timedelta(minutes=15), 103.0, 104.5, 102.8, 104.2, 1500),
            ]
            client = FakeDomesticOrderClient()

            trader._evaluate(client, start + timedelta(minutes=16))

            self.assertEqual(len(client.orders), 1)
            self.assertEqual(client.orders[0]["side"], "buy")
            self.assertEqual(trader.position["symbol"], "005930")
            self.assertEqual(trader.snapshot()["orders"], 1)
            self.assertIn("live_momentum_entry", trader.snapshot()["trade_message"])

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


class FakeDomesticOrderClient:
    def __init__(self):
        self.orders = []

    def order_cash(self, **kwargs):
        self.orders.append(kwargs)
        return {"rt_cd": "0", "msg1": "정상"}


if __name__ == "__main__":
    unittest.main()
