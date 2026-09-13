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



class BulgarianDatesTest(unittest.TestCase):
    """Формите от истинските бележки на играча."""

    def setUp(self):
        self.base = datetime(2026, 9, 13, 12, 0).timestamp()

    def moments(self, text):
        from kapiland.timeutil import parse_bg_datetimes, format_dt
        return [format_dt(t, "%d.%m.%Y %H:%M") for t in parse_bg_datetimes(text, self.base)]

    def test_dash_forms(self):
        for text in ("Бензин – 17 септември – 17 ч", "Бензин - 17 септември - 17 ч",
                     "Бензин — 17 септември — 17 ч", "17 септември 17 ч",
                     "17 септември, 17 ч", "17 септември –17 ч", "17 сеп 17 ч"):
            self.assertEqual(self.moments(text), ["17.09.2026 17:00"], text)

    def test_several_hours_on_one_day(self):
        self.assertEqual(self.moments("газ – 13 септември – 12  ч, 19 ч, 21 ч"),
                         ["13.09.2026 12:00", "13.09.2026 19:00", "13.09.2026 21:00"])

    def test_several_dates_on_one_line(self):
        self.assertEqual(
            self.moments("Двигатели – 02 септември – 07 ч, 05 септември – 07 ч"),
            ["02.09.2026 07:00", "05.09.2026 07:00"])

    def test_quantity_is_not_mistaken_for_a_date_or_hour(self):
        self.assertEqual(self.moments("99999999 вода – 19 септември – 14 ч"),
                         ["19.09.2026 14:00"])
        self.assertEqual(
            self.moments("Произвеждат 10000000 бензин – Ще бъде готов на 04 октомври – 10 ч"),
            ["04.10.2026 10:00"])

    def test_filler_words_are_ignored(self):
        self.assertEqual(self.moments("Ще бъдат готови на 21 септември 22 ч"),
                         ["21.09.2026 22:00"])

    def test_relative_days(self):
        self.assertEqual(self.moments("утре 7 ч"), ["14.09.2026 07:00"])
        self.assertEqual(self.moments("днес 18:30 ч"), ["13.09.2026 18:30"])

    def test_date_without_hour_is_not_a_moment(self):
        self.assertEqual(self.moments("Произвежда сребро"), [])
        self.assertEqual(self.moments("17 септември"), [])

    def test_year_rolls_over_only_far_in_the_past(self):
        from kapiland.timeutil import infer_year
        self.assertEqual(infer_year(9, 2, self.base), 2026)    # 11 дни назад
        self.assertEqual(infer_year(12, 17, self.base), 2026)  # напред
        self.assertEqual(infer_year(1, 5, self.base), 2027)    # 8 месеца назад

    def test_parse_datetime_accepts_the_bulgarian_form(self):
        self.assertEqual(parse_datetime("17 септември 17 ч", self.base),
                         datetime(2026, 9, 17, 17, 0).timestamp())
        self.assertEqual(parse_datetime("18 ч", self.base),
                         datetime(2026, 9, 13, 18, 0).timestamp())
        self.assertEqual(parse_datetime("9 ч", self.base),   # вече минал -> утре
                         datetime(2026, 9, 14, 9, 0).timestamp())


class FormatWhenTest(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 9, 13, 12, 0).timestamp()

    def when(self, *args):
        from kapiland.timeutil import format_when
        return format_when(datetime(*args).timestamp(), self.base)

    def spoken(self, *args):
        from kapiland.timeutil import format_when_spoken
        return format_when_spoken(datetime(*args).timestamp(), self.base)

    def test_short_forms(self):
        self.assertEqual(self.when(2026, 9, 13, 17, 0), "днес 17:00")
        self.assertEqual(self.when(2026, 9, 14, 7, 0), "утре 07:00")
        self.assertEqual(self.when(2026, 9, 12, 14, 0), "вчера 14:00")
        self.assertEqual(self.when(2026, 9, 17, 17, 0), "чт 17.09 17:00")
        self.assertEqual(self.when(2026, 12, 17, 21, 0), "17.12 21:00")
        self.assertEqual(self.when(2027, 1, 5, 9, 0), "05.01.2027 09:00")

    def test_has_no_seconds_so_it_does_not_tick(self):
        from kapiland.timeutil import format_when
        target = datetime(2026, 9, 13, 17, 0).timestamp()
        self.assertEqual(format_when(target, self.base),
                         format_when(target, self.base + 59))

    def test_spoken_forms(self):
        self.assertEqual(self.spoken(2026, 9, 13, 17, 0), "днес в 17 часа")
        self.assertEqual(self.spoken(2026, 9, 14, 7, 30), "утре в 7:30")
        self.assertEqual(self.spoken(2026, 9, 17, 17, 0),
                         "в четвъртък, 17 септември, в 17 часа")
        self.assertEqual(self.spoken(2026, 9, 15, 7, 0),
                         "във вторник, 15 септември, в 7 часа")
        self.assertEqual(self.spoken(2026, 12, 17, 21, 0), "на 17 декември в 21 часа")


class RemainingWordsTest(unittest.TestCase):
    def test_no_seconds_so_the_text_does_not_tick(self):
        from kapiland.timeutil import format_remaining_words
        self.assertEqual(format_remaining_words(2 * HOUR + 30 * MINUTE + 29), "2 часа и 30 минути")
        self.assertEqual(format_remaining_words(2 * HOUR + 30 * MINUTE + 29),
                         format_remaining_words(2 * HOUR + 30 * MINUTE + 1))

    def test_under_a_minute(self):
        from kapiland.timeutil import format_remaining_words
        self.assertEqual(format_remaining_words(29), "по-малко от минута")
        self.assertEqual(format_remaining_words(-29), "по-малко от минута")


if __name__ == "__main__":
    unittest.main()
