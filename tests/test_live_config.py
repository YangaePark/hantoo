import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from semibot_backtester.stock_scanner import StockBar, StockScannerConfig
from semibot_live.trader import LiveConfig, LiveTrader


class LiveConfigTests(unittest.TestCase):
    def test_auto_select_defaults_on(self):
        config = LiveConfig.from_dict({})

        self.assertTrue(config.auto_select)
        self.assertEqual(config.max_symbols, 20)
        self.assertEqual(config.seed_capital, 1_000_000.0)
        self.assertEqual(config.seed_source, "manual")

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

    def test_manual_watchlist_payload_is_ignored(self):
        config = LiveConfig.from_dict(
            {
                "auto_select": False,
                "watchlist": "005930,000660\n042700",
            }
        )

        self.assertTrue(config.auto_select)
        self.assertFalse(hasattr(config, "watchlist"))

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


if __name__ == "__main__":
    unittest.main()
