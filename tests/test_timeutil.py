"""Тестове за парсването и форматирането на времена."""

import unittest
from datetime import datetime

from kapiland.timeutil import (
    DAY,
    HOUR,
    MINUTE,
    format_duration,
    format_duration_words,
    format_dt_relative,
    parse_datetime,
    parse_duration,
)


class ParseDurationTest(unittest.TestCase):
    def test_latin_units(self):
        self.assertEqual(parse_duration("3d 4h 20m"), 3 * DAY + 4 * HOUR + 20 * MINUTE)
        self.assertEqual(parse_duration("2h"), 2 * HOUR)
        self.assertEqual(parse_duration("45s"), 45)

    def test_cyrillic_units(self):
        self.assertEqual(parse_duration("3д 4ч 20м"), 3 * DAY + 4 * HOUR + 20 * MINUTE)
        self.assertEqual(parse_duration("2 часа 30 мин"), 2 * HOUR + 30 * MINUTE)
        self.assertEqual(parse_duration("90 секунди"), 90)

    def test_colon_forms(self):
        self.assertEqual(parse_duration("03:42:10"), 3 * HOUR + 42 * MINUTE + 10)
        self.assertEqual(parse_duration("2:30"), 2 * HOUR + 30 * MINUTE)
        self.assertEqual(parse_duration("1:00:00:00"), DAY)

    def test_decimals_and_bare_number(self):
        self.assertEqual(parse_duration("1.5h"), 90 * MINUTE)
        self.assertEqual(parse_duration("1,5ч"), 90 * MINUTE)
        self.assertEqual(parse_duration("45"), 45 * MINUTE)  # голо число = минути

    def test_zero(self):
        self.assertEqual(parse_duration("0"), 0)
        self.assertEqual(parse_duration("00:00:00"), 0)

    def test_invalid(self):
        for bad in ("", "   ", "утре", "5 парсека", None, "12:xx"):
            with self.assertRaises(ValueError):
                parse_duration(bad)


class FormatDurationTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(format_duration(0), "00:00:00")
        self.assertEqual(format_duration(59), "00:00:59")
        self.assertEqual(format_duration(3600), "01:00:00")
        self.assertEqual(format_duration(9015), "02:30:15")

    def test_over_a_day(self):
        self.assertEqual(format_duration(DAY + 9015), "1д 02:30:15")
        self.assertEqual(format_duration(DAY + 9015, with_days=False), "26:30:15")

    def test_negative(self):
        self.assertEqual(format_duration(-90), "-00:01:30")

    def test_round_trip(self):
        for seconds in (0, 1, 59, 60, 3599, 3600, 86399, 86400, 123456):
            self.assertEqual(parse_duration(format_duration(seconds)), seconds)

    def test_words(self):
        self.assertEqual(format_duration_words(0), "0 секунди")
        self.assertEqual(format_duration_words(60), "1 минута")
        self.assertEqual(format_duration_words(3600), "1 час")
        self.assertIn("и", format_duration_words(9015))


class ParseDatetimeTest(unittest.TestCase):
    def setUp(self):
        # петък, 12.09.2026, 14:00 местно време
        self.base = datetime(2026, 9, 12, 14, 0, 0).timestamp()

    def test_full_formats(self):
        expected = datetime(2026, 9, 12, 14, 30).timestamp()
        for text in ("12.09.2026 14:30", "2026-09-12 14:30", "12/09/2026 14:30"):
            self.assertEqual(parse_datetime(text, self.base), expected)

    def test_short_date_uses_current_year(self):
        self.assertEqual(parse_datetime("12.09 14:30", self.base),
                         datetime(2026, 9, 12, 14, 30).timestamp())

    def test_time_only_today(self):
        self.assertEqual(parse_datetime("15:30", self.base),
                         datetime(2026, 9, 12, 15, 30).timestamp())

    def test_time_only_already_passed_means_tomorrow(self):
        self.assertEqual(parse_datetime("09:00", self.base),
                         datetime(2026, 9, 13, 9, 0).timestamp())

    def test_now(self):
        self.assertEqual(parse_datetime("сега", self.base), self.base)
        self.assertEqual(parse_datetime("now", self.base), self.base)

    def test_invalid(self):
        for bad in ("", "някога", "32.13.2026 99:99"):
            with self.assertRaises(ValueError):
                parse_datetime(bad, self.base)

    def test_relative_labels(self):
        self.assertTrue(format_dt_relative(self.base + HOUR, self.base)
                        .startswith("днес"))
        self.assertTrue(format_dt_relative(self.base + DAY, self.base)
                        .startswith("утре"))
        self.assertTrue(format_dt_relative(self.base - DAY, self.base)
                        .startswith("вчера"))


if __name__ == "__main__":
    unittest.main()
