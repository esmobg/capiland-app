"""Раздел „Таймери“."""

from __future__ import annotations

import wx

from .. import planner
from ..models import STATE_DUE, STATE_MISSED, Timer, TimerStatus, type_label
from ..timeutil import (
    DAY,
    format_duration,
    format_remaining_words,
    format_when,
    format_when_spoken,
    now as time_now,
)
from .common import RowList, confirm, read_only_text
from .timer_dialog import TimerDialog

SHOW_ALL, SHOW_DUE, SHOW_24H = 0, 1, 2
ALL_WORLDS = "Всички светове"

COLUMNS = [
    ("Кога", 170, wx.LIST_FORMAT_LEFT),
    ("Продукт", 170, wx.LIST_FORMAT_LEFT),
    ("Количество", 95, wx.LIST_FORMAT_RIGHT),
    ("Компания", 150, wx.LIST_FORMAT_LEFT),
    ("Свят", 140, wx.LIST_FORMAT_LEFT),
    ("Дейност", 110, wx.LIST_FORMAT_LEFT),
    ("Сграда", 160, wx.LIST_FORMAT_LEFT),
]
COUNTDOWN_COLUMN = ("Остава", 95, wx.LIST_FORMAT_RIGHT)


def when_text(timer: Timer, now: float, soon: int) -> str:
    """Неподвижен текст: мени се само когато се мени състоянието."""
    state = timer.state(now, soon)
    when = format_when(timer.end_at, now)
    if state == STATE_DUE:
        return f"ГОТОВО от {when}"
    if state == STATE_MISSED:
        return f"ПРОПУСНАТО от {when}"
    if state == "soon":
        return f"скоро, {when}"
    return when


def quantity_text(value: float) -> str:
    """Цифри без разделители: „10000000“ четците казват „десет милиона“,
    а „10 000 000“ може да прочетат като отделни числа."""
    if not value:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def describe(timer: Timer, now: float) -> str:
    """Цяло изречение за полето „Подробности“ и за F3."""
    what = timer.display_name if timer.product.strip() else type_label(timer.type)
    place = ", ".join(p for p in (timer.line.strip(), timer.world.strip()) if p)
    parts = [f"{what}{' — ' + place if place else ''}."]
    kind = type_label(timer.type)
    parts.append(f"{kind}{', ' + timer.building if timer.building.strip() else ''}.")
    left = timer.end_at - now
    if left > 0:
        parts.append(f"Готово {format_when_spoken(timer.end_at, now)}, "
                     f"остават {format_remaining_words(left)}.")
    else:
        parts.append(f"Готово е от {format_remaining_words(-left)} "
                     f"({format_when_spoken(timer.end_at, now)}). Потвърди с Ctrl+D.")
    if timer.repeat_enabled:
        total = f" от {timer.cycles_planned}" if timer.cycles_planned else ""
        parts.append(f"Цикъл {timer.cycle_no}{total}.")
    if timer.quality.strip():
        parts.append(f"Качество {timer.quality}.")
    if timer.note.strip():
        parts.append(f"Бележка: {timer.note}.")
    return " ".join(parts)


class TimersPanel(wx.Panel):
    def __init__(self, parent, frame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.db = frame.db
        self.settings = frame.settings
        self._timers: dict[int, Timer] = {}
        self._countdown = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(wx.StaticText(self, label="Свят:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.world_filter = wx.Choice(self, choices=[ALL_WORLDS])
        self.world_filter.SetName("Свят")
        self.world_filter.SetSelection(0)
        filters.Add(self.world_filter, 1, wx.RIGHT, 16)
        filters.Add(wx.StaticText(self, label="Показвай:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.show_filter = wx.Choice(self, choices=["Всички", "Само готовите",
                                                    "Следващите 24 часа"])
        self.show_filter.SetName("Показвай")
        self.show_filter.SetSelection(0)
        filters.Add(self.show_filter, 1)
        sizer.Add(filters, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Таймери:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.list = RowList(self, self._columns(), name="Таймери")
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Подробности:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.details = read_only_text(self, lines=3)
        self.details.SetName("Подробности")
        sizer.Add(self.details, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.buttons: list[wx.Button] = []
        for label, handler in (
            ("&Нов таймер", self.new_timer),
            ("&Редактирай", self.edit_selected),
            ("&Готово", self.complete_selected),
            ("Нов &цикъл", self.restart_selected),
            ("&Спри", self.cancel_selected),
            ("Изтрий", self.delete_selected),
            ("Потвърди всички готови", self.complete_all_due),
        ):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            buttons.Add(button, 0, wx.ALL, 4)
            self.buttons.append(button)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)

        self.world_filter.Bind(wx.EVT_CHOICE, lambda _e: self.refresh(resort=True))
        self.show_filter.Bind(wx.EVT_CHOICE, lambda _e: self.refresh(resort=True))
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.edit_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _e: self.update_details())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)

    # ---------------------------------------------------------- колони

    def _columns(self) -> list:
        return COLUMNS + ([COUNTDOWN_COLUMN] if self._countdown else [])

    def set_countdown(self, enabled: bool) -> None:
        """Колона „Остава“ с тиктакащи секунди — само без екранен четец."""
        if enabled == self._countdown:
            return
        self._countdown = enabled
        if enabled:
            title, width, align = COUNTDOWN_COLUMN
            self.list.add_column(len(COLUMNS), title, width, align)
        else:
            self.list.remove_column(len(COLUMNS))
        self.list._ids = []  # следващото обновяване преначертава
        self.refresh(resort=True)

    # ------------------------------------------------------------ данни

    def _soon(self) -> int:
        return int(self.settings.get("prewarn_minutes", 0) or 0) * 60

    def set_worlds(self, worlds: list[str]) -> None:
        current = self.world_filter.GetStringSelection()
        items = [ALL_WORLDS] + worlds
        if self.world_filter.GetItems() != items:
            self.world_filter.Set(items)
            self.world_filter.SetStringSelection(current if current in items else ALL_WORLDS)

    def _visible(self, timers: list[Timer], now: float) -> list[Timer]:
        world = self.world_filter.GetStringSelection()
        show = self.show_filter.GetSelection()
        result = []
        for timer in timers:
            if world and world != ALL_WORLDS and timer.world != world:
                continue
            if show == SHOW_DUE and not timer.is_due(now):
                continue
            if show == SHOW_24H and timer.end_at > now + DAY:
                continue
            result.append(timer)
        return result

    def refresh(self, resort: bool = False) -> None:
        now = time_now()
        timers = self.db.list_timers(TimerStatus.RUNNING.value)
        self._timers = {t.id: t for t in timers if t.id is not None}
        visible = self._visible(timers, now)
        visible_ids = {t.id for t in visible}

        order = self.list.ids()
        if resort or set(order) != visible_ids:
            ordered = sorted(visible, key=lambda t: t.end_at)
        else:
            ordered = [self._timers[i] for i in order]  # без пренареждане

        soon = self._soon()
        rows = []
        for timer in ordered:
            texts = [
                when_text(timer, now, soon),
                timer.product or type_label(timer.type),
                quantity_text(timer.quantity),
                timer.line or "—",
                timer.world or "—",
                type_label(timer.type),
                timer.building or "—",
            ]
            if self._countdown:
                left = timer.end_at - now
                texts.append(format_duration(left) if left >= 0 else "0")
            rows.append((timer.id, texts, timer.state(now, soon)))
        self.list.set_rows(rows)
        self.update_details(now)

    def update_details(self, now: float | None = None) -> None:
        timer = self.selected()
        text = describe(timer, time_now() if now is None else now) if timer else \
            "Няма избран таймер."
        if self.details.GetValue() != text and not self.details.HasFocus():
            self.details.SetValue(text)

    def selected(self) -> Timer | None:
        row_id = self.list.selected_id()
        return self._timers.get(row_id) if row_id is not None else None

    def due_count(self) -> int:
        now = time_now()
        return sum(1 for t in self._timers.values() if t.is_due(now))

    # ------------------------------------------------------------ клавиши

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE and not event.HasAnyModifiers():
            self.delete_selected()
            return
        event.Skip()

    def speak_details(self) -> None:
        timer = self.selected()
        text = describe(timer, time_now()) if timer else "Няма избран таймер."
        if self.details.GetValue() != text:
            self.details.SetValue(text)
        self.frame.announce(text, interrupt=True)

    # ------------------------------------------------------------ действия

    def _require(self) -> Timer | None:
        timer = self.selected()
        if timer is None:
            self.frame.announce("Първо избери таймер от списъка.", interrupt=True)
            self.list.SetFocus()
        return timer

    def new_timer(self, world: str = "", company: str = "") -> None:
        dialog = TimerDialog(self.frame, self.db, self.settings, world=world, company=company)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.result is not None:
                timer = dialog.result
                self.db.add_timer(timer)
                self.db.remember_product(timer)
                self.settings.save()
                self.frame.refresh_all()
                self.list.focus_id(timer.id)
                self.list.SetFocus()
                self.frame.announce(f"Добавен: {planner.describe_spoken(timer)}, готово "
                                    f"{format_when_spoken(timer.end_at, time_now())}.")
        finally:
            dialog.Destroy()

    def edit_selected(self) -> None:
        timer = self._require()
        if timer is None:
            return
        dialog = TimerDialog(self.frame, self.db, self.settings, timer)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.result is not None:
                self.db.update_timer(dialog.result)
                self.db.remember_product(dialog.result)
                self.frame.refresh_all(resort=True)
                self.list.focus_id(timer.id)
                self.frame.announce("Записано.")
        finally:
            dialog.Destroy()
        self.list.SetFocus()

    def complete_selected(self) -> None:
        timer = self._require()
        if timer is None:
            return
        message = self._complete(timer, time_now())
        self.frame.refresh_all()
        self.frame.announce(message, interrupt=True)

    def complete_all_due(self) -> None:
        now = time_now()
        due = [t for t in self._timers.values() if t.is_due(now)]
        if not due:
            self.frame.announce("Няма готови таймери.", interrupt=True)
            return
        for timer in due:
            self._complete(timer, now)
        self.frame.refresh_all()
        self.frame.announce(f"Потвърдени {len(due)} готови.", interrupt=True)

    def _complete(self, timer: Timer, now: float) -> str:
        product = self.db.get_product(timer.product, timer.quality) if timer.product else None
        profit = 0.0
        if product is not None and (product.unit_price or product.unit_cost):
            profit = planner.profit(timer.quantity, product.unit_cost, product.unit_price).total
        self.db.complete_timer(timer.id, now, profit)
        message = f"Готово: {planner.describe_spoken(timer)}."
        nxt = self.db.start_next_cycle(timer, now)
        if nxt is not None:
            message += (f" Пуснат е цикъл {nxt.cycle_no}, готов "
                        f"{format_when_spoken(nxt.end_at, now)}.")
        return message

    def restart_selected(self) -> None:
        timer = self._require()
        if timer is None:
            return
        if timer.duration_sec <= 0:
            self.frame.announce("Таймерът няма времетраене — отвори го с Enter и задай времето.",
                                interrupt=True)
            return
        now = time_now()
        clone = Timer(
            product=timer.product, quality=timer.quality, type=timer.type,
            quantity=timer.quantity, line=timer.line, world=timer.world,
            building=timer.building, start_at=now, end_at=now + timer.duration_sec,
            duration_sec=timer.duration_sec, repeat_enabled=timer.repeat_enabled,
            cycles_planned=timer.cycles_planned, cycle_no=timer.cycle_no + 1,
            prewarn_sec=timer.prewarn_sec, note=timer.note, created_at=now)
        self.db.add_timer(clone)
        self.frame.refresh_all()
        self.frame.announce(f"Нов цикъл, готов {format_when_spoken(clone.end_at, now)}.",
                            interrupt=True)

    def cancel_selected(self) -> None:
        timer = self._require()
        if timer is None:
            return
        self.db.set_timer_fields(timer.id, status=TimerStatus.CANCELLED.value)
        self.frame.refresh_all()
        self.frame.announce(f"Спрян: {planner.describe_spoken(timer)}.", interrupt=True)

    def delete_selected(self) -> None:
        timer = self._require()
        if timer is None:
            return
        if not confirm(self.frame, f"Да изтрия ли „{planner.describe_spoken(timer)}“?\n"
                                   "Действието не може да се върне.", "Изтриване"):
            self.list.SetFocus()
            return
        self.db.delete_timer(timer.id)
        self.frame.refresh_all()
        self.list.SetFocus()
        self.frame.announce("Изтрито.", interrupt=True)
