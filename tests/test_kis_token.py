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


if __name__ == "__main__":
    unittest.main()
