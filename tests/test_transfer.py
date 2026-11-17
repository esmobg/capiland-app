"""Пренос между два компютъра с един CSV файл.

Бъгът, който тези тестове пазят: „Изнеси в CSV“ записваше само каталога с
продуктите. Пуснатите таймери и компаниите не влизаха във файла, затова на
другия компютър списъкът с таймерите оставаше празен, а приложението казваше
само „Внесени N продукта“.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from kapiland import catalog, transfer
from kapiland.db import Database
from kapiland.models import Account, Product, Timer, TimerStatus
from kapiland.timeutil import HOUR

NOW = 1_800_000_000.0


def running(db: Database) -> list[Timer]:
    return db.list_timers(TimerStatus.RUNNING.value)


class TransferTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="kapilands-transfer"))
        self.path = self.folder / "katalog.csv"
        self.a = Database(":memory:")   # компютър А
        self.b = Database(":memory:")   # компютър Б

    def tearDown(self):
        self.a.close()
        self.b.close()

    def fill_a(self) -> None:
        self.a.upsert_product(Product(name="Бензин", category="Химия",
                                      building="Химически фабрики",
                                      default_duration_sec=8 * HOUR, unit_price=3.5))
        self.a.upsert_account(Account(world="Българска единица", name="Алфа маркет 7",
                                      owner="Иван", buildings="Химически фабрики; Мини"))
        self.a.add_timer(Timer(product="Бензин", quality="Q2", quantity=10000000,
                               line="Алфа маркет 7", world="Българска единица",
                               building="Химически фабрики", start_at=NOW - HOUR,
                               end_at=NOW + 7 * HOUR, duration_sec=8 * HOUR,
                               repeat_enabled=1, cycles_planned=5, cycle_no=2,
                               prewarn_sec=600, note="за износ; спешно"))
        self.a.add_timer(Timer(type="research", world="Немска единица",
                               start_at=NOW, end_at=NOW + 30 * HOUR,
                               duration_sec=30 * HOUR))


class RoundTripTest(TransferTestCase):
    def test_timers_reach_the_other_computer(self):
        """Точно пътят на потребителя: „Изнеси в CSV“ на А, „Внеси от CSV“ на Б."""
        self.fill_a()
        catalog.export_csv(self.a, self.path)
        catalog.import_csv(self.b, self.path)
        self.assertEqual(len(running(self.b)), 2)

    def test_every_field_of_the_timer_survives(self):
        self.fill_a()
        transfer.export_file(self.a, self.path)
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual(result["timers"], 2)
        timer = next(t for t in running(self.b) if t.product == "Бензин")
        self.assertEqual(timer.quality, "Q2")
        self.assertEqual(timer.quantity, 10000000)
        self.assertEqual(timer.line, "Алфа маркет 7")
        self.assertEqual(timer.world, "Българска единица")
        self.assertEqual(timer.building, "Химически фабрики")
        self.assertEqual(timer.type, "production")
        self.assertEqual(timer.start_at, NOW - HOUR)
        self.assertEqual(timer.end_at, NOW + 7 * HOUR)
        self.assertEqual(timer.duration_sec, 8 * HOUR)
        self.assertEqual((timer.repeat_enabled, timer.cycles_planned, timer.cycle_no), (1, 5, 2))
        self.assertEqual(timer.prewarn_sec, 600)
        self.assertEqual(timer.note, "за износ; спешно")
        self.assertIsNone(timer.notified_at)
        self.assertEqual(timer.missed, 0)

    def test_companies_and_catalog_come_along(self):
        self.fill_a()
        counts = transfer.export_file(self.a, self.path)
        self.assertEqual(counts, {"products": 1, "timers": 2, "accounts": 1})
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual((result["products"], result["accounts"]), (1, 1))
        account = self.b.get_account("Българска единица", "Алфа маркет 7")
        self.assertEqual(account.owner, "Иван")
        self.assertEqual(account.building_list, ["Химически фабрики", "Мини"])
        self.assertEqual(self.b.get_product("Бензин").default_duration_sec, 8 * HOUR)
        self.assertEqual(self.b.list_worlds(), ["Българска единица", "Немска единица"])

    def test_importing_twice_does_not_double_the_timers(self):
        self.fill_a()
        transfer.export_file(self.a, self.path)
        transfer.import_file(self.b, self.path, now=NOW)
        again = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual((again["timers"], again["timers_existing"]), (0, 2))
        self.assertEqual(len(running(self.b)), 2)

    def test_only_running_timers_are_exported(self):
        self.fill_a()
        done = self.a.add_timer(Timer(product="Газ", start_at=NOW - 2 * HOUR,
                                      end_at=NOW - HOUR, duration_sec=HOUR))
        self.a.complete_timer(done, NOW)
        stopped = self.a.add_timer(Timer(product="Ток", start_at=NOW, end_at=NOW + HOUR,
                                         duration_sec=HOUR))
        self.a.set_timer_fields(stopped, status=TimerStatus.CANCELLED.value)
        self.assertEqual(transfer.export_file(self.a, self.path)["timers"], 2)

    def test_past_timers_arrive_as_missed_without_a_notification_storm(self):
        self.fill_a()
        transfer.export_file(self.a, self.path)
        later = NOW + 10 * HOUR          # Бензинът вече е готов, науката още не
        result = transfer.import_file(self.b, self.path, now=later)
        self.assertEqual((result["timers"], result["timers_past"]), (2, 1))
        past = next(t for t in running(self.b) if t.product == "Бензин")
        self.assertEqual((past.missed, past.notified_at), (1, later))
        future = next(t for t in running(self.b) if t.type == "research")
        self.assertEqual((future.missed, future.notified_at), (0, None))


class FileFormatTest(TransferTestCase):
    def test_version_2_1_reads_the_new_file_as_a_plain_catalog(self):
        """Старата версия чете с DictReader и прескача редове без име."""
        self.fill_a()
        transfer.export_file(self.a, self.path)
        with open(self.path, newline="", encoding="utf-8-sig") as handle:
            names = [(row.get("name") or "").strip()
                     for row in csv.DictReader(handle, delimiter=";")]
        self.assertEqual([n for n in names if n], ["Бензин"])

    def test_old_catalog_file_says_it_has_no_timers(self):
        self.path.write_text("name;quality;category\nХляб;;Агрокултура\n", encoding="utf-8-sig")
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual(result["products"], 1)
        self.assertFalse(result["has_timers"])
        summary = transfer.import_summary(result)
        self.assertIn("Внесен 1 продукт.", summary)
        self.assertIn("няма таймери", summary)
        self.assertIn("по-стара версия", summary)

    def test_saved_from_excel_in_windows_1251_with_commas(self):
        self.fill_a()
        transfer.export_file(self.a, self.path)
        text = self.path.read_text(encoding="utf-8-sig")
        text = text.replace(str(NOW + 7 * HOUR), str(NOW + 7 * HOUR).replace(".", ","))
        self.path.write_bytes(text.encode("cp1251"))
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual(result["timers"], 2)
        self.assertEqual(self.b.get_account("Българска единица", "Алфа маркет 7").owner, "Иван")

    def test_a_file_that_is_not_a_catalog_is_an_error(self):
        self.path.write_text("Потвърдено;Продукт;Качество\n01.01.2026;Хляб;\n",
                             encoding="utf-8-sig")
        with self.assertRaises(ValueError) as caught:
            transfer.import_file(self.b, self.path, now=NOW)
        self.assertIn("name", str(caught.exception))
        self.assertEqual(self.b.list_products(), [])

    def test_broken_timer_rows_are_counted_not_imported(self):
        self.path.write_text(
            "name;quality\n"
            ";#timers;product;end_at;type\n"
            ";timer;Хляб;не е час;production\n"
            ";timer;Газ;%s;нещо непознато\n" % (NOW + HOUR),
            encoding="utf-8-sig")
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual((result["timers"], result["timers_bad"]), (1, 1))
        timer = running(self.b)[0]
        self.assertEqual((timer.product, timer.type), ("Газ", "production"))
        self.assertEqual(timer.end_at, NOW + HOUR)

    def test_same_timer_twice_in_the_file_is_imported_once(self):
        row = ";timer;Хляб;%s\n" % (NOW + HOUR)
        self.path.write_text("name\n;#timers;product;end_at\n" + row + row,
                             encoding="utf-8-sig")
        result = transfer.import_file(self.b, self.path, now=NOW)
        self.assertEqual((result["timers"], result["timers_existing"]), (1, 1))


class SummaryTest(unittest.TestCase):
    def result(self, **kwargs) -> dict:
        data = dict(products=48, timers=57, accounts=41, timers_existing=0, timers_past=0,
                    timers_bad=0, has_timers=True)
        data.update(kwargs)
        return data

    def test_export(self):
        self.assertEqual(
            transfer.export_summary({"products": 48, "timers": 57, "accounts": 41}),
            "Изнесени 48 продукта, 57 таймера и 41 компании.")
        self.assertEqual(
            transfer.export_summary({"products": 1, "timers": 1, "accounts": 1}),
            "Изнесени 1 продукт, 1 таймер и 1 компания.")

    def test_import_says_where_the_timers_are(self):
        self.assertEqual(
            transfer.import_summary(self.result()),
            "Внесени 48 продукта, 57 таймера и 41 компании. "
            "Таймерите са в раздел „Таймери“, Ctrl+1.")

    def test_import_mentions_existing_past_and_broken(self):
        text = transfer.import_summary(self.result(timers=2, timers_existing=55,
                                                   timers_past=1, timers_bad=3))
        self.assertIn("55 таймера вече ги имаше", text)
        self.assertIn("1 е с минал час", text)
        self.assertIn("3 реда с таймери не са разчетени", text)

    def test_import_of_a_new_file_without_timers(self):
        text = transfer.import_summary(self.result(timers=0, accounts=0))
        self.assertEqual(text, "Внесени 48 продукта. Във файла няма таймери.")


if __name__ == "__main__":
    unittest.main()
