"""Тестове за качеството на продуктите и за надграждането на стара база.

В Kapilands един и същ продукт се прави в различни качества, а те имат
различно време и различна цена. Тези тестове пазят точно това разделяне.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kapiland import catalog
from kapiland.db import Database
from kapiland.models import Product, Timer
from kapiland.timeutil import HOUR

NOW = 1_000_000.0


def make_timer(**kwargs) -> Timer:
    data = dict(product="Хляб", quantity=100, start_at=NOW,
                end_at=NOW + HOUR, duration_sec=HOUR)
    data.update(kwargs)
    return Timer(**data)


class QualitySeparatesRecordsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_same_name_in_two_qualities_are_two_products(self):
        self.db.remember_product(make_timer(quality="Q1", duration_sec=HOUR))
        self.db.remember_product(make_timer(quality="Q3", duration_sec=2 * HOUR))
        self.assertEqual(len(self.db.list_products()), 2)
        self.assertEqual(self.db.get_product("Хляб", "Q1").default_duration_sec, HOUR)
        self.assertEqual(self.db.get_product("Хляб", "Q3").default_duration_sec,
                         2 * HOUR)

    def test_same_quality_is_updated_not_duplicated(self):
        self.db.remember_product(make_timer(quality="Q1", duration_sec=HOUR))
        self.db.remember_product(make_timer(quality="Q1", duration_sec=3 * HOUR))
        self.assertEqual(len(self.db.list_products()), 1)
        self.assertEqual(self.db.get_product("Хляб", "Q1").default_duration_sec,
                         3 * HOUR)

    def test_product_without_quality_is_its_own_record(self):
        self.db.remember_product(make_timer(quality="", duration_sec=HOUR))
        self.db.remember_product(make_timer(quality="Q1", duration_sec=2 * HOUR))
        self.assertEqual(len(self.db.list_products()), 2)
        self.assertEqual(self.db.get_product("Хляб").default_duration_sec, HOUR)

    def test_quality_lookup_is_case_insensitive_in_cyrillic(self):
        self.db.upsert_product(Product(name="Плат", quality="Високо"))
        self.assertIsNotNone(self.db.get_product("плат", "високо"))

    def test_prices_are_kept_per_quality(self):
        self.db.upsert_product(Product(name="Хляб", quality="Q1", unit_price=5))
        self.db.upsert_product(Product(name="Хляб", quality="Q5", unit_price=20))
        self.assertEqual(self.db.get_product("Хляб", "Q1").unit_price, 5)
        self.assertEqual(self.db.get_product("Хляб", "Q5").unit_price, 20)


class QualityTravelsWithTheTimerTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_saved_and_read_back(self):
        timer = make_timer(quality="Q2")
        self.db.add_timer(timer)
        self.assertEqual(self.db.get_timer(timer.id).quality, "Q2")

    def test_history_keeps_the_quality(self):
        timer = make_timer(quality="Q2")
        self.db.add_timer(timer)
        self.db.complete_timer(timer.id, now=NOW + HOUR)
        self.assertEqual(self.db.list_history()[0].quality, "Q2")

    def test_next_cycle_keeps_the_quality(self):
        timer = make_timer(quality="Q2", repeat_enabled=1, cycles_planned=3)
        self.db.add_timer(timer)
        nxt = self.db.start_next_cycle(timer, start_at=NOW + HOUR)
        self.assertEqual(nxt.quality, "Q2")

    def test_display_name_shows_the_quality(self):
        self.assertEqual(make_timer(quality="Q2", quantity=500).display_name,
                         "500× Хляб [Q2]")
        self.assertEqual(make_timer(quality="", quantity=500).display_name,
                         "500× Хляб")
        self.assertEqual(Product(name="Хляб", quality="Q2").display_name, "Хляб [Q2]")
        self.assertEqual(Product(name="Хляб").display_name, "Хляб")

    def test_statistics_separate_the_qualities(self):
        from kapiland import planner
        from kapiland.models import HistoryEntry

        rows = planner.summarize_history([
            HistoryEntry(product="Хляб", quality="Q1", quantity=100,
                         duration_sec=HOUR, profit=100),
            HistoryEntry(product="Хляб", quality="Q5", quantity=100,
                         duration_sec=HOUR, profit=500),
        ])
        self.assertEqual(len(rows), 2)
        by_quality = {r["quality"]: r["profit_per_hour"] for r in rows}
        self.assertEqual(by_quality["Q1"], 100)
        self.assertEqual(by_quality["Q5"], 500)


class CsvKeepsQualityTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_export_and_import_round_trip(self):
        self.db.upsert_product(Product(name="Хляб", quality="Q1",
                                       default_duration_sec=HOUR, unit_price=5))
        self.db.upsert_product(Product(name="Хляб", quality="Q5",
                                       default_duration_sec=2 * HOUR, unit_price=20))
        path = Path(tempfile.mkdtemp()) / "katalog.csv"
        self.assertEqual(catalog.export_csv(self.db, path), 2)

        for product in self.db.list_products():
            self.db.delete_product(product.id)
        catalog.import_csv(self.db, path)

        self.assertEqual(len(self.db.list_products()), 2)
        self.assertEqual(self.db.get_product("Хляб", "Q5").unit_price, 20)


class CategoriesMatchTheGameTest(unittest.TestCase):
    """Отраслите, които сайтът на играта назовава."""

    def test_industries_from_the_site_are_present(self):
        for industry in ("Агрокултура", "Животновъдство",
                         "Високи технологии", "Мода"):
            self.assertIn(industry, catalog.CATEGORIES)

    def test_seed_uses_only_known_categories(self):
        for name, category in catalog.SEED_PRODUCTS:
            self.assertIn(category, catalog.CATEGORIES, name)

    def test_seed_covers_every_industry(self):
        used = {category for _name, category in catalog.SEED_PRODUCTS}
        for industry in ("Агрокултура", "Животновъдство",
                         "Високи технологии", "Мода", "Суровини", "Строителни"):
            self.assertIn(industry, used)

    def test_seed_names_are_unique(self):
        names = [name for name, _c in catalog.SEED_PRODUCTS]
        self.assertEqual(len(names), len(set(names)))


OLD_SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT '',
    default_type TEXT NOT NULL DEFAULT 'production',
    default_duration_sec INTEGER NOT NULL DEFAULT 0,
    default_quantity REAL NOT NULL DEFAULT 0,
    unit_cost REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE timers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'production',
    quantity REAL NOT NULL DEFAULT 0,
    line TEXT NOT NULL DEFAULT '',
    start_at REAL NOT NULL, end_at REAL NOT NULL, duration_sec INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    repeat_enabled INTEGER NOT NULL DEFAULT 0,
    cycles_planned INTEGER NOT NULL DEFAULT 0,
    cycle_no INTEGER NOT NULL DEFAULT 1,
    prewarn_sec INTEGER NOT NULL DEFAULT 0,
    notified_at REAL, prewarned_at REAL, reminded_at REAL,
    missed INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'production',
    quantity REAL NOT NULL DEFAULT 0, line TEXT NOT NULL DEFAULT '',
    start_at REAL NOT NULL DEFAULT 0, end_at REAL NOT NULL DEFAULT 0,
    duration_sec INTEGER NOT NULL DEFAULT 0, finished_at REAL NOT NULL DEFAULT 0,
    cycle_no INTEGER NOT NULL DEFAULT 1, profit REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
INSERT INTO products (name, category, default_duration_sec, unit_price, unit_cost)
    VALUES ('Хляб', 'Храни', 3600, 5, 2),
           ('Стомана', 'Промишлени', 7200, 40, 10),
           ('Дъски', 'Строителни', 1800, 12, 4),
           ('Пшеница', 'Суровини', 900, 3, 1);
INSERT INTO timers (product, quantity, line, start_at, end_at, duration_sec, note)
    VALUES ('Стар таймер', 250, 'Линия 3', 0, 9999999999, 3600, 'бележка');
INSERT INTO history (product, quantity, duration_sec, profit)
    VALUES ('Стар запис', 10, 3600, 100);
"""


class MigrationTest(unittest.TestCase):
    """База от предишната версия трябва да се надгради без загуби."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="kapilands-migrate"),
                                 "staro.db")
        old = sqlite3.connect(self.path)
        old.executescript(OLD_SCHEMA)
        old.commit()
        old.close()

    def test_nothing_is_lost(self):
        db = Database(self.path)
        try:
            self.assertEqual(len(db.list_products()), 4)
            timers = db.list_timers(None)
            self.assertEqual(len(timers), 1)
            self.assertEqual(timers[0].product, "Стар таймер")
            self.assertEqual(timers[0].quantity, 250)
            self.assertEqual(timers[0].line, "Линия 3")
            self.assertEqual(timers[0].note, "бележка")
            self.assertEqual(len(db.list_history()), 1)
            self.assertEqual(db.list_history()[0].profit, 100)
        finally:
            db.close()

    def test_prices_survive(self):
        db = Database(self.path)
        try:
            bread = db.get_product("Хляб")
            self.assertEqual(bread.unit_price, 5)
            self.assertEqual(bread.unit_cost, 2)
            self.assertEqual(bread.default_duration_sec, 3600)
        finally:
            db.close()

    def test_old_rows_get_an_empty_quality(self):
        db = Database(self.path)
        try:
            self.assertEqual(db.list_timers(None)[0].quality, "")
            self.assertEqual(db.list_history()[0].quality, "")
            self.assertEqual(db.get_product("Хляб").quality, "")
        finally:
            db.close()

    def test_old_categories_become_the_game_industries(self):
        db = Database(self.path)
        try:
            categories = {p.name: p.category for p in db.list_products()}
            self.assertEqual(categories["Хляб"], "Агрокултура")
            self.assertEqual(categories["Стомана"], "Високи технологии")
            self.assertEqual(categories["Дъски"], "Строителни")   # без промяна
            self.assertEqual(categories["Пшеница"], "Суровини")   # без промяна
        finally:
            db.close()

    def test_quality_works_after_the_migration(self):
        db = Database(self.path)
        try:
            db.upsert_product(Product(name="Хляб", quality="Q5", unit_price=20))
            self.assertEqual(len(db.list_products()), 5)
            self.assertEqual(db.get_product("Хляб").unit_price, 5)
            self.assertEqual(db.get_product("Хляб", "Q5").unit_price, 20)
        finally:
            db.close()

    def test_opening_twice_changes_nothing(self):
        db = Database(self.path)
        db.close()
        db = Database(self.path)
        try:
            self.assertEqual(len(db.list_products()), 4)
            self.assertEqual(len(db.list_timers(None)), 1)
        finally:
            db.close()

    def test_a_fresh_database_needs_no_migration(self):
        path = os.path.join(tempfile.mkdtemp(), "novo.db")
        db = Database(path)
        db.close()
        db = Database(path)
        try:
            self.assertEqual(db.list_products(), [])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
