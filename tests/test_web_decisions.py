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


if __name__ == "__main__":
    unittest.main()
