import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
