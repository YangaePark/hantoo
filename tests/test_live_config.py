import unittest

from semibot_live.trader import LiveConfig


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


if __name__ == "__main__":
    unittest.main()
