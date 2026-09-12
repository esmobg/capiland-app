"""Тестове за изчисленията."""

import unittest

from kapiland import planner
from kapiland.models import Timer, TimerStatus
from kapiland.timeutil import DAY, HOUR, MINUTE

NOW = 1_000_000.0


def make_timer(**kwargs) -> Timer:
    data = dict(product="Хляб", quantity=100, line="Линия 1",
                start_at=NOW, end_at=NOW + HOUR, duration_sec=HOUR,
                status=TimerStatus.RUNNING.value)
    data.update(kwargs)
    return Timer(**data)


class EndTimeTest(unittest.TestCase):
    def test_start_plus_duration(self):
        self.assertEqual(planner.end_from_start_duration(NOW, 3 * HOUR + 45 * MINUTE),
                         NOW + 13500)

    def test_duration_from_end(self):
        self.assertEqual(planner.duration_from_start_end(NOW, NOW + 13500), 13500)

    def test_end_from_remaining(self):
        self.assertEqual(planner.end_from_remaining(13330, NOW), NOW + 13330)

    def test_negative_inputs_rejected(self):
        with self.assertRaises(ValueError):
            planner.end_from_start_duration(NOW, -1)
        with self.assertRaises(ValueError):
            planner.duration_from_start_end(NOW, NOW - 1)
        with self.assertRaises(ValueError):
            planner.end_from_remaining(-5, NOW)

    def test_three_modes_agree(self):
        """Трите начина за въвеждане трябва да дават един и същ краен час."""
        duration = 3 * HOUR + 45 * MINUTE
        by_duration = planner.end_from_start_duration(NOW, duration)
        by_end = NOW + planner.duration_from_start_end(NOW, NOW + duration)
        by_remaining = planner.end_from_remaining(duration, NOW)
        self.assertEqual(by_duration, by_end)
        self.assertEqual(by_duration, by_remaining)

    def test_progress_and_remaining(self):
        timer = make_timer()
        self.assertAlmostEqual(planner.remaining(timer, NOW + 900), 2700)
        self.assertAlmostEqual(planner.progress(timer, NOW + 1800), 0.5)
        self.assertEqual(planner.progress(timer, NOW - 100), 0.0)
        self.assertEqual(planner.progress(timer, NOW + 10 * HOUR), 1.0)

    def test_next_start_suggestion(self):
        self.assertEqual(planner.next_start_suggestion(NOW + HOUR, 5 * MINUTE),
                         NOW + HOUR - 300)
        self.assertEqual(planner.next_start_suggestion(NOW + HOUR, 0), NOW + HOUR)


class ThroughputTest(unittest.TestCase):
    def test_per_hour_and_day(self):
        rate = planner.throughput(100, HOUR)
        self.assertAlmostEqual(rate.per_hour, 100)
        self.assertAlmostEqual(rate.per_day, 2400)
        self.assertAlmostEqual(rate.seconds_per_unit, 36)

    def test_half_hour_batch(self):
        rate = planner.throughput(50, 30 * MINUTE)
        self.assertAlmostEqual(rate.per_hour, 100)

    def test_zero_is_safe(self):
        self.assertEqual(planner.throughput(0, HOUR).per_hour, 0)
        self.assertEqual(planner.throughput(10, 0).per_hour, 0)

    def test_cycles_per_day(self):
        self.assertAlmostEqual(planner.cycles_per_day(6 * HOUR), 4)
        self.assertEqual(planner.cycles_per_day(0), 0)


class ProfitTest(unittest.TestCase):
    def test_total_and_per_hour(self):
        money = planner.profit(quantity=100, unit_cost=2.0, unit_price=5.0,
                               duration_sec=2 * HOUR)
        self.assertAlmostEqual(money.per_unit, 3.0)
        self.assertAlmostEqual(money.total, 300.0)
        self.assertAlmostEqual(money.per_hour, 150.0)
        self.assertAlmostEqual(money.per_day, 3600.0)

    def test_loss(self):
        money = planner.profit(10, 5.0, 3.0, HOUR)
        self.assertAlmostEqual(money.total, -20.0)

    def test_ranking_picks_best_per_hour(self):
        ranked = planner.rank_by_profit_per_hour([
            {"name": "Бавен", "quantity": 100, "unit_cost": 0, "unit_price": 10,
             "duration_sec": 10 * HOUR},
            {"name": "Бърз", "quantity": 10, "unit_cost": 0, "unit_price": 10,
             "duration_sec": 30 * MINUTE},
        ])
        self.assertEqual(ranked[0]["name"], "Бърз")
        self.assertAlmostEqual(ranked[0]["profit_per_hour"], 200.0)


class LinesTest(unittest.TestCase):
    def setUp(self):
        self.lines = ["Линия 1", "Линия 2", "Линия 3"]
        self.timers = [
            make_timer(id=1, line="Линия 1", end_at=NOW + HOUR),
            make_timer(id=2, line="Линия 2", end_at=NOW + 10 * MINUTE),
        ]

    def test_free_lines(self):
        self.assertEqual(planner.free_lines(self.timers, self.lines, NOW), ["Линия 3"])

    def test_busy_line_carries_its_timer(self):
        statuses = {s.name: s for s in planner.line_status(self.timers, self.lines, NOW)}
        self.assertTrue(statuses["Линия 1"].busy)
        self.assertEqual(statuses["Линия 1"].timer.id, 1)
        self.assertFalse(statuses["Линия 3"].busy)

    def test_next_line_free_at(self):
        self.assertIsNone(planner.next_line_free_at(self.timers, self.lines, NOW))
        two = ["Линия 1", "Линия 2"]
        self.assertEqual(planner.next_line_free_at(self.timers, two, NOW),
                         NOW + 10 * MINUTE)

    def test_finished_timer_frees_the_line(self):
        timers = [make_timer(id=1, line="Линия 1", end_at=NOW - 1)]
        self.assertIn("Линия 1", planner.free_lines(timers, self.lines, NOW))

    def test_idle_time(self):
        timers = [make_timer(id=1, line="Линия 1", start_at=NOW, end_at=NOW + 6 * HOUR)]
        idle = planner.idle_time(timers, "Линия 1", NOW, DAY)
        self.assertAlmostEqual(idle, 18 * HOUR)


class CollisionTest(unittest.TestCase):
    def test_groups_close_endings(self):
        timers = [
            make_timer(id=1, end_at=NOW + 3600),
            make_timer(id=2, end_at=NOW + 3660),   # 1 минута по-късно
            make_timer(id=3, end_at=NOW + 20000),  # далеч
        ]
        groups = planner.find_collisions(timers, window_sec=5 * MINUTE, now=NOW)
        self.assertEqual(len(groups), 1)
        self.assertEqual([t.id for t in groups[0]], [1, 2])

    def test_no_collision_when_far_apart(self):
        timers = [make_timer(id=1, end_at=NOW + 3600),
                  make_timer(id=2, end_at=NOW + 9000)]
        self.assertEqual(planner.find_collisions(timers, 5 * MINUTE, NOW), [])


class AgendaTest(unittest.TestCase):
    def test_orders_and_filters_by_horizon(self):
        timers = [
            make_timer(id=1, end_at=NOW + 2 * HOUR),
            make_timer(id=2, end_at=NOW + 30 * MINUTE),
            make_timer(id=3, end_at=NOW + 3 * DAY),  # извън хоризонта
        ]
        items = planner.agenda(timers, NOW, DAY)
        self.assertEqual([i.timer.id for i in items], [2, 1])
        self.assertAlmostEqual(items[0].in_seconds, 30 * MINUTE)

    def test_next_due_and_due_now(self):
        timers = [
            make_timer(id=1, end_at=NOW - 10),   # вече готов
            make_timer(id=2, end_at=NOW + 600),
        ]
        self.assertEqual(planner.next_due(timers, NOW).id, 2)
        self.assertEqual([t.id for t in planner.due_now(timers, NOW)], [1])

    def test_completed_timers_are_ignored(self):
        timers = [make_timer(id=1, end_at=NOW - 10,
                             status=TimerStatus.DONE.value)]
        self.assertEqual(planner.due_now(timers, NOW), [])
        self.assertIsNone(planner.next_due(timers, NOW))


class HistoryStatsTest(unittest.TestCase):
    def test_summary_groups_by_product(self):
        from kapiland.models import HistoryEntry

        entries = [
            HistoryEntry(product="Хляб", quantity=100, duration_sec=HOUR, profit=300),
            HistoryEntry(product="Хляб", quantity=100, duration_sec=HOUR, profit=300),
            HistoryEntry(product="Стомана", quantity=10, duration_sec=2 * HOUR,
                         profit=100),
        ]
        rows = {r["product"]: r for r in planner.summarize_history(entries)}
        self.assertEqual(rows["Хляб"]["cycles"], 2)
        self.assertAlmostEqual(rows["Хляб"]["quantity"], 200)
        self.assertAlmostEqual(rows["Хляб"]["avg_seconds"], HOUR)
        self.assertAlmostEqual(rows["Хляб"]["profit_per_hour"], 300)
        self.assertAlmostEqual(rows["Стомана"]["profit_per_hour"], 50)

    def test_empty_history(self):
        self.assertEqual(planner.summarize_history([]), [])


if __name__ == "__main__":
    unittest.main()
