"""Тестове за световете, компаниите и надграждането на базата до v2."""

import os
import sqlite3
import tempfile
import unittest

from kapiland.db import SCHEMA_VERSION, Database
from kapiland.models import Account, Timer, TimerType, type_label
from kapiland.timeutil import HOUR

NOW = 1_000_000.0


class AccountModelTest(unittest.TestCase):
    def test_building_list(self):
        account = Account(name="Алфа", buildings="Мини; Плантация ;  ")
        self.assertEqual(account.building_list, ["Мини", "Плантация"])

    def test_add_building_skips_duplicates_case_insensitively(self):
        account = Account(name="Алфа", buildings="Мини")
        account.add_building("мини")
        account.add_building("Бензиностанции")
        account.add_building("  ")
        self.assertEqual(account.buildings, "Мини; Бензиностанции")

    def test_display_name(self):
        self.assertEqual(Account(name="Алфа", world="Немска двойка").display_name,
                         "Алфа (Немска двойка)")
        self.assertEqual(Account(name="Алфа").display_name, "Алфа")

    def test_expand_is_a_timer_type(self):
        self.assertEqual(TimerType.EXPAND.value, "expand")
        self.assertEqual(type_label("expand"), "Разширяване")


class AccountStorageTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_same_name_in_two_worlds_are_two_companies(self):
        self.db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        self.db.upsert_account(Account(world="Английска единица", name="Алфа"))
        self.assertEqual(len(self.db.list_accounts()), 2)

    def test_upsert_merges_buildings_instead_of_replacing(self):
        self.db.upsert_account(Account(world="Б1", name="Алфа", buildings="Плантация"))
        self.db.upsert_account(Account(world="Б1", name="алфа", buildings="Бензиностанции"))
        accounts = self.db.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].building_list, ["Плантация", "Бензиностанции"])

    def test_upsert_keeps_owner_unless_a_new_one_is_given(self):
        self.db.upsert_account(Account(world="Б1", name="Алфа", owner="Гошо"))
        self.db.upsert_account(Account(world="Б1", name="Алфа"))
        self.assertEqual(self.db.get_account("Б1", "Алфа").owner, "Гошо")
        self.db.upsert_account(Account(world="Б1", name="Алфа", owner="Пешо"))
        self.assertEqual(self.db.get_account("Б1", "Алфа").owner, "Пешо")

    def test_lookup_ignores_case_in_cyrillic(self):
        self.db.upsert_account(Account(world="Немска двойка", name="Бета ООД"))
        self.assertIsNotNone(self.db.get_account("немска ДВОЙКА", "бета оод"))

    def test_list_by_world(self):
        self.db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        self.db.upsert_account(Account(world="Немска двойка", name="Бета"))
        self.db.upsert_account(Account(world="Холандска единица", name="Гама"))
        names = [a.name for a in self.db.list_accounts("немска двойка")]
        self.assertEqual(names, ["Алфа", "Бета"])

    def test_update_and_delete(self):
        account = Account(world="Б1", name="Алфа")
        self.db.upsert_account(account)
        account.note = "бележка"
        self.db.update_account(account)
        self.assertEqual(self.db.get_account("Б1", "Алфа").note, "бележка")
        self.db.delete_account(account.id)
        self.assertEqual(self.db.list_accounts(), [])

    def test_worlds_come_from_companies_and_timers(self):
        self.db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        self.db.add_timer(Timer(product="Газ", world="Английска единица",
                                start_at=NOW, end_at=NOW + HOUR, duration_sec=HOUR))
        self.assertEqual(self.db.list_worlds(), ["Английска единица", "Немска двойка"])


class TimerWorldTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def make(self, **kwargs):
        data = dict(product="Бензин", line="Алфа", world="Немска двойка",
                    building="Химически фабрики", start_at=NOW, end_at=NOW + HOUR,
                    duration_sec=HOUR)
        data.update(kwargs)
        return Timer(**data)

    def test_world_and_building_are_stored(self):
        timer = self.make()
        self.db.add_timer(timer)
        stored = self.db.get_timer(timer.id)
        self.assertEqual(stored.world, "Немска двойка")
        self.assertEqual(stored.building, "Химически фабрики")

    def test_next_cycle_keeps_world_and_building(self):
        timer = self.make(repeat_enabled=1, cycles_planned=3)
        self.db.add_timer(timer)
        nxt = self.db.start_next_cycle(timer, start_at=NOW + HOUR)
        self.assertEqual((nxt.world, nxt.building), ("Немска двойка", "Химически фабрики"))

    def test_history_keeps_the_world(self):
        timer = self.make()
        self.db.add_timer(timer)
        self.db.complete_timer(timer.id, now=NOW + HOUR)
        self.assertEqual(self.db.list_history()[0].world, "Немска двойка")

    def test_expand_timer_round_trip(self):
        timer = self.make(type="expand", product="")
        self.db.add_timer(timer)
        self.assertEqual(self.db.get_timer(timer.id).type, "expand")


class MetaTest(unittest.TestCase):
    def test_schema_version_is_recorded(self):
        db = Database(":memory:")
        try:
            self.assertEqual(db.get_meta("schema_version"), str(SCHEMA_VERSION))
        finally:
            db.close()

    def test_set_and_overwrite(self):
        db = Database(":memory:")
        try:
            self.assertEqual(db.get_meta("x", "няма"), "няма")
            db.set_meta("x", "1")
            db.set_meta("x", "2")
            self.assertEqual(db.get_meta("x"), "2")
        finally:
            db.close()


V1_SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
    default_type TEXT NOT NULL DEFAULT 'production',
    default_duration_sec INTEGER NOT NULL DEFAULT 0,
    default_quantity REAL NOT NULL DEFAULT 0, unit_cost REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
    UNIQUE(name, quality)
);
CREATE TABLE timers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT NOT NULL DEFAULT '',
    quality TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'production',
    quantity REAL NOT NULL DEFAULT 0, line TEXT NOT NULL DEFAULT '',
    start_at REAL NOT NULL, end_at REAL NOT NULL, duration_sec INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running', repeat_enabled INTEGER NOT NULL DEFAULT 0,
    cycles_planned INTEGER NOT NULL DEFAULT 0, cycle_no INTEGER NOT NULL DEFAULT 1,
    prewarn_sec INTEGER NOT NULL DEFAULT 0, notified_at REAL, prewarned_at REAL,
    reminded_at REAL, missed INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT NOT NULL DEFAULT '',
    quality TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'production',
    quantity REAL NOT NULL DEFAULT 0, line TEXT NOT NULL DEFAULT '',
    start_at REAL NOT NULL DEFAULT 0, end_at REAL NOT NULL DEFAULT 0,
    duration_sec INTEGER NOT NULL DEFAULT 0, finished_at REAL NOT NULL DEFAULT 0,
    cycle_no INTEGER NOT NULL DEFAULT 1, profit REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
INSERT INTO products (name, quality, category, unit_price) VALUES ('Хляб', 'Q2', 'Агрокултура', 5);
INSERT INTO timers (product, quality, quantity, line, start_at, end_at, duration_sec)
    VALUES ('Бензин', 'Q1', 1000, 'Линия 2', 0, 9999999999, 3600);
INSERT INTO history (product, quality, profit) VALUES ('Сирене', '', 42);
"""


class MigrationV1ToV2Test(unittest.TestCase):
    """База от v1.0 (с качество, без светове) трябва да мине без загуби."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="kapilands-v1"), "v1.db")
        conn = sqlite3.connect(self.path)
        conn.executescript(V1_SCHEMA)
        conn.commit()
        conn.close()

    def test_everything_survives(self):
        db = Database(self.path)
        try:
            timer = db.list_timers(None)[0]
            self.assertEqual((timer.product, timer.quality, timer.quantity, timer.line),
                             ("Бензин", "Q1", 1000, "Линия 2"))
            self.assertEqual((timer.world, timer.building), ("", ""))
            self.assertEqual(db.get_product("Хляб", "Q2").unit_price, 5)
            self.assertEqual(db.list_history()[0].profit, 42)
            self.assertEqual(db.list_history()[0].world, "")
        finally:
            db.close()

    def test_new_tables_and_version_appear(self):
        db = Database(self.path)
        try:
            self.assertEqual(db.list_accounts(), [])
            self.assertEqual(db.get_meta("schema_version"), str(SCHEMA_VERSION))
        finally:
            db.close()

    def test_new_fields_work_after_migration(self):
        db = Database(self.path)
        try:
            db.upsert_account(Account(world="Немска двойка", name="Алфа"))
            db.add_timer(Timer(product="Ток", world="Немска двойка", line="Алфа",
                               start_at=NOW, end_at=NOW + HOUR, duration_sec=HOUR))
            self.assertEqual(db.list_worlds(), ["Немска двойка"])
        finally:
            db.close()

    def test_opening_again_changes_nothing(self):
        Database(self.path).close()
        db = Database(self.path)
        try:
            self.assertEqual(len(db.list_timers(None)), 1)
            self.assertEqual(len(db.list_products()), 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
