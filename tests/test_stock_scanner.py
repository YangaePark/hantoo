from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from semibot_backtester.stock_scanner import StockBar, StockScannerBacktester, StockScannerConfig


class StockScannerBacktesterTest(unittest.TestCase):
    def test_scanner_runs(self) -> None:
        config = StockScannerConfig(
            observation_minutes=15,
            volume_sma=3,
            volume_factor=0.8,
            atr_period=3,
            min_atr_pct=0.001,
            top_value_rank=2,
            require_spread=True,
        )
        result = StockScannerBacktester(config).run(synthetic_bars())

        self.assertGreater(result.metrics["final_equity"], 0)
        self.assertEqual(result.metrics["symbols"], 3)
        self.assertTrue(result.equity_curve)
        self.assertIn("explicit_trade_cost", result.metrics)

    def test_scanner_accepts_intraday_move_after_small_open_gap(self) -> None:
        config = StockScannerConfig(
            initial_capital=1_000_000,
            observation_minutes=10,
            top_value_rank=1,
            gap_min_pct=0.02,
            gap_max_pct=0.08,
            volume_sma=3,
            volume_factor=0.8,
            atr_period=3,
            min_atr_pct=0.001,
            max_atr_pct=0.1,
            max_extension_pct=0.2,
            vi_proxy_move_pct=0.2,
        )
        result = StockScannerBacktester(config).run(intraday_breakout_after_small_open_gap())

        self.assertTrue(any(trade.action == "BUY" for trade in result.trades))

    def test_partial_sell_keeps_remaining_average_cost(self) -> None:
        config = StockScannerConfig(commission_bps=0.0, slippage_bps=0.0, sell_tax_bps=0.0)
        backtester = StockScannerBacktester(config)
        trades = []
        bar = StockBar("AAA", datetime(2026, 1, 5, 10, 0), 110.0, 110.0, 110.0, 110.0, 1000)

        cash, avg_cost = backtester._sell(bar, "SELL_PARTIAL", 50, 0.0, 100.0, trades, "partial_take_profit")

        self.assertEqual(cash, 5500.0)
        self.assertEqual(avg_cost, 100.0)
        self.assertEqual(trades[0].realized_pnl, 500.0)


def synthetic_bars() -> list[StockBar]:
    bars: list[StockBar] = []
    symbols = ["AAA", "BBB", "CCC"]
    start = datetime(2026, 1, 5, 9, 0)
    previous = {"AAA": 10000.0, "BBB": 20000.0, "CCC": 15000.0}
    for day in range(3):
        session_start = start + timedelta(days=day)
        for symbol in symbols:
            price = previous[symbol] * (1.04 if symbol != "CCC" else 1.01)
            for idx in range(30):
                ts = session_start + timedelta(minutes=5 * idx)
                price += 35 if symbol == "AAA" and idx > 4 else 8
                bars.append(
                    StockBar(
                        symbol=symbol,
                        timestamp=ts,
                        open=price * 0.998,
                        high=price * 1.006,
                        low=price * 0.994,
                        close=price,
                        volume=200000 + idx * 4000 if symbol == "AAA" else 50000 + idx * 500,
                        spread_pct=0.001,
                    )
                )
            previous[symbol] = price
    return bars


def intraday_breakout_after_small_open_gap() -> list[StockBar]:
    bars: list[StockBar] = [StockBar("AAA", datetime(2026, 1, 4, 15, 30), 100.0, 100.0, 100.0, 100.0, 1)]
    start = datetime(2026, 1, 5, 9, 0)
    prices = [100.4, 101.0, 101.8, 102.4, 103.2, 104.0, 104.8, 105.5]
    for idx, close in enumerate(prices):
        ts = start + timedelta(minutes=5 * idx)
        bars.append(
            StockBar(
                "AAA",
                ts,
                close * 0.998,
                close * 1.006,
                close * 0.994,
                close,
                200000 + idx * 10000,
                spread_pct=0.001,
            )
        )
    return bars


if __name__ == "__main__":
    unittest.main()
