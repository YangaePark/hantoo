import unittest

from semibot_live.trader import LiveConfig


class LiveConfigTests(unittest.TestCase):
    def test_auto_select_defaults_on(self):
        config = LiveConfig.from_dict({})

        self.assertTrue(config.auto_select)
        self.assertEqual(config.watchlist, [])
        self.assertEqual(config.max_symbols, 20)

    def test_manual_watchlist_parses_lines_and_commas(self):
        config = LiveConfig.from_dict(
            {
                "auto_select": False,
                "watchlist": "005930,000660\n042700",
            }
        )

        self.assertFalse(config.auto_select)
        self.assertEqual(config.watchlist, ["005930", "000660", "042700"])


if __name__ == "__main__":
    unittest.main()
