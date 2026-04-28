from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from semibot_backtester.intraday import IntradayBacktester, IntradayBar, IntradayConfig


class IntradayBacktesterTest(unittest.TestCase):
    def test_intraday_backtester_runs(self) -> None:
        bars = synthetic_intraday_bars()
        config = IntradayConfig(
            opening_range_minutes=15,
            fast_sma=3,
            slow_sma=6,
            volume_sma=4,
            volume_factor=0.5,
            max_trades_per_day=3,
        )

        result = IntradayBacktester(config).run(bars)

        self.assertGreater(result.metrics["final_equity"], 0)
        self.assertIn("explicit_trade_cost", result.metrics)
        self.assertEqual(result.metrics["sessions"], 3)
        self.assertTrue(result.equity_curve)


def synthetic_intraday_bars() -> list[IntradayBar]:
    bars: list[IntradayBar] = []
    start = datetime(2026, 1, 5, 9, 0)
    price = 30_000.0
    for day in range(3):
        session_start = start + timedelta(days=day)
        for idx in range(40):
            ts = session_start + timedelta(minutes=5 * idx)
            price += 25 if idx > 5 else 5
            bars.append(
                IntradayBar(
                    timestamp=ts,
                    open=price * 0.999,
                    high=price * 1.002,
                    low=price * 0.998,
                    close=price,
                    volume=100_000 + idx * 1000,
                )
            )
    return bars


if __name__ == "__main__":
    unittest.main()
