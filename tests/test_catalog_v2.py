"""Тестове за световете, сградите и продуктите в каталога (v2)."""

import unittest

from kapiland import catalog
from kapiland.db import Database
from kapiland.models import Product


class WorldTest(unittest.TestCase):
    def test_world_at_the_start_of_a_line(self):
        self.assertEqual(catalog.parse_world("Немска двойка – Тау")[0], "Немска двойка")
        self.assertEqual(catalog.parse_world("английска ЕДИНИЦА - газ")[0],
                         "Английска единица")
        self.assertEqual(catalog.parse_world("Холандска единица ")[0], "Холандска единица")

    def test_rest_of_the_line_is_returned(self):
        self.assertEqual(catalog.parse_world("Немска петица – рози")[1], " – рози")

    def test_not_a_world(self):
        for text in ("Алфа маркет 7", "Немски продукти", "", "единица"):
            self.assertIsNone(catalog.parse_world(text), text)

    def test_every_known_world_parses_to_itself(self):
        for world in catalog.KNOWN_WORLDS:
            self.assertEqual(catalog.parse_world(world)[0], world)

    def test_world_name(self):
        self.assertEqual(catalog.world_name("немска", 6), "Немска шестица")


class BuildingTest(unittest.TestCase):
    def test_buildings_from_the_notes_and_the_production_list(self):
        # 15 от бележките + 11 от списъка „Производство“.
        self.assertEqual(len(catalog.BUILDINGS), 26)
        for name in catalog.building_names():
            self.assertEqual(catalog.find_building(name), name)

    def test_plural_and_singular_forms(self):
        self.assertEqual(catalog.find_building("автосалони"), "Автосалон")
        self.assertEqual(catalog.find_building("бензиностанция"), "Бензиностанции")
        self.assertEqual(catalog.find_building("мебелни магазини"), "Мебелни магазини")

    def test_longest_name_wins(self):
        self.assertEqual(catalog.find_building("Плодова плантация"), "Плодова плантация")
        self.assertEqual(catalog.find_building("Плантация"), "Плантация")

    def test_building_followed_by_more_text(self):
        self.assertEqual(catalog.find_building("автосалони – Ще бъдат готови"), "Автосалон")

    def test_not_a_building(self):
        for text in ("Алфа маркет 7", "Бензин", ""):
            self.assertIsNone(catalog.find_building(text), text)

    def test_building_categories_are_known(self):
        for name, category in catalog.BUILDINGS:
            self.assertIn(category, catalog.CATEGORIES, name)


class ProductTest(unittest.TestCase):
    def test_all_products_from_the_notes(self):
        self.assertEqual(len(catalog.PRODUCTS_V2), 28)
        names = catalog.product_names_v2()
        self.assertEqual(len(names), len(set(names)))

    def test_case_and_articles(self):
        self.assertEqual(catalog.find_product("бензин"), "Бензин")
        self.assertEqual(catalog.find_product("Токът"), "Ток")
        self.assertEqual(catalog.find_product("Парфюмите"), "Парфюми")
        self.assertEqual(catalog.find_product("кожени  якета"), "Кожени якета")

    def test_unknown_products_stay_unknown(self):
        for text in ("измисленпродукт", "Computers", ""):
            self.assertIsNone(catalog.find_product(text), text)

    def test_extra_names_from_the_users_catalog(self):
        self.assertEqual(catalog.find_product("хляб", extra=["Хляб"]), "Хляб")

    def test_building_only_where_the_notes_show_it(self):
        self.assertEqual(catalog.building_for_product("Компютри"), "Фабрики за електроника")
        self.assertEqual(catalog.building_for_product("бензин"), "Химически фабрики")
        self.assertEqual(catalog.building_for_product("Газ"), "")      # не се гадае
        self.assertEqual(catalog.building_for_product("непознат"), "")

    def test_product_categories_and_buildings_are_consistent(self):
        buildings = set(catalog.building_names())
        for name, category, building in catalog.PRODUCTS_V2:
            self.assertIn(category, catalog.CATEGORIES, name)
            if building:
                self.assertIn(building, buildings, name)


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_adds_missing_products(self):
        added = catalog.upgrade_catalog_v2(self.db)
        self.assertEqual(added, 28)
        self.assertEqual(self.db.get_product("Бензин").building, "Химически фабрики")

    def test_runs_only_once(self):
        catalog.upgrade_catalog_v2(self.db)
        self.db.delete_product(self.db.get_product("Газ").id)
        self.assertEqual(catalog.upgrade_catalog_v2(self.db), 0)
        self.assertIsNone(self.db.get_product("Газ"))  # изтритото не се връща

    def test_does_not_overwrite_what_the_user_filled_in(self):
        self.db.upsert_product(Product(name="Бензин", category="Моя категория",
                                       unit_price=7.5, default_duration_sec=3600))
        catalog.upgrade_catalog_v2(self.db)
        bensin = self.db.get_product("Бензин")
        self.assertEqual(bensin.category, "Моя категория")
        self.assertEqual(bensin.unit_price, 7.5)
        self.assertEqual(bensin.default_duration_sec, 3600)
        self.assertEqual(bensin.building, "Химически фабрики")  # празното се попълва

    def test_existing_seed_is_kept(self):
        catalog.ensure_seed(self.db)
        before = len(self.db.list_products())
        added = catalog.upgrade_catalog_v2(self.db)
        self.assertEqual(len(self.db.list_products()), before + added)

    def test_csv_keeps_the_building(self):
        import tempfile
        from pathlib import Path

        catalog.upgrade_catalog_v2(self.db)
        path = Path(tempfile.mkdtemp()) / "k.csv"
        catalog.export_csv(self.db, path)
        for product in self.db.list_products():
            self.db.delete_product(product.id)
        catalog.import_csv(self.db, path)
        self.assertEqual(self.db.get_product("Сребро").building, "Мини")


if __name__ == "__main__":
    unittest.main()
