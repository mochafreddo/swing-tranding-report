import datetime as dt
import tempfile
import unittest

from sab.data.holiday_cache import (
    HolidayEntry,
    lookup_holiday,
    merge_holidays,
)


class HolidayCacheTests(unittest.TestCase):
    def test_merge_handles_multiple_field_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            items = [
                {
                    "base_date": "20250101",
                    "base_event": "New Year",
                    "cntr_div_cd": "N",
                },
                {
                    "TRD_DT": "20250102",
                    "evnt_nm": "Normal Session",
                    "open_yn": "Y",
                },
                # Missing optional fields should not break merge
                {
                    "TRD_DT": "20250103",
                },
            ]

            merged = merge_holidays(tmpdir, "US", items)

            self.assertIn("20250101", merged)
            self.assertIn("20250102", merged)
            self.assertIn("20250103", merged)

            jan1 = merged["20250101"]
            self.assertIsInstance(jan1, HolidayEntry)
            self.assertEqual(jan1.note, "New Year")
            self.assertFalse(jan1.is_open)

            jan2 = merged["20250102"]
            self.assertEqual(jan2.note, "Normal Session")
            self.assertTrue(jan2.is_open)

            jan3 = merged["20250103"]
            self.assertIsNone(jan3.note)
            # default: treated as closed when flag missing
            self.assertFalse(jan3.is_open)

            looked_up = lookup_holiday(tmpdir, "US", dt.date(2025, 1, 2))
            self.assertIsNotNone(looked_up)
            assert looked_up is not None
            self.assertTrue(looked_up.is_open)


if __name__ == "__main__":
    unittest.main()
