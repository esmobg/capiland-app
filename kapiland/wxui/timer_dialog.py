"""Диалог за нов или редактиран таймер."""

from __future__ import annotations

import wx

from .. import catalog, planner
from ..models import TYPE_LABELS, TYPE_ORDER, Timer, TimerStatus, type_label
from ..timeutil import (
    format_duration,
    format_duration_words,
    format_dt,
    format_when_spoken,
    now as time_now,
    parse_datetime,
    parse_duration,
)
from .common import Form, read_only_text, show_error

MODE_END = 0        # „Готово на“ — така се водят бележките
MODE_DURATION = 1   # начало и времетраене
MODE_REMAINING = 2  # оставащо време от играта
MODE_LABELS = ["Готово на", "Начало и времетраене", "Оставащо време"]


class TimerDialog(wx.Dialog):
    def __init__(self, parent, db, settings, timer: Timer | None = None,
                 world: str = "", company: str = "") -> None:
        super().__init__(parent, title="Редактиране на таймер" if timer else "Нов таймер",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.db = db
        self.settings = settings
        self.original = timer
        self.result: Timer | None = None

        panel = self
        outer = wx.BoxSizer(wx.VERTICAL)
        form = Form(panel)

        worlds = list(dict.fromkeys(list(catalog.KNOWN_WORLDS) + db.list_worlds()))
        self.world = form.add("Свят:", wx.ComboBox, choices=worlds)
        self.company = form.add("Компания:", wx.ComboBox, choices=[])
        self.kind = form.add("Дейност:", wx.Choice, choices=[TYPE_LABELS[t] for t in TYPE_ORDER])
        self.building = form.add("Сграда:", wx.ComboBox, choices=catalog.building_names())
        products = list(dict.fromkeys(catalog.known_product_names() + [p.name for p in db.list_products()]))
        self.product = form.add("Продукт:", wx.ComboBox, choices=sorted(products, key=str.lower))
        qualities = sorted({p.quality for p in db.list_products() if p.quality.strip()})
        self.quality = form.add("Качество:", wx.ComboBox, choices=qualities)
        self.quantity = form.add("Количество:", wx.TextCtrl)
        outer.Add(form.sizer, 0, wx.EXPAND | wx.ALL, 12)

        self.mode = wx.RadioBox(panel, label="Как задаваш времето", choices=MODE_LABELS,
                                majorDimension=1, style=wx.RA_SPECIFY_COLS)
        outer.Add(self.mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        times = Form(panel)
        self.label_end = None
        self.end = self._time_field(times, "Готово на:", "напр. 17 септември 17 ч")
        self.start = self._time_field(times, "Начало:", "сега")
        self.duration = self._time_field(times, "Времетраене:", "напр. 3ч 45м")
        self.remaining = self._time_field(times, "Оставащо време:", "напр. 03:42:10")
        outer.Add(times.sizer, 0, wx.EXPAND | wx.ALL, 12)

        outer.Add(wx.StaticText(panel, label="Изчислено:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.preview = read_only_text(panel, lines=3)
        self.preview.SetName("Изчислено")
        outer.Add(self.preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        extra = Form(panel)
        self.repeat = wx.CheckBox(panel, label="Пускай нов цикъл след потвърждаване")
        extra.add_full(self.repeat)
        self.cycles = extra.add("Брой цикли (0 = без край):", wx.SpinCtrl, min=0, max=999)
        self.prewarn = extra.add("Предупреди ме толкова минути по-рано:", wx.SpinCtrl,
                                 min=0, max=1440)
        self.note = extra.add("Бележка:", wx.TextCtrl)
        outer.Add(extra.sizer, 0, wx.EXPAND | wx.ALL, 12)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(panel, wx.ID_OK, "Запиши")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(panel, wx.ID_CANCEL, "Отказ"))
        buttons.Realize()
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize(self.FromDIP(wx.Size(520, -1)))

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.mode.Bind(wx.EVT_RADIOBOX, lambda _e: self._on_mode())
        self.world.Bind(wx.EVT_COMBOBOX, lambda _e: self._fill_companies())
        self.world.Bind(wx.EVT_TEXT, lambda _e: self._fill_companies())
        self.product.Bind(wx.EVT_COMBOBOX, lambda _e: self._on_product())
        self.repeat.Bind(wx.EVT_CHECKBOX, lambda _e: self._on_repeat())
        for control in (self.end, self.start, self.duration, self.remaining,
                        self.quantity, self.product, self.quality):
            control.Bind(wx.EVT_TEXT, lambda _e: self._update_preview())

        self._load(timer, world, company)
        self._on_mode()
        self._on_repeat()
        self.CentreOnParent()
        wx.CallAfter(self.world.SetFocus)

    # ---------------------------------------------------------- градеж

    def _time_field(self, form: Form, label: str, hint: str) -> wx.TextCtrl:
        control = form.add(label, wx.TextCtrl)
        control.SetHint(hint)
        return control

    def _fill_companies(self) -> None:
        current = self.company.GetValue()
        names = [a.name for a in self.db.list_accounts(self.world.GetValue().strip())]
        self.company.Set(names)
        self.company.SetValue(current)

    # ------------------------------------------------------------ данни

    def _load(self, timer: Timer | None, world: str, company: str) -> None:
        default_world = world or str(self.settings.get("default_world", "") or "")
        last_type = str(self.settings.get("last_type", "production"))
        self.world.SetValue(timer.world if timer else default_world)
        self._fill_companies()
        self.company.SetValue(timer.line if timer else company)
        kind = timer.type if timer else last_type
        self.kind.SetSelection(TYPE_ORDER.index(kind) if kind in TYPE_ORDER else 0)
        if timer is None:
            self.mode.SetSelection(MODE_END)
            self.start.SetValue("сега")
            return
        self.building.SetValue(timer.building)
        self.product.SetValue(timer.product)
        self.quality.SetValue(timer.quality)
        if timer.quantity:
            self.quantity.SetValue(str(int(timer.quantity)) if float(timer.quantity).is_integer()
                                   else str(timer.quantity))
        self.mode.SetSelection(MODE_END)
        self.end.SetValue(format_dt(timer.end_at, "%d.%m.%Y %H:%M"))
        self.start.SetValue(format_dt(timer.start_at, "%d.%m.%Y %H:%M"))
        self.duration.SetValue(format_duration(timer.duration_sec))
        self.remaining.SetValue(format_duration(max(0, timer.end_at - time_now())))
        self.repeat.SetValue(bool(timer.repeat_enabled))
        self.cycles.SetValue(timer.cycles_planned)
        self.prewarn.SetValue(int(timer.prewarn_sec // 60))
        self.note.SetValue(timer.note)

    def _on_product(self) -> None:
        """Предлага запомнените стойности за продукта и сградата от каталога."""
        name = self.product.GetValue().strip()
        product = self.db.get_product(name, self.quality.GetValue().strip()) if name else None
        if product is not None:
            if product.default_duration_sec and not self.duration.GetValue().strip():
                self.duration.SetValue(format_duration(product.default_duration_sec))
            if product.default_quantity and not self.quantity.GetValue().strip():
                qty = product.default_quantity
                self.quantity.SetValue(str(int(qty)) if float(qty).is_integer() else str(qty))
            if product.building and not self.building.GetValue().strip():
                self.building.SetValue(product.building)
        self._update_preview()

    def _on_mode(self) -> None:
        mode = self.mode.GetSelection()
        visible = {
            MODE_END: (self.end,),
            MODE_DURATION: (self.start, self.duration),
            MODE_REMAINING: (self.remaining,),
        }[mode]
        for control in (self.end, self.start, self.duration, self.remaining):
            show = control in visible
            control.Show(show)
            label = control.GetPrevSibling()
            if isinstance(label, wx.StaticText):
                label.Show(show)
        self.Layout()
        self.Fit()
        self._update_preview()

    def _on_repeat(self) -> None:
        self.cycles.Enable(self.repeat.GetValue())

    # ---------------------------------------------------------- сметка

    def _compute(self) -> tuple[float, float, int]:
        now = time_now()
        mode = self.mode.GetSelection()
        if mode == MODE_END:
            end = parse_datetime(self.end.GetValue(), now)
            start = now if end > now else end
            return start, end, max(0, int(round(end - start)))
        if mode == MODE_DURATION:
            start = parse_datetime(self.start.GetValue() or "сега", now)
            duration = parse_duration(self.duration.GetValue())
            return start, planner.end_from_start_duration(start, duration), duration
        remaining = parse_duration(self.remaining.GetValue())
        return now, planner.end_from_remaining(remaining, now), remaining

    def _field_for_mode(self) -> wx.TextCtrl:
        return {MODE_END: self.end, MODE_DURATION: self.duration,
                MODE_REMAINING: self.remaining}[self.mode.GetSelection()]

    def _update_preview(self) -> None:
        try:
            _start, end, _duration = self._compute()
        except ValueError as exc:
            self.preview.SetValue(f"Още не мога да сметна: {exc}")
            return
        now = time_now()
        left = end - now
        lines = [f"Готово {format_when_spoken(end, now)} "
                 f"({format_dt(end, '%d.%m.%Y %H:%M')})."]
        if left >= 0:
            lines.append(f"Остават {format_duration_words(left)}.")
        else:
            lines.append(f"Вече е минало преди {format_duration_words(-left)}.")
        quantity = _as_float(self.quantity.GetValue())
        product = self.db.get_product(self.product.GetValue().strip(),
                                      self.quality.GetValue().strip())
        if product and quantity and (product.unit_price or product.unit_cost) and left > 0:
            money = planner.profit(quantity, product.unit_cost, product.unit_price, left)
            lines.append(f"Печалба {planner.format_money(money.total)}.")
        self.preview.SetValue(" ".join(lines))

    # ---------------------------------------------------------- запис

    def _on_ok(self, _event) -> None:
        try:
            start, end, duration = self._compute()
        except ValueError as exc:
            show_error(self, f"Не мога да разбера времето: {exc}", self._field_for_mode())
            return
        quantity_text = self.quantity.GetValue().strip()
        if quantity_text and _as_float(quantity_text) is None:
            show_error(self, "Количеството трябва да е число.", self.quantity)
            return

        timer = self.original or Timer()
        timer.world = self.world.GetValue().strip()
        timer.line = self.company.GetValue().strip()
        timer.type = TYPE_ORDER[max(0, self.kind.GetSelection())]
        timer.building = self.building.GetValue().strip()
        timer.product = self.product.GetValue().strip()
        timer.quality = self.quality.GetValue().strip()
        timer.quantity = _as_float(quantity_text) or 0.0
        timer.start_at, timer.end_at, timer.duration_sec = start, end, duration
        timer.repeat_enabled = 1 if self.repeat.GetValue() else 0
        timer.cycles_planned = self.cycles.GetValue()
        timer.prewarn_sec = self.prewarn.GetValue() * 60
        timer.note = self.note.GetValue().strip()
        if self.original is None:
            timer.status = TimerStatus.RUNNING.value
            timer.cycle_no = 1
            timer.created_at = time_now()
        else:
            timer.notified_at = timer.prewarned_at = timer.reminded_at = None
            timer.missed = 0
        self.settings.set("last_type", timer.type)
        self.result = timer
        self.EndModal(wx.ID_OK)


def _as_float(text: str) -> float | None:
    text = (text or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None
