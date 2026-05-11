import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from semibot_live.kis import KisClient, KisCredentials


class FakeKisClient(KisClient):
    def __init__(self, credentials, credentials_path=None):
        super().__init__(credentials, credentials_path)
        self.refreshes = 0

    def refresh_token(self) -> str:
        self.refreshes += 1
        self.access_token = "new-token"
        self.access_token_expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        self._save_token()
        return self.access_token


class RecordingKisClient(KisClient):
    def __init__(self):
        super().__init__(KisCredentials(app_key="key", app_secret="secret"))
        self.requests = []

    def _request(self, method, path, *, body=None, tr_id=None, auth=True, hash_body=False):
        self.requests.append({"method": method, "path": path, "body": body, "tr_id": tr_id})
        return {"rt_cd": "0", "msg1": "ok"}


class KisTokenTests(unittest.TestCase):
    def test_expiring_token_refreshes_and_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "kis.local.json"
            path.write_text(
                json.dumps(
                    {
                        "app_key": "key",
                        "app_secret": "secret",
                        "base_url": "https://example.com",
                        "access_token": "old-token",
                        "access_token_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            client = FakeKisClient(KisCredentials.from_file(path), credentials_path=path)

            self.assertEqual(client.ensure_token(), "new-token")
            self.assertEqual(client.refreshes, 1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["access_token"], "new-token")
            self.assertIn("access_token_expires_at", saved)

    def test_valid_token_is_reused(self):
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        client = FakeKisClient(
            KisCredentials(
                app_key="key",
                app_secret="secret",
                access_token="valid-token",
                access_token_expires_at=expires_at,
            )
        )

        self.assertEqual(client.ensure_token(), "valid-token")
        self.assertEqual(client.refreshes, 0)

    def test_json_token_error_is_detected(self):
        from semibot_live.kis import _looks_like_token_error

        self.assertTrue(_looks_like_token_error({"rt_cd": "-1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token입니다"}))
        self.assertFalse(_looks_like_token_error({"rt_cd": "0", "msg_cd": "", "msg1": "정상"}))

    def test_balance_response_is_parsed(self):
        from semibot_live.kis import parse_balance_response

        parsed = parse_balance_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output1": [
                    {
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "hldg_qty": "3",
                        "pchs_avg_pric": "70000",
                        "prpr": "72000",
                        "evlu_amt": "216000",
                        "evlu_pfls_amt": "6000",
                        "evlu_pfls_rt": "2.85",
                    }
                ],
                "output2": [
                    {
                        "dnca_tot_amt": "1200000",
                        "prvs_rcdl_excc_amt": "1100000",
                        "tot_evlu_amt": "1416000",
                        "scts_evlu_amt": "216000",
                        "evlu_pfls_smtl_amt": "6000",
                        "evlu_pfls_rt": "0.42",
                    }
                ],
            }
        )

        self.assertEqual(parsed["cash"], 1_200_000)
        self.assertEqual(parsed["withdrawable_cash"], 1_100_000)
        self.assertEqual(parsed["total_evaluation"], 1_416_000)
        self.assertEqual(parsed["holdings"][0]["symbol"], "005930")

    def test_domestic_psbl_order_response_prefers_cash_only_quantity(self):
        from semibot_live.kis import parse_domestic_psbl_order_response

        parsed = parse_domestic_psbl_order_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output": {
                    "nrcvb_buy_qty": "0",
                    "max_buy_qty": "9",
                    "nrcvb_buy_amt": "0",
                    "max_buy_amt": "900000",
                    "psbl_qty_calc_unpr": "130000",
                },
            }
        )

        self.assertEqual(parsed["orderable_quantity"], 0)
        self.assertEqual(parsed["orderable_cash"], 0)
        self.assertEqual(parsed["calculation_price"], 130000)

    def test_domestic_psbl_order_request_uses_market_order_query(self):
        client = RecordingKisClient()

        client.inquire_psbl_order(
            "12345678",
            "01",
            symbol="005930",
            price=0,
            order_division="01",
            live=True,
        )

        request = client.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["tr_id"], "TTTC8908R")
        self.assertIn("/uapi/domestic-stock/v1/trading/inquire-psbl-order?", request["path"])
        self.assertIn("PDNO=005930", request["path"])
        self.assertIn("ORD_DVSN=01", request["path"])

    def test_domestic_price_response_parses_spread(self):
        from semibot_live.kis import parse_price_response

        parsed = parse_price_response(
            {
                "output": {
                    "stck_prpr": "70000",
                    "stck_oprc": "69000",
                    "stck_hgpr": "70500",
                    "stck_lwpr": "68800",
                    "acml_vol": "1000000",
                    "acml_tr_pbmn": "70000000000",
                    "prdy_ctrt": "3.5",
                    "bidp1": "69900",
                    "askp1": "70000",
                }
            }
        )

        self.assertEqual(parsed["bid"], 69900)
        self.assertEqual(parsed["ask"], 70000)
        self.assertGreater(parsed["spread_pct"], 0)

    def test_overseas_price_response_is_parsed(self):
        from semibot_live.kis import parse_overseas_price_response

        parsed = parse_overseas_price_response(
            {
                "output": {
                    "last": "171.25",
                    "open": "170.00",
                    "high": "172.00",
                    "low": "169.50",
                    "tvol": "12345",
                    "tamt": "2111111.25",
                    "base": "168.00",
                }
            }
        )

        self.assertEqual(parsed["price"], 171.25)
        self.assertEqual(parsed["open"], 170.0)
        self.assertGreater(parsed["prev_rate_pct"], 0)

    def test_nasdaq_order_price_is_limited_to_two_decimals(self):
        client = RecordingKisClient()

        client.order_overseas(
            account_no="12345678",
            product_code="01",
            exchange_code="NASD",
            symbol="TEAM",
            side="buy",
            quantity=2,
            price=95.1277,
            live=True,
        )

        self.assertEqual(client.requests[0]["body"]["OVRS_ORD_UNPR"], "95.13")

    def test_overseas_balance_response_is_parsed(self):
        from semibot_live.kis import parse_overseas_balance_response

        parsed = parse_overseas_balance_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output1": [
                    {
                        "ovrs_pdno": "AAPL",
                        "ovrs_item_name": "Apple",
                        "ovrs_cblc_qty": "2",
                        "pchs_avg_pric": "150.25",
                        "now_pric2": "171.25",
                        "ovrs_stck_evlu_amt": "342.50",
                        "frcr_evlu_pfls_amt": "42.00",
                        "evlu_pfls_rt": "13.98",
                    }
                ],
                "output2": {
                    "frcr_dncl_amt_2": "5000.00",
                    "frcr_drwg_psbl_amt_1": "4500.00",
                    "tot_evlu_amt": "5342.50",
                    "ovrs_stck_evlu_amt": "342.50",
                    "tot_evlu_pfls_amt": "42.00",
                    "tot_pftrt": "0.79",
                },
            }
        )

        self.assertEqual(parsed["cash"], 5000)
        self.assertEqual(parsed["withdrawable_cash"], 4500)
        self.assertEqual(parsed["holdings"][0]["symbol"], "AAPL")

    def test_overseas_balance_response_accepts_swapped_outputs(self):
        from semibot_live.kis import parse_overseas_balance_response

        parsed = parse_overseas_balance_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output1": {
                    "frcr_dncl_amt": "3200.00",
                    "frcr_drwg_psbl_amt": "3000.00",
                    "tot_asst_amt": "3542.50",
                },
                "output2": [
                    {
                        "ovrs_pdno": "MSFT",
                        "ovrs_item_name": "Microsoft",
                        "ovrs_cblc_qty": "1",
                        "pchs_avg_pric": "300.00",
                        "now_pric2": "342.50",
                        "ovrs_stck_evlu_amt": "342.50",
                    }
                ],
            }
        )

        self.assertEqual(parsed["cash"], 3200)
        self.assertEqual(parsed["withdrawable_cash"], 3000)
        self.assertEqual(parsed["total_evaluation"], 3542.5)
        self.assertEqual(parsed["holdings"][0]["symbol"], "MSFT")

    def test_overseas_margin_response_is_parsed_by_currency(self):
        from semibot_live.kis import parse_overseas_margin_response

        parsed = parse_overseas_margin_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output": [
                    {
                        "crcy_cd": "JPY",
                        "frcr_dncl_amt": "100000",
                        "frcr_drwg_psbl_amt": "90000",
                    },
                    {
                        "crcy_cd": "USD",
                        "frcr_dncl_amt_2": "7000.00",
                        "frcr_drwg_psbl_amt_1": "6500.00",
                    },
                ],
            },
            "USD",
        )

        self.assertEqual(parsed["cash"], 7000)
        self.assertEqual(parsed["withdrawable_cash"], 6500)
        self.assertEqual(parsed["total_evaluation"], 7000)

    def test_overseas_psamount_response_is_parsed(self):
        from semibot_live.kis import parse_overseas_psamount_response

        parsed = parse_overseas_psamount_response(
            {
                "rt_cd": "0",
                "msg1": "정상",
                "output": {
                    "ovrs_ord_psbl_amt": "1234.56",
                    "ovrs_max_ord_psbl_qty": "12",
                },
            }
        )

        self.assertEqual(parsed["cash"], 1234.56)
        self.assertEqual(parsed["withdrawable_cash"], 1234.56)
        self.assertIn("ovrs_ord_psbl_amt", parsed["debug_keys"])

    def test_overseas_rank_rows_and_symbols_are_parsed(self):
        from semibot_live.kis import parse_rank_rows, rank_row_symbol

        rows = parse_rank_rows({"output1": {"summary": "x"}, "output2": [{"symb": "AAPL"}, {"rsym": "DNASTSLA"}]})

        self.assertEqual(rank_row_symbol(rows[1]), "AAPL")
        self.assertEqual(rank_row_symbol(rows[2]), "DNASTSLA")

    def test_balance_max_seed_uses_larger_cash_value(self):
        from semibot_web.server import balance_max_seed

        self.assertEqual(balance_max_seed({"cash": 1_200_000, "withdrawable_cash": 900_000}), 1_200_000)
        self.assertEqual(balance_max_seed({"cash": 800_000, "withdrawable_cash": 1_100_000}), 1_100_000)


if __name__ == "__main__":
    unittest.main()
