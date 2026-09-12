"""Тестове за известяването: кога излиза „готово“, кога предупреждение."""

import unittest

from kapiland.config import Settings
from kapiland.db import Database
from kapiland.models import Timer
from kapiland.scheduler import (
    EVENT_DUE,
    EVENT_MISSED,
    EVENT_PREWARN,
    EVENT_REMIND,
    Scheduler,
)
from kapiland.timeutil import HOUR, MINUTE

NOW = 1_000_000.0


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify_async(self, title, message, urgent=False):
        self.sent.append((title, message, urgent))

    notify = notify_async


class FakeSettings(Settings):
    def __init__(self, **overrides):
        self._path = None
        from kapiland.config import DEFAULTS
        self._data = dict(DEFAULTS)
        self._data.update(overrides)

    def save(self):
        pass


def make_timer(**kwargs) -> Timer:
    data = dict(product="Хляб", quantity=500, line="Линия 1",
                start_at=NOW, end_at=NOW + HOUR, duration_sec=HOUR)
    data.update(kwargs)
    return Timer(**data)


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.notifier = FakeNotifier()

    def tearDown(self):
        self.db.close()

    def scheduler(self, **settings):
        return Scheduler(self.db, self.notifier, FakeSettings(**settings))

    # ------------------------------------------------------------------

    def test_no_events_while_running(self):
        self.db.add_timer(make_timer())
        self.assertEqual(self.scheduler().tick(now=NOW + MINUTE), [])
        self.assertEqual(self.notifier.sent, [])

    def test_due_event_fires_once(self):
        timer = make_timer()
        self.db.add_timer(timer)
        sched = self.scheduler(repeat_reminder_minutes=0)

        events = sched.tick(now=NOW + HOUR)
        self.assertEqual([e.kind for e in events], [EVENT_DUE])
        self.assertIn("Хляб", events[0].title)
        self.assertEqual(len(self.notifier.sent), 1)

        # Второ минаване не праща ново известие.
        self.assertEqual(sched.tick(now=NOW + HOUR + 1), [])
        self.assertEqual(len(self.notifier.sent), 1)

    def test_prewarn_before_the_end(self):
        self.db.add_timer(make_timer(prewarn_sec=10 * MINUTE))
        sched = self.scheduler()

        self.assertEqual(sched.tick(now=NOW + 40 * MINUTE), [])
        events = sched.tick(now=NOW + 50 * MINUTE)
        self.assertEqual([e.kind for e in events], [EVENT_PREWARN])
        self.assertIn("Скоро готово", events[0].title)
        # Само веднъж.
        self.assertEqual(sched.tick(now=NOW + 55 * MINUTE), [])

    def test_prewarn_from_settings_applies_to_all(self):
        self.db.add_timer(make_timer())
        sched = self.scheduler(prewarn_minutes=5)
        self.assertEqual(sched.tick(now=NOW + 50 * MINUTE), [])
        events = sched.tick(now=NOW + 56 * MINUTE)
        self.assertEqual([e.kind for e in events], [EVENT_PREWARN])

    def test_reminder_repeats_until_acknowledged(self):
        timer = make_timer()
        self.db.add_timer(timer)
        sched = self.scheduler(repeat_reminder_minutes=5)

        sched.tick(now=NOW + HOUR)                       # „готово“
        self.assertEqual(sched.tick(now=NOW + HOUR + 60), [])   # рано за напомняне
        events = sched.tick(now=NOW + HOUR + 5 * MINUTE)
        self.assertEqual([e.kind for e in events], [EVENT_REMIND])
        events = sched.tick(now=NOW + HOUR + 10 * MINUTE)
        self.assertEqual([e.kind for e in events], [EVENT_REMIND])

    def test_no_reminder_when_switched_off(self):
        self.db.add_timer(make_timer())
        sched = self.scheduler(repeat_reminder_minutes=0)
        sched.tick(now=NOW + HOUR)
        self.assertEqual(sched.tick(now=NOW + HOUR + HOUR), [])

    def test_completed_timer_stops_producing_events(self):
        timer = make_timer()
        self.db.add_timer(timer)
        sched = self.scheduler(repeat_reminder_minutes=5)
        sched.tick(now=NOW + HOUR)
        self.db.complete_timer(timer.id, now=NOW + HOUR)
        self.assertEqual(sched.tick(now=NOW + HOUR + 10 * MINUTE), [])

    def test_several_at_once_send_one_summary(self):
        self.db.add_timer(make_timer(product="Хляб"))
        self.db.add_timer(make_timer(product="Сирене"))
        sched = self.scheduler()
        events = sched.tick(now=NOW + HOUR)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(self.notifier.sent), 1)
        self.assertIn("Готови са 2", self.notifier.sent[0][0])

    # ------------------------------------------------------------------

    def test_catch_up_reports_timers_expired_while_closed(self):
        self.db.add_timer(make_timer(product="Хляб", end_at=NOW - HOUR))
        self.db.add_timer(make_timer(product="Стомана", end_at=NOW + HOUR))
        sched = self.scheduler()

        events = sched.catch_up(now=NOW)
        self.assertEqual([e.kind for e in events], [EVENT_MISSED])
        self.assertIn("Пропуснато", events[0].title)
        self.assertEqual(events[0].timer.product, "Хляб")

    def test_catch_up_does_not_repeat_on_next_start(self):
        self.db.add_timer(make_timer(end_at=NOW - HOUR))
        sched = self.scheduler()
        sched.catch_up(now=NOW)
        self.assertEqual(sched.catch_up(now=NOW + MINUTE), [])

    def test_messages_mention_the_product_and_the_line(self):
        self.db.add_timer(make_timer(product="Хляб", quantity=500, line="Линия 2"))
        sched = self.scheduler()
        events = sched.tick(now=NOW + HOUR)
        title, message, urgent = self.notifier.sent[0]
        self.assertIn("500× Хляб", title)
        self.assertIn("Линия 2", title)
        self.assertIn("следваща продукция", message)
        self.assertTrue(urgent)

    def test_message_matches_the_timer_type(self):
        self.db.add_timer(make_timer(product="Химия", type="research"))
        sched = self.scheduler()
        sched.tick(now=NOW + HOUR)
        self.assertIn("изследване", self.notifier.sent[0][1])


if __name__ == "__main__":
    unittest.main()
