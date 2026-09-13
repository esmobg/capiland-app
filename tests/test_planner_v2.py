"""Тестове за бездействащите компании и изговореното обобщение."""

import unittest
from datetime import datetime

from kapiland import planner
from kapiland.models import Account, Timer, TimerStatus

NOW = datetime(2026, 9, 13, 12, 0).timestamp()
HOUR = 3600


def timer(**kwargs):
    data = dict(product="Бензин", quantity=1000, line="Алфа", world="Немска двойка",
                start_at=NOW - HOUR, end_at=NOW + HOUR, duration_sec=2 * HOUR)
    data.update(kwargs)
    return Timer(**data)


class IdleAccountsTest(unittest.TestCase):
    def setUp(self):
        self.accounts = [
            Account(world="Немска двойка", name="Алфа"),
            Account(world="Немска двойка", name="Бета"),
            Account(world="Английска единица", name="Алфа"),
        ]

    def test_company_with_a_running_timer_is_busy(self):
        idle = planner.idle_accounts(self.accounts, [timer()], NOW)
        self.assertEqual([(a.world, a.name) for a in idle],
                         [("Немска двойка", "Бета"), ("Английска единица", "Алфа")])

    def test_same_name_in_another_world_is_not_busy(self):
        idle = planner.idle_accounts(self.accounts, [timer()], NOW)
        self.assertIn(("Английска единица", "Алфа"), [(a.world, a.name) for a in idle])

    def test_finished_timer_frees_the_company(self):
        idle = planner.idle_accounts(self.accounts, [timer(end_at=NOW - 1)], NOW)
        self.assertEqual(len(idle), 3)

    def test_cancelled_timer_does_not_count(self):
        idle = planner.idle_accounts(
            self.accounts, [timer(status=TimerStatus.CANCELLED.value)], NOW)
        self.assertEqual(len(idle), 3)

    def test_case_insensitive_match(self):
        idle = planner.idle_accounts(self.accounts, [timer(line="алфа", world="немска двойка")], NOW)
        self.assertEqual(len(idle), 2)

    def test_account_timers(self):
        timers = [timer(end_at=NOW + 2 * HOUR), timer(end_at=NOW + HOUR), timer(line="Бета")]
        found = planner.account_timers(self.accounts[0], timers)
        self.assertEqual([t.end_at for t in found], [NOW + HOUR, NOW + 2 * HOUR])


class SpokenTest(unittest.TestCase):
    def test_describe(self):
        self.assertEqual(planner.describe_spoken(timer()), "1000× Бензин, Алфа, Немска двойка")
        research = timer(product="", quantity=0, line="", type="research", world="Немска единица")
        self.assertEqual(planner.describe_spoken(research), "Наука, Немска единица")

    def test_nothing_running(self):
        self.assertEqual(planner.spoken_summary([], NOW), "Няма активни таймери.")

    def test_nothing_ready_says_what_is_next(self):
        text = planner.spoken_summary([timer(end_at=NOW + 5 * HOUR)], NOW)
        self.assertEqual(text, "Нищо не е готово. Следващо: 1000× Бензин, Алфа, "
                               "Немска двойка, днес в 17 часа.")

    def test_ready_items_are_listed_and_capped(self):
        timers = [timer(product=p, end_at=NOW - i) for i, p in
                  enumerate(["Бензин", "Газ", "Ток", "Вода"], start=1)]
        timers.append(timer(product="Легла", quantity=0, line="Бета", end_at=NOW + HOUR))
        text = planner.spoken_summary(timers, NOW, limit=3)
        self.assertTrue(text.startswith("Готови 4: "))
        self.assertIn("; и още 1.", text)
        self.assertIn("Следващо: Легла, Бета, Немска двойка, днес в 13 часа.", text)

    def test_group_by_world(self):
        groups = planner.group_by_world([timer(world="Холандска единица"),
                                         timer(world="Английска единица", end_at=NOW + 9),
                                         timer(world="Английска единица", end_at=NOW + 1)])
        self.assertEqual(list(groups), ["Английска единица", "Холандска единица"])
        self.assertEqual([t.end_at for t in groups["Английска единица"]], [NOW + 1, NOW + 9])


if __name__ == "__main__":
    unittest.main()
