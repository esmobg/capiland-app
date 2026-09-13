"""Тестове за вноса на свободен текст.

``fixtures/sample_list.txt`` повтаря всеки формат от истинските бележки на
играча, но с измислени имена и измислени данни за вход.
"""

import unittest
from datetime import datetime
from pathlib import Path

from kapiland import importer
from kapiland.db import Database
from kapiland.importer import (
    NOTE_DUPLICATE,
    NOTE_EXISTS,
    NOTE_NEW_PRODUCT,
    NOTE_NO_WORLD,
    NOTE_PAST,
)
from kapiland.models import TimerStatus

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_list.txt").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 13, 12, 30).timestamp()
DEFAULT_WORLD = "Българска единица"


def at(month, day, hour, minute=0):
    return datetime(2026, month, day, hour, minute).timestamp()


class SampleListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = importer.parse(SAMPLE, DEFAULT_WORLD, now=NOW)

    def find(self, **wanted):
        found = [e for e in self.result.entries
                 if all(getattr(e, k) == v for k, v in wanted.items())]
        self.assertTrue(found, f"няма таймер с {wanted}")
        return found

    def account(self, name, world=DEFAULT_WORLD):
        for a in self.result.accounts:
            if a.name == name and a.world == world:
                return a
        self.fail(f"няма компания {name} в {world}")

    # --------------------------------------------------------- цялото

    def test_every_line_is_understood(self):
        self.assertEqual(self.result.unrecognized, [])

    def test_totals(self):
        self.assertEqual(len(self.result.entries), 39)
        self.assertEqual(self.result.skipped_credentials, 6)

    def test_summary_speaks_in_words(self):
        summary = self.result.summary()
        self.assertIn("Разпознати 39 таймера", summary)
        self.assertIn("6 реда с данни за вход пропуснати", summary)
        self.assertIn("Отметнати за внос:", summary)

    # ---------------------------------------------------- данни за вход

    def test_credentials_never_appear_anywhere(self):
        haystack = repr([e.__dict__ for e in self.result.entries]) \
            + repr([a.__dict__ for a in self.result.accounts]) \
            + repr(self.result.unrecognized) + self.result.summary()
        for secret in ("потребител1", "потребител2", "потребител3", "731944"):
            self.assertNotIn(secret, haystack)

    def test_login_line_does_not_steal_the_company(self):
        """Редът след паролата принадлежи на компанията преди потребителското име."""
        pi = self.account("пифирма")
        self.assertEqual(pi.buildings, ["Текстилни фабрики"])
        self.find(company="пифирма", product="Текстил", end_at=at(9, 16, 11))

    # ------------------------------------------------- първият блок

    def test_company_header_then_product_line(self):
        entry, = self.find(company="Алфа маркет 7", product="Бензин")
        self.assertEqual(entry.end_at, at(9, 17, 17))
        self.assertEqual(entry.world, DEFAULT_WORLD)
        self.assertEqual(entry.type, "production")

    def test_company_and_product_on_one_line_with_two_dates(self):
        entries = self.find(company="Гама83", product="Двигатели")
        self.assertEqual([e.end_at for e in entries], [at(9, 2, 7), at(9, 5, 7)])

    def test_lowercase_product_is_matched_to_the_catalog(self):
        entry, = self.find(company="Делта")
        self.assertEqual(entry.product, "Легла")
        self.assertTrue(entry.known_product)

    def test_double_dash_and_quantity(self):
        entry, = self.find(company="Зета таралеж")
        self.assertEqual((entry.product, entry.quantity), ("Минерали", 10000000))

    def test_trailing_dash_continues_on_the_next_line(self):
        entry, = self.find(company="Етаслинчо")
        self.assertEqual((entry.product, entry.quantity), ("Вода", 99999999))

    # ----------------------------------------------------- допълнителни

    def test_building_then_verb(self):
        entry, = self.find(company="тетафирма")
        self.assertEqual((entry.product, entry.building), ("Компютри", "Фабрики за електроника"))
        self.assertEqual(entry.end_at, at(9, 21, 22))

    def test_building_after_the_timer_is_added_to_the_company(self):
        entry, = self.find(company="йотафирма")
        self.assertEqual(entry.building, "Плантация")
        self.assertEqual(self.account("йотафирма").buildings, ["Плантация", "Бензиностанции"])

    def test_quantity_with_a_stray_and(self):
        entry, = self.find(company="капа42")
        self.assertEqual((entry.product, entry.quantity), ("Компоненти", 2000000))

    def test_build_with_the_date_on_the_next_line(self):
        entry, = self.find(company="ламбда")
        self.assertEqual((entry.type, entry.building), ("build", "Бензиностанции"))
        self.assertEqual(entry.end_at, at(12, 17, 18))
        self.assertIn("Бензиностанции", self.account("ламбда").buildings)

    def test_idle_company(self):
        mu = self.account("мю")
        self.assertTrue(mu.idle)
        self.assertEqual([e for e in self.result.entries if e.company == "мю"], [])

    def test_activity_without_a_time_is_a_note_not_a_timer(self):
        nu = self.account("ню")
        self.assertEqual(nu.buildings, ["Мини"])
        self.assertIn("Произвежда сребро (без час)", nu.notes)
        self.assertEqual([e for e in self.result.entries if e.company == "ню"], [])

    def test_two_dates_after_a_verb(self):
        entries = self.find(company="кси", product="Банани")
        self.assertEqual(len(entries), 2)

    def test_expand_with_a_building(self):
        entry, = self.find(company="омикрон")
        self.assertEqual((entry.type, entry.building), ("expand", "Мебелни магазини"))

    # -------------------------------------------------- блок със собственик

    def test_owner_block(self):
        for name in ("пифирма", "ро стил", "сигма"):
            self.assertEqual(self.account(name).owner, "Иван")
        self.assertEqual(self.account("Алфа маркет 7").owner, "")

    def test_two_known_products_joined_with_and(self):
        products = sorted(e.product for e in self.find(company="ро стил"))
        self.assertEqual(products, ["Автомобили", "Мотори"])
        self.assertTrue(all(e.type == "sale" for e in self.find(company="ро стил")))

    def test_expand_without_a_building_uses_the_companys_building(self):
        entry, = self.find(company="сигма", type="expand")
        self.assertEqual(entry.building, "Бижутерия")

    def test_past_is_unchecked(self):
        entry, = self.find(company="сигма", product="Пръстени")
        self.assertIn(NOTE_PAST, entry.notes)
        self.assertFalse(entry.selected)

    def test_duplicate_is_unchecked(self):
        first, second = self.find(company="Епсилон", product="Парфюми")
        self.assertTrue(first.selected)
        self.assertIn(NOTE_DUPLICATE, second.notes)
        self.assertFalse(second.selected)

    # ----------------------------------------------------- редове със свят

    def test_world_person_and_articled_product(self):
        entry, = self.find(company="Тау")
        self.assertEqual((entry.world, entry.product), ("Немска двойка", "Ток"))

    def test_same_person_in_two_worlds_is_two_companies(self):
        self.account("Ипсилон", "Немска тройка")
        self.account("Ипсилон", "Немска петица")
        entry, = self.find(company="Ипсилон", world="Немска петица")
        self.assertEqual((entry.type, entry.product, entry.quantity),
                         ("sale", "Кожени ръкавици", 100000))

    def test_product_on_one_line_hours_on_the_next(self):
        entries = self.find(world="Английска единица", product="Газ")
        self.assertEqual([e.end_at for e in entries],
                         [at(9, 13, 12), at(9, 13, 19), at(9, 13, 21)])
        self.assertFalse(entries[0].selected)  # 12:00 вече е минало
        self.assertTrue(entries[1].selected)

    def test_no_guessing_of_buildings(self):
        entry, = self.find(company="Ипсилон", world="Немска тройка")
        self.assertEqual(entry.building, "")  # продава компютри — не е фабрика

    # --------------------------------------------------------------- науки

    def test_research_per_world(self):
        entry, = self.find(type="research", world="Немска единица")
        self.assertEqual((entry.company, entry.product), ("", ""))
        self.assertEqual(len(self.find(type="research", world="Английска двойка")), 2)

    # ------------------------------------------------------------ магазини

    def test_two_products_on_one_line(self):
        products = sorted(e.product for e in self.find(type="sale", world="Немска петица",
                                                         company=""))
        self.assertEqual(products, ["Кожени ръкавици", "Рози"])

    def test_unknown_product_is_kept_and_marked(self):
        entry, = self.find(product="Измисленпродукт")
        self.assertIn(NOTE_NEW_PRODUCT, entry.notes)
        self.assertTrue(entry.selected)

    def test_line_without_a_world_keeps_the_previous_world(self):
        entry, = self.find(product="Computers")
        self.assertEqual((entry.world, entry.type), ("Английска единица", "sale"))

    def test_world_only_line_sets_the_world_for_the_following_lines(self):
        for product in ("Автомобили", "Джинси", "Компютри"):
            entry = self.find(product=product, world="Холандска единица")[0]
            self.assertEqual(entry.type, "sale")
        self.assertEqual(self.find(product="Джинси")[0].quantity, 1500)


class EdgeCasesTest(unittest.TestCase):
    def test_empty_text(self):
        result = importer.parse("", DEFAULT_WORLD, now=NOW)
        self.assertEqual((result.entries, result.accounts, result.unrecognized), ([], [], []))
        self.assertIn("Разпознати 0 таймера", result.summary())

    def test_without_a_default_world(self):
        result = importer.parse("Алфа\nБензин – 17 септември – 17 ч", "", now=NOW)
        self.assertIn(NOTE_NO_WORLD, result.entries[0].notes)

    def test_long_sentence_is_not_a_company(self):
        result = importer.parse("това е едно дълго изречение без никакъв смисъл", now=NOW)
        self.assertEqual(result.accounts, [])
        self.assertEqual(len(result.unrecognized), 1)

    def test_building_without_a_company_is_unrecognized(self):
        result = importer.parse("Химически фабрики", now=NOW)
        self.assertEqual(len(result.unrecognized), 1)

    def test_digits_outside_an_owner_block_do_not_delete_a_plain_company(self):
        result = importer.parse("Алфа\n123456\nБензин – 17 септември – 17 ч", now=NOW)
        self.assertEqual(result.skipped_credentials, 1)
        self.assertEqual(result.entries[0].company, "Алфа")

    def test_login_like_word_before_digits_is_dropped_anywhere(self):
        text = "Алфа\nпотребител7\n123456\nБензин – 17 септември – 17 ч"
        result = importer.parse(text, now=NOW)
        self.assertEqual(result.skipped_credentials, 2)
        self.assertEqual([a.name for a in result.accounts], ["Алфа"])
        self.assertEqual(result.entries[0].company, "Алфа")
        self.assertNotIn("потребител7", repr(result.__dict__))

    def test_dates_without_hours_are_unrecognized(self):
        result = importer.parse("Алфа – Бензин – 17 септември", now=NOW)
        self.assertEqual(result.entries, [])

    def test_known_products_from_the_users_catalog(self):
        result = importer.parse("Алфа – хляб – 17 септември – 17 ч", now=NOW,
                                known_products=["Хляб"])
        self.assertEqual(result.entries[0].product, "Хляб")
        self.assertNotIn(NOTE_NEW_PRODUCT, result.entries[0].notes)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.result = importer.parse(SAMPLE, DEFAULT_WORLD, now=NOW)

    def tearDown(self):
        self.db.close()

    def test_writes_companies_and_checked_timers(self):
        counts = importer.apply(self.result, self.db, now=NOW)
        self.assertEqual(counts["timers"], len(self.result.selected_entries))
        self.assertEqual(counts["companies"], len(self.result.accounts))
        self.assertEqual(len(self.db.list_timers(TimerStatus.RUNNING.value)),
                         len(self.result.selected_entries))
        self.assertEqual(self.db.get_account(DEFAULT_WORLD, "ро стил").owner, "Иван")
        self.assertIn("Бензиностанции", self.db.get_account(DEFAULT_WORLD, "йотафирма").buildings)

    def test_timer_fields(self):
        importer.apply(self.result, self.db, now=NOW)
        timer = next(t for t in self.db.list_timers() if t.line == "Зета таралеж")
        self.assertEqual((timer.product, timer.quantity, timer.world),
                         ("Минерали", 10000000, DEFAULT_WORLD))
        self.assertEqual(timer.end_at, at(10, 2, 19))
        self.assertEqual(timer.duration_sec, int(round(at(10, 2, 19) - NOW)))
        self.assertIn("Внесено на", timer.note)

    def test_checked_past_timer_is_shown_as_missed_without_a_new_alert(self):
        entry = next(e for e in self.result.entries if NOTE_PAST in e.notes)
        entry.selected = True
        importer.apply(self.result, self.db, now=NOW)
        timer = next(t for t in self.db.list_timers()
                     if t.end_at == entry.end_at and t.line == entry.company)
        self.assertEqual(timer.missed, 1)
        self.assertIsNotNone(timer.notified_at)

    def test_unknown_products_join_the_catalog(self):
        importer.apply(self.result, self.db, now=NOW)
        self.assertIsNotNone(self.db.get_product("Измисленпродукт"))

    def test_second_import_finds_everything_already_there(self):
        importer.apply(self.result, self.db, now=NOW)
        again = importer.parse(SAMPLE, DEFAULT_WORLD, now=NOW)
        marked = importer.mark_existing(again, self.db)
        self.assertEqual(marked, len(self.result.selected_entries))
        self.assertEqual(again.selected_entries, [])
        self.assertIn(NOTE_EXISTS, again.entries[0].notes)

    def test_nothing_checked_writes_no_timers(self):
        for entry in self.result.entries:
            entry.selected = False
        counts = importer.apply(self.result, self.db, now=NOW)
        self.assertEqual(counts["timers"], 0)
        self.assertEqual(self.db.list_timers(None), [])


if __name__ == "__main__":
    unittest.main()
