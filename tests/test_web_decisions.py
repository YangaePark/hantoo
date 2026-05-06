import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import semibot_web.server as server
from semibot_live.trader import DEFAULT_MARKET


class WebDecisionLogTests(unittest.TestCase):
    def test_load_live_decisions_returns_recent_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            (report_dir / "decision_log.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"timestamp": "2026-04-30 09:00:00", "event": "cycle", "trade_message": "first"}),
                        json.dumps({"timestamp": "2026-04-30 09:05:00", "event": "entry_skip", "reason": "daily_trade_limit"}),
                        json.dumps({"timestamp": "2026-04-30 09:10:00", "event": "order_submitted", "symbol": "005930"}),
                    ]
                ),
                encoding="utf-8",
            )
            original_live_report_dir = server.live_report_dir
            try:
                server.live_report_dir = lambda market: report_dir

                data = server.load_live_decisions(DEFAULT_MARKET, limit=2)
            finally:
                server.live_report_dir = original_live_report_dir

            self.assertEqual(data["report"], report_dir.name)
            self.assertEqual([row["event"] for row in data["decisions"]], ["entry_skip", "order_submitted"])

    def test_load_report_includes_tone_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "live_trading"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "metrics.json").write_text(json.dumps({"strategy": "live"}), encoding="utf-8")
            (report_dir / "equity_curve.csv").write_text("datetime,cash,symbol,shares,mark_price,equity,drawdown,paused\n", encoding="utf-8")
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-05-04 09:20:31,SELL_ALL,090460,15,35050,525750,499.46,-7249.46,1000000,live_stop_loss,live,{},k1\n",
                encoding="utf-8",
            )
            (report_dir / "decision_log.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"timestamp": "2026-05-04 09:10:00", "event": "cycle", "strategy_tone": "neutral"}),
                        json.dumps({"timestamp": "2026-05-04 09:11:00", "event": "cycle", "strategy_tone": "conservative"}),
                        json.dumps({"timestamp": "2026-05-04 09:12:00", "event": "entry_skip", "reason": "stop_loss_reentry_cooldown"}),
                    ]
                ),
                encoding="utf-8",
            )

            original_reports_root = server.REPORTS_ROOT
            try:
                server.REPORTS_ROOT = root
                data = server.load_report("live_trading")
            finally:
                server.REPORTS_ROOT = original_reports_root

            summary = data.get("tone_summary", {})
            self.assertEqual(summary.get("latest_tone"), "conservative")
            self.assertEqual(summary.get("tone_switches"), 1)
            self.assertEqual(summary.get("stop_loss_reentry_blocks"), 1)
            self.assertGreater(summary.get("estimated_avoided_loss", 0), 0)

    def test_load_report_normalizes_metrics_from_equity_curve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "live_trading"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "metrics.json").write_text(
                json.dumps({"strategy": "live", "initial_capital": 100, "final_equity": 100, "total_return_pct": 0}),
                encoding="utf-8",
            )
            (report_dir / "equity_curve.csv").write_text(
                "datetime,cash,symbol,shares,mark_price,equity,drawdown,paused\n"
                "2026-05-04 09:00,500,,0,0,500,0,0\n"
                "2026-05-04 09:01,550,,0,0,550,0,0\n",
                encoding="utf-8",
            )
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-05-04 09:00:10,BUY,AAPL,1,500,500,1,0,0,entry,live,{},k1\n"
                "2026-05-04 09:01:10,SELL_ALL,AAPL,1,550,550,1,48,550,exit,live,{},k2\n",
                encoding="utf-8",
            )

            original_reports_root = server.REPORTS_ROOT
            try:
                server.REPORTS_ROOT = root
                data = server.load_report("live_trading")
            finally:
                server.REPORTS_ROOT = original_reports_root

            self.assertEqual(data["metrics"]["initial_capital"], 500)
            self.assertEqual(data["metrics"]["final_equity"], 550)
            self.assertEqual(data["metrics"]["total_return_pct"], 10.0)
            self.assertEqual(data["metrics"]["trades"], 2)
            self.assertEqual(data["metrics"]["explicit_trade_cost"], 2)

    def test_load_report_includes_daily_entry_and_pnl_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "live_trading_domestic_surge"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "metrics.json").write_text(json.dumps({"strategy": "live"}), encoding="utf-8")
            (report_dir / "equity_curve.csv").write_text(
                "datetime,cash,symbol,shares,mark_price,equity,drawdown,paused\n"
                "2026-05-05 15:10,1000000,,0,0,1000000,0,0\n"
                "2026-05-06 09:05,1000000,,0,0,1000000,0,0\n"
                "2026-05-06 10:00,1015000,,0,0,1015000,0,0\n",
                encoding="utf-8",
            )
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n"
                "2026-05-06 09:06:00,BUY,005930,10,70000,700000,100,0,300000,entry,live,{},k1\n"
                "2026-05-06 09:30:00,BUY,000660,5,150000,750000,100,0,250000,entry,live,{},k2\n"
                "2026-05-06 10:00:00,SELL_ALL,005930,10,71500,715000,100,14900,1015000,exit,live,{},k3\n",
                encoding="utf-8",
            )

            original_reports_root = server.REPORTS_ROOT
            try:
                server.REPORTS_ROOT = root
                data = server.load_report("live_trading_domestic_surge")
            finally:
                server.REPORTS_ROOT = original_reports_root

            summary = server._daily_summary("domestic_surge", data["trades"], data["daily_pnl"], today=date(2026, 5, 6))
            self.assertEqual(summary["entry_limit"], 3)
            self.assertEqual(summary["entries_used"], 2)
            self.assertEqual(summary["entry_remaining"], 1)
            self.assertEqual(summary["pnl_amount"], 15000)
            self.assertEqual(summary["return_pct"], 1.5)
            self.assertEqual(data["daily_pnl"][-1]["pnl_amount"], 15000)

    def test_current_snapshot_uses_final_equity_as_cash_without_equity_curve(self):
        snapshot = server.current_snapshot({"final_equity": 200000}, [], [])

        self.assertEqual(snapshot["equity"], 200000)
        self.assertEqual(snapshot["cash"], 200000)

    def test_daily_pnl_uses_realized_pnl_when_equity_is_flat(self):
        equity = [
            {"datetime": "2026-05-04 09:00", "equity": "1000"},
            {"datetime": "2026-05-04 15:10", "equity": "1000"},
        ]
        trades = [
            {"timestamp": "2026-05-04 09:10:00", "action": "BUY", "realized_pnl": "0"},
            {"timestamp": "2026-05-04 09:30:00", "action": "SELL_ALL", "realized_pnl": "-25.5"},
        ]

        rows = server._daily_pnl_series(equity, trades)

        self.assertEqual(rows[0]["pnl_amount"], -25.5)
        self.assertEqual(rows[0]["return_pct"], -2.55)

    def test_overseas_daily_summary_uses_market_date_rows(self):
        trades = [{"timestamp": "2026-05-05 09:35:00", "action": "BUY"}]
        daily_pnl = [{"date": "2026-05-05", "pnl_amount": "12.5", "return_pct": "1.25"}]

        summary = server._daily_summary("overseas", trades, daily_pnl, today=date(2026, 5, 5))

        self.assertEqual(summary["date"], "2026-05-05")
        self.assertEqual(summary["entries_used"], 1)
        self.assertEqual(summary["pnl_amount"], 12.5)

    def test_backtest_report_keeps_stored_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "sample_backtest"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "metrics.json").write_text(
                json.dumps({"strategy": "backtest", "initial_capital": 100, "final_equity": 100, "total_return_pct": 0}),
                encoding="utf-8",
            )
            (report_dir / "equity_curve.csv").write_text(
                "datetime,cash,symbol,shares,mark_price,equity,drawdown,paused\n"
                "2026-05-04 09:00,500,,0,0,500,0,0\n",
                encoding="utf-8",
            )
            (report_dir / "trades.csv").write_text(
                "timestamp,action,symbol,shares,price,gross,cost,realized_pnl,cash_after,reason,mode,order_response,trade_key\n",
                encoding="utf-8",
            )

            original_reports_root = server.REPORTS_ROOT
            try:
                server.REPORTS_ROOT = root
                data = server.load_report("sample_backtest")
            finally:
                server.REPORTS_ROOT = original_reports_root

            self.assertEqual(data["metrics"]["final_equity"], 100)


if __name__ == "__main__":
    unittest.main()
