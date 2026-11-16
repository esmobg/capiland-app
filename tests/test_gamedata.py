"""Тестове за списъците „Изследвания“ и „Производство“ и преноса им."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from kapiland import catalog, gamedata, importer
from kapiland.db import Database
from kapiland.models import Product

FIXTURES = Path(__file__).parent / "fixtures"
RESEARCH_FILE = FIXTURES / "research_list.txt"       # копие на Изследвания.txt
PRODUCTION_FILE = FIXTURES / "production_list.txt"   # копие на Производство.txt


class ParseTest(unittest.TestCase):
    def test_embedded_lists_are_the_users_files(self):
        for path, text in ((RESEARCH_FILE, gamedata.RESEARCH_TEXT),
                           (PRODUCTION_FILE, gamedata.PRODUCTION_TEXT)):
            from_file = gamedata.parse_groups(path.read_text(encoding="utf-8-sig"))
            self.assertEqual(from_file, gamedata.parse_groups(text), path.name)

    def test_kind_and_groups(self):
        kind, groups = gamedata.parse_groups(gamedata.RESEARCH_TEXT)
        self.assertEqual(kind, gamedata.RESEARCH)
        self.assertEqual(len(groups), 7)
        self.assertEqual(groups["Производствени сгради"], [])  # празна група се пази
        kind, groups = gamedata.parse_groups(gamedata.PRODUCTION_TEXT)
        self.assertEqual(kind, gamedata.PRODUCTION)
        self.assertEqual(len(groups), 19)

    def test_no_header(self):
        kind, groups = gamedata.parse_groups("мина\nзлато\n\nферма\nяйца\n")
        self.assertIsNone(kind)
        self.assertEqual(groups, {"Мина": ["Злато"], "Ферма": ["Яйца"]})

    def test_aliases_and_spaces(self):
        _kind, groups = gamedata.parse_groups("мина\n  железа \nе  компоненти\nжелязо\n")
        self.assertEqual(groups["Мина"], ["Желязо", "Компоненти"])

    def test_format_round_trip(self):
        for text in (gamedata.RESEARCH_TEXT, gamedata.PRODUCTION_TEXT):
            kind, groups = gamedata.parse_groups(text)
            self.assertEqual(gamedata.parse_groups(gamedata.format_groups(kind, groups)),
                             (kind, groups))

    def test_lookups(self):
        self.assertEqual(gamedata.research_for_product("бензин"), "Химическа")
        self.assertEqual(gamedata.research_for_product("Реклами"), "Медийна")
        self.assertEqual(gamedata.research_for_product("железа"), "Мини и кладенец")
        self.assertEqual(gamedata.research_for_product("непознат"), "")
        self.assertEqual(gamedata.production_group_for_product("Сладолед лимон"),
                         "Сладоледена фабрика")
        self.assertEqual(gamedata.production_group_for_product("Плюшени играчки"),
                         "Фабрика за играчки")


class CatalogLookupTest(unittest.TestCase):
    def test_every_production_group_is_a_known_building(self):
        names = set(catalog.building_names())
        for group in gamedata.production_groups():
            self.assertIn(catalog.find_building(group), names, group)

    def test_production_building(self):
        self.assertEqual(catalog.production_building("Бензин"), "Фабрика")
        self.assertEqual(catalog.production_building("Парфюми"), "Химически фабрики")
        self.assertEqual(catalog.production_building("Реклами"), "ТВ станция")
        self.assertEqual(catalog.production_building("Ток"), "Електроцентрала")
        self.assertEqual(catalog.production_building("Злато"), "Мини")
        self.assertEqual(catalog.production_building("Газ"), "")

    def test_buildings_for_sale_put_the_shop_first(self):
        self.assertEqual(catalog.buildings_for_product("Телевизори"),
                         ["Фабрики за електроника", "Магазини за електроника"])
        self.assertEqual(catalog.buildings_for_product("Телевизори", importer.SALE),
                         ["Магазини за електроника", "Фабрики за електроника"])

    def test_find_product_knows_the_lists(self):
        self.assertEqual(catalog.find_product("капи кола"), "Капи кола")
        self.assertEqual(catalog.find_product("е компоненти"), "Компоненти")
        self.assertEqual(catalog.find_product("железа"), "Желязо")

    def test_every_product_has_a_known_category(self):
        for name in gamedata.all_product_names():
            self.assertIn(catalog.category_for_product(name), catalog.CATEGORIES, name)


class UpgradeV3Test(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_fresh_computer_gets_everything(self):
        catalog.ensure_seed(self.db)
        catalog.upgrade_catalog_v2(self.db)
        catalog.upgrade_catalog_v3(self.db)
        bensin = self.db.get_product("Бензин")
        self.assertEqual(bensin.research, "Химическа")
        self.assertEqual(bensin.building, "Химически фабрики")  # от v2, не се пипа
        ads = self.db.get_product("Реклами")
        self.assertEqual((ads.building, ads.research), ("ТВ станция", "Медийна"))
        names = {p.name.lower() for p in self.db.list_products()}
        for name in gamedata.all_product_names():
            self.assertIn(name.lower(), names)

    def test_runs_only_once_and_deleted_stays_deleted(self):
        self.assertGreater(catalog.upgrade_catalog_v3(self.db), 90)
        self.db.delete_product(self.db.get_product("Реклами").id)
        self.assertEqual(catalog.upgrade_catalog_v3(self.db), 0)
        self.assertIsNone(self.db.get_product("Реклами"))

    def test_does_not_overwrite_and_fills_every_quality(self):
        self.db.upsert_product(Product(name="Хляб", quality="Q5", building="Моята пекарна",
                                       unit_price=3.0, default_duration_sec=600))
        catalog.upgrade_catalog_v3(self.db)
        bread = self.db.get_product("Хляб", "Q5")
        self.assertEqual(bread.building, "Моята пекарна")
        self.assertEqual(bread.research, "Храна")
        self.assertEqual(bread.unit_price, 3.0)
        self.assertEqual(bread.default_duration_sec, 600)
        self.assertIsNone(self.db.get_product("Хляб"))  # не се дублира без качество


class ImportExportTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.folder = Path(tempfile.mkdtemp(prefix="kapilands-lists"))

    def tearDown(self):
        self.db.close()

    def test_import_the_users_files_into_an_empty_catalog(self):
        result = catalog.import_lists(self.db, RESEARCH_FILE)
        self.assertEqual((result["kind"], result["groups"]), (gamedata.RESEARCH, 7))
        self.assertEqual(result["added"], result["products"])
        result = catalog.import_lists(self.db, PRODUCTION_FILE)
        self.assertEqual((result["kind"], result["groups"]), (gamedata.PRODUCTION, 19))
        honey = self.db.get_product("Сребърни огърлици")
        self.assertEqual((honey.building, honey.research), ("Фабрика за бижута", "Химическа"))
        self.assertEqual(honey.category, "Бижута")

    def test_import_overwrites_only_the_list_field(self):
        self.db.upsert_product(Product(name="Бензин", building="Бензиностанции",
                                       research="Стара", unit_price=9.0,
                                       default_duration_sec=7200, note="моя"))
        catalog.import_lists(self.db, RESEARCH_FILE)
        bensin = self.db.get_product("Бензин")
        self.assertEqual(bensin.research, "Химическа")
        self.assertEqual(bensin.building, "Бензиностанции")
        self.assertEqual((bensin.unit_price, bensin.default_duration_sec, bensin.note),
                         (9.0, 7200, "моя"))

    def test_export_then_import_on_another_computer(self):
        catalog.upgrade_catalog_v2(self.db)
        catalog.upgrade_catalog_v3(self.db)
        self.db.upsert_product(Product(name="Рози", building="Плантация", research="Храна"))
        counts = catalog.export_lists(self.db, self.folder)
        self.assertGreater(counts[gamedata.RESEARCH], 90)
        files = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(files, sorted(gamedata.FILE_NAMES.values()))

        other = Database(":memory:")
        try:
            for name in gamedata.FILE_NAMES.values():
                catalog.import_lists(other, self.folder / name)
            for product in self.db.list_products():
                copy = other.get_product(product.name)
                if not (product.building or product.research):
                    continue
                self.assertIsNotNone(copy, product.name)
                self.assertEqual((copy.building, copy.research),
                                 (product.building, product.research), product.name)
        finally:
            other.close()

    def test_kind_from_the_file_name_when_there_is_no_header(self):
        path = self.folder / "Производство.txt"
        path.write_text("мина\nзлато\n", encoding="utf-8")
        self.assertEqual(catalog.import_lists(self.db, path)["kind"], gamedata.PRODUCTION)
        self.assertEqual(self.db.get_product("Злато").building, "Мини")

    def test_unknown_kind_is_an_error(self):
        path = self.folder / "бележки.txt"
        path.write_text("мина\nзлато\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog.import_lists(self.db, path)

    def test_old_windows_encoding(self):
        path = self.folder / "x.txt"
        path.write_bytes(gamedata.RESEARCH_TEXT.encode("cp1251"))
        self.assertEqual(catalog.import_lists(self.db, path)["kind"], gamedata.RESEARCH)

    def test_csv_carries_the_research(self):
        catalog.upgrade_catalog_v3(self.db)
        path = self.folder / "k.csv"
        catalog.export_csv(self.db, path)
        other = Database(":memory:")
        try:
            catalog.import_csv(other, path)
            self.assertEqual(other.get_product("Реклами").research, "Медийна")
        finally:
            other.close()

    def test_old_csv_without_research_still_imports(self):
        path = self.folder / "old.csv"
        path.write_text("name;quality;category;building\nХляб;;Агрокултура;Фабрики за храна\n",
                        encoding="utf-8-sig")
        self.db.upsert_product(Product(name="Хляб", research="Храна"))
        catalog.import_csv(self.db, path)
        self.assertEqual(self.db.get_product("Хляб").research, "Храна")


class SummaryTest(unittest.TestCase):
    def test_wording(self):
        from kapiland.wxui.catalog_panel import import_lists_summary

        self.assertEqual(import_lists_summary(
            {"kind": gamedata.RESEARCH, "groups": 1, "products": 1, "added": 0}),
            "Внесени 1 продукт в 1 наука.")
        self.assertEqual(import_lists_summary(
            {"kind": gamedata.PRODUCTION, "groups": 19, "products": 95, "added": 3}),
            "Внесени 95 продукта в 19 сгради, 3 от тях нови.")


class MigrationTest(unittest.TestCase):
    def test_old_database_gets_the_research_column(self):
        path = Path(tempfile.mkdtemp(prefix="kapilands-old")) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
            " quality TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',"
            " building TEXT NOT NULL DEFAULT '', default_type TEXT NOT NULL DEFAULT 'production',"
            " default_duration_sec INTEGER NOT NULL DEFAULT 0,"
            " default_quantity REAL NOT NULL DEFAULT 0, unit_cost REAL NOT NULL DEFAULT 0,"
            " unit_price REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',"
            " UNIQUE(name, quality));"
            "INSERT INTO products (name, unit_price) VALUES ('Бензин', 5);")
        conn.commit()
        conn.close()
        db = Database(path)
        try:
            bensin = db.get_product("Бензин")
            self.assertEqual((bensin.research, bensin.unit_price), ("", 5.0))
            catalog.upgrade_catalog_v3(db)
            self.assertEqual(db.get_product("Бензин").research, "Химическа")
        finally:
            db.close()


class ImporterBuildingTest(unittest.TestCase):
    TEXT = ("Българска единица\nИпсилон\nФабрики за електроника\nМагазини за електроника\n"
            "Продава телевизори – 17 декември – 18 ч\n"
            "Произвежда телевизори – 17 декември – 19 ч\n")

    def test_factory_for_production_shop_for_sale(self):
        now = 1_700_000_000.0  # ноември 2023 — декември е в бъдещето
        result = importer.parse(self.TEXT, now=now)
        by_type = {e.type: e.building for e in result.entries}
        self.assertEqual(by_type[importer.SALE], "Магазини за електроника")
        self.assertEqual(by_type[importer.PRODUCTION], "Фабрики за електроника")


if __name__ == "__main__":
    unittest.main()
