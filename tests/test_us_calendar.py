import unittest

from sab.data.us_calendar import load_us_trading_calendar


class USCalendarTests(unittest.TestCase):
    def test_builtin_contains_key_holidays(self) -> None:
        cal = load_us_trading_calendar()
        self.assertIn("20251127", cal)  # Thanksgiving 2025
        self.assertEqual(cal["20251127"], "Thanksgiving")
        self.assertIn("20250704", cal)  # Independence Day 2025
        self.assertIn("20260619", cal)  # Juneteenth 2026


if __name__ == "__main__":
    unittest.main()
