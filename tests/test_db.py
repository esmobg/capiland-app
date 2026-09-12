"""Тестове за базата и за повторението на циклите."""

import unittest

from kapiland.db import Database
from kapiland.models import Product, Timer, TimerStatus
from kapiland.timeutil import HOUR

NOW = 1_000_000.0


def make_timer(**kwargs) -> Timer:
    data = dict(product="Хляб", quantity=500, line="Линия 1",
                start_at=NOW, end_at=NOW + HOUR, duration_sec=HOUR)
    data.update(kwargs)
    return Timer(**data)


class TimerCrudTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_add_and_read(self):
        timer = make_timer()
        timer_id = self.db.add_timer(timer)
        self.assertIsNotNone(timer_id)
        stored = self.db.get_timer(timer_id)
        self.assertEqual(stored.product, "Хляб")
        self.assertEqual(stored.quantity, 500)
        self.assertEqual(stored.duration_sec, HOUR)
        self.assertEqual(stored.status, TimerStatus.RUNNING.value)

    def test_update(self):
        timer = make_timer()
        self.db.add_timer(timer)
        timer.product = "Сирене"
        timer.end_at = NOW + 2 * HOUR
        self.db.update_timer(timer)
        self.assertEqual(self.db.get_timer(timer.id).product, "Сирене")
        self.assertEqual(self.db.get_timer(timer.id).end_at, NOW + 2 * HOUR)

    def test_set_fields_ignores_unknown(self):
        timer = make_timer()
        self.db.add_timer(timer)
        self.db.set_timer_fields(timer.id, note="проба", nesushtestvuvashto=1)
        self.assertEqual(self.db.get_timer(timer.id).note, "проба")

    def test_delete(self):
        timer = make_timer()
        self.db.add_timer(timer)
        self.db.delete_timer(timer.id)
        self.assertIsNone(self.db.get_timer(timer.id))

    def test_list_only_running(self):
        running = make_timer()
        self.db.add_timer(running)
        cancelled = make_timer(status=TimerStatus.CANCELLED.value)
        self.db.add_timer(cancelled)
        ids = [t.id for t in self.db.list_timers(TimerStatus.RUNNING.value)]
        self.assertEqual(ids, [running.id])
        self.assertEqual(len(self.db.list_timers(None)), 2)


class CompletionTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_complete_writes_history(self):
        timer = make_timer()
        self.db.add_timer(timer)
        self.db.complete_timer(timer.id, now=NOW + HOUR, profit=1500)
        self.assertEqual(self.db.get_timer(timer.id).status, TimerStatus.DONE.value)
        history = self.db.list_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].product, "Хляб")
        self.assertEqual(history[0].profit, 1500)
        self.assertEqual(history[0].finished_at, NOW + HOUR)

    def test_completed_timer_leaves_the_active_list(self):
        timer = make_timer()
        self.db.add_timer(timer)
        self.db.complete_timer(timer.id, now=NOW + HOUR)
        self.assertEqual(self.db.list_timers(TimerStatus.RUNNING.value), [])

    def test_next_cycle_created_with_same_duration(self):
        timer = make_timer(repeat_enabled=1, cycles_planned=3)
        self.db.add_timer(timer)
        nxt = self.db.start_next_cycle(timer, start_at=NOW + HOUR)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.cycle_no, 2)
        self.assertEqual(nxt.duration_sec, HOUR)
        self.assertEqual(nxt.end_at, NOW + 2 * HOUR)
        self.assertEqual(nxt.product, "Хляб")
        self.assertEqual(nxt.cycle_text, "2/3")

    def test_no_cycle_after_the_last_one(self):
        timer = make_timer(repeat_enabled=1, cycles_planned=3, cycle_no=3)
        self.db.add_timer(timer)
        self.assertIsNone(self.db.start_next_cycle(timer, start_at=NOW))

    def test_endless_repeat(self):
        timer = make_timer(repeat_enabled=1, cycles_planned=0, cycle_no=99)
        self.db.add_timer(timer)
        nxt = self.db.start_next_cycle(timer, start_at=NOW)
        self.assertEqual(nxt.cycle_no, 100)
        self.assertEqual(nxt.cycle_text, "100/∞")

    def test_no_cycle_without_repeat(self):
        timer = make_timer(repeat_enabled=0)
        self.db.add_timer(timer)
        self.assertIsNone(self.db.start_next_cycle(timer, start_at=NOW))


class MissedTest(unittest.TestCase):
    """Таймери, изтекли докато приложението е било затворено."""

    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_expired_timer_is_marked_missed(self):
        timer = make_timer(end_at=NOW - 10)
        self.db.add_timer(timer)
        missed = self.db.mark_missed_on_startup(now=NOW)
        self.assertEqual([t.id for t in missed], [timer.id])
        stored = self.db.get_timer(timer.id)
        self.assertEqual(stored.missed, 1)
        self.assertEqual(stored.notified_at, NOW)

    def test_running_timer_is_not_touched(self):
        timer = make_timer(end_at=NOW + HOUR)
        self.db.add_timer(timer)
        self.assertEqual(self.db.mark_missed_on_startup(now=NOW), [])
        self.assertEqual(self.db.get_timer(timer.id).missed, 0)

    def test_already_notified_is_not_reported_twice(self):
        timer = make_timer(end_at=NOW - 10)
        self.db.add_timer(timer)
        self.db.mark_missed_on_startup(now=NOW)
        self.assertEqual(self.db.mark_missed_on_startup(now=NOW + 60), [])


class ProductTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_upsert_updates_existing(self):
        self.db.upsert_product(Product(name="Хляб", unit_price=5))
        self.db.upsert_product(Product(name="Хляб", unit_price=7))
        products = self.db.list_products()
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].unit_price, 7)

    def test_lookup_is_case_insensitive_in_cyrillic(self):
        self.db.upsert_product(Product(name="Хляб"))
        self.assertIsNotNone(self.db.get_product("хляб"))
        self.assertIsNotNone(self.db.get_product("ХЛЯБ"))

    def test_remember_product_stores_last_used_values(self):
        timer = make_timer(product="Сирене", quantity=42, duration_sec=7200,
                           type="research")
        self.db.remember_product(timer)
        product = self.db.get_product("Сирене")
        self.assertEqual(product.default_duration_sec, 7200)
        self.assertEqual(product.default_quantity, 42)
        self.assertEqual(product.default_type, "research")

    def test_remember_ignores_empty_name(self):
        self.db.remember_product(make_timer(product="   "))
        self.assertEqual(self.db.list_products(), [])

    def test_delete(self):
        product = Product(name="Хляб")
        self.db.upsert_product(product)
        self.db.delete_product(product.id)
        self.assertEqual(self.db.list_products(), [])


class CatalogSeedTest(unittest.TestCase):
    def test_seed_runs_only_once(self):
        from kapiland import catalog

        db = Database(":memory:")
        try:
            first = catalog.ensure_seed(db)
            self.assertGreater(first, 0)
            self.assertEqual(catalog.ensure_seed(db), 0)
            self.assertEqual(len(db.list_products()), first)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
