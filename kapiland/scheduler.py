"""Следене на таймерите: кой е изтекъл, кой е пред изтичане, кого да напомним.

Няма собствена нишка — интерфейсът извиква ``tick()`` веднъж в секунда.
Така няма състезания между нишките, а обратното броене се смята винаги от
крайния час, не чрез натрупване на тикове (не се разминава при заспиване
на компютъра).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import TYPE_ACTIONS, Timer, TimerStatus, type_label
from .timeutil import format_duration, format_dt_relative, now as time_now

EVENT_PREWARN = "prewarn"
EVENT_DUE = "due"
EVENT_REMIND = "remind"
EVENT_MISSED = "missed"


@dataclass
class Event:
    kind: str
    timer: Timer
    title: str
    message: str

    @property
    def urgent(self) -> bool:
        return self.kind in (EVENT_DUE, EVENT_MISSED, EVENT_REMIND)


def build_message(timer: Timer, kind: str, now: float) -> tuple[str, str]:
    """Заглавие и текст на известието."""
    name = timer.display_name
    where = f" — {timer.line}" if timer.line.strip() else ""
    action = TYPE_ACTIONS.get(timer.type, "Пусни следващото.")

    if kind == EVENT_PREWARN:
        left = format_duration(max(0.0, timer.end_at - now))
        return (f"Скоро готово: {name}{where}",
                f"Остават {left}. Приготви се да пуснеш следващото.")
    if kind == EVENT_MISSED:
        when = format_dt_relative(timer.end_at, now)
        return (f"Пропуснато: {name}{where}",
                f"Готово беше в {when}. {action}")
    if kind == EVENT_REMIND:
        waiting = format_duration(max(0.0, now - timer.end_at))
        return (f"Още чака: {name}{where}",
                f"Готово от {waiting}. {action}")
    return (f"Готово: {name}{where}", action)


class Scheduler:
    """Свързва базата с известията."""

    def __init__(self, db, notifier, settings) -> None:
        self.db = db
        self.notifier = notifier
        self.settings = settings
        self.last_events: list[Event] = []

    # ------------------------------------------------------------------

    def soon_seconds(self) -> int:
        return int(self.settings.get("prewarn_minutes", 0) or 0) * 60

    def reminder_seconds(self) -> int:
        return int(self.settings.get("repeat_reminder_minutes", 0) or 0) * 60

    # ------------------------------------------------------------------

    def catch_up(self, now: float | None = None) -> list[Event]:
        """Таймери, изтекли докато приложението е било затворено."""
        ts = time_now() if now is None else now
        events = []
        for timer in self.db.mark_missed_on_startup(ts):
            title, message = build_message(timer, EVENT_MISSED, ts)
            events.append(Event(EVENT_MISSED, timer, title, message))
        if events:
            self._announce(events, summary_kind=EVENT_MISSED)
        self.last_events = events
        return events

    def tick(self, now: float | None = None, announce: bool = True) -> list[Event]:
        """Проверява всички активни таймери и издава събития."""
        ts = time_now() if now is None else now
        events: list[Event] = []
        reminder = self.reminder_seconds()

        for timer in self.db.list_timers(TimerStatus.RUNNING.value):
            if timer.id is None:
                continue

            # Готово за първи път.
            if ts >= timer.end_at and timer.notified_at is None:
                self.db.set_timer_fields(timer.id, notified_at=ts, missed=0)
                timer.notified_at = ts
                title, message = build_message(timer, EVENT_DUE, ts)
                events.append(Event(EVENT_DUE, timer, title, message))
                continue

            # Напомняне, докато не бъде потвърдено.
            if ts >= timer.end_at and timer.notified_at is not None and reminder > 0:
                last = max(timer.notified_at, timer.reminded_at or 0.0)
                if ts - last >= reminder:
                    self.db.set_timer_fields(timer.id, reminded_at=ts)
                    timer.reminded_at = ts
                    title, message = build_message(timer, EVENT_REMIND, ts)
                    events.append(Event(EVENT_REMIND, timer, title, message))
                continue

            # Предварително предупреждение.
            prewarn = timer.prewarn_sec or self.soon_seconds()
            if (prewarn > 0 and timer.prewarned_at is None
                    and ts >= timer.end_at - prewarn and ts < timer.end_at):
                self.db.set_timer_fields(timer.id, prewarned_at=ts)
                timer.prewarned_at = ts
                title, message = build_message(timer, EVENT_PREWARN, ts)
                events.append(Event(EVENT_PREWARN, timer, title, message))

        if events and announce:
            self._announce(events)
        self.last_events = events
        return events

    # ------------------------------------------------------------------

    def _announce(self, events: list[Event], summary_kind: str = EVENT_DUE) -> None:
        """Известява; при няколко наведнъж праща едно обобщено известие."""
        from .notify import play_sound_async

        sound_on = bool(self.settings.get("sound_enabled", True))
        toast_on = bool(self.settings.get("toast_enabled", True))
        play_sound_async(str(self.settings.get("sound_file", "")), sound_on)
        if not toast_on:
            return

        if len(events) == 1:
            event = events[0]
            self.notifier.notify_async(event.title, event.message, event.urgent)
            return

        names = ", ".join(e.timer.display_name for e in events[:4])
        if len(events) > 4:
            names += f" и още {len(events) - 4}"
        word = "неща" if len(events) != 1 else "нещо"
        title = f"Готови са {len(events)} {word}"
        if summary_kind == EVENT_MISSED:
            title = f"Пропуснати са {len(events)} {word}"
        self.notifier.notify_async(title, names, urgent=True)
