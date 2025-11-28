import datetime as dt
import unittest
from unittest.mock import MagicMock

from sab.data.kis_client import KISClient, KISCredentials


class KISClientOverseasHolidaysTests(unittest.TestCase):
    def setUp(self) -> None:
        creds = KISCredentials(
            app_key="test-key",
            app_secret="test-secret",
            base_url="https://example.com",
            env="demo",
        )
        # Session is unused in this test because we override _request
        self.client = KISClient(creds, session=MagicMock(), cache_dir=None)
        # Skip real token fetching
        self.client._access_token = "Bearer test"
        self.client._token_expiry = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    def test_overseas_holidays_builds_request_and_parses_output(self) -> None:
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "rt_cd": "0",
            "msg_cd": "00000",
            "msg1": "OK",
            "output": [
                {"TRD_DT": "20251127", "evnt_nm": "Thanksgiving", "open_yn": "N"},
            ],
        }

        # Intercept the actual HTTP call
        self.client._request = MagicMock(return_value=fake_resp)

        items = self.client.overseas_holidays(
            country_code="US",
            start_date="20251127",
            end_date="20251231",
        )

        # Verify request
        self.client._request.assert_called_once()
        method, url = self.client._request.call_args[0][:2]
        kwargs = self.client._request.call_args.kwargs

        self.assertEqual(method, "GET")
        self.assertEqual(url, self.client.creds.overseas_holiday_url)
        self.assertEqual(kwargs["params"]["TRAD_DT"], "20251127")

        # Verify parsing
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["evnt_nm"], "Thanksgiving")


if __name__ == "__main__":
    unittest.main()
