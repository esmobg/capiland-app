"""Диалог за нов или редактиран таймер."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import planner
from ..models import TYPE_LABELS, Timer, TimerStatus, label_to_type, type_label
from ..timeutil import (
    format_duration,
    format_dt,
    format_dt_relative,
    now as time_now,
    parse_datetime,
    parse_duration,
)

MODE_START_DURATION = "start"
MODE_END = "end"
MODE_REMAINING = "remaining"


class TimerDialog(tk.Toplevel):
    """Модален диалог. След затваряне ``result`` е обект Timer или None."""

    def __init__(self, master, app_style, db, settings,
                 timer: Timer | None = None) -> None:
        super().__init__(master)
        self.app_style = app_style
        self.db = db
        self.settings = settings
        self.original = timer
        self.result: Timer | None = None

        self.title("Редактиране на таймер" if timer else "Нов таймер")
        self.transient(master)
        self.resizable(True, True)
        self.configure(background=app_style.colors["bg"])
        self.columnconfigure(0, weight=1)

        self._build()
        self._load(timer)
        self._update_preview()

        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", self._on_return)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        self._center_on(master)
        self.grab_set()
        self.product_box.focus_set()

    # ------------------------------------------------------------- градеж

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 5}
        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        row = 0

        # --- какво ---
        ttk.Label(body, text="Какво пускаш", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        self.type_var = tk.StringVar(value=type_label(
            str(self.settings.get("last_type", "production"))))
        ttk.Label(body, text="Тип:").grid(row=row, column=0, sticky="w", **pad)
        self.type_box = ttk.Combobox(
            body, textvariable=self.type_var, state="readonly",
            values=list(TYPE_LABELS.values()))
        self.type_box.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.product_var = tk.StringVar()
        ttk.Label(body, text="Продукт / название:").grid(
            row=row, column=0, sticky="w", **pad)
        self.product_box = ttk.Combobox(body, textvariable=self.product_var,
                                        values=self._product_names())
        self.product_box.grid(row=row, column=1, sticky="ew", **pad)
        self.product_box.bind("<<ComboboxSelected>>", self._on_product_selected)
        row += 1

        self.quality_var = tk.StringVar()
        ttk.Label(body, text="Качество:").grid(row=row, column=0, sticky="w", **pad)
        self.quality_box = ttk.Combobox(body, textvariable=self.quality_var,
                                        values=self._known_qualities())
        self.quality_box.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.quantity_var = tk.StringVar(value="")
        ttk.Label(body, text="Количество:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(body, textvariable=self.quantity_var).grid(
            row=row, column=1, sticky="ew", **pad)
        row += 1

        self.line_var = tk.StringVar()
        ttk.Label(body, text="Линия / фабрика:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Combobox(body, textvariable=self.line_var,
                     values=self._line_names()).grid(
            row=row, column=1, sticky="ew", **pad)
        row += 1

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        # --- кога ---
        ttk.Label(body, text="Кога свършва", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        self.mode_var = tk.StringVar(value=MODE_START_DURATION)
        modes = ttk.Frame(body)
        modes.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10)
        for value, text in (
            (MODE_START_DURATION, "Начало и времетраене"),
            (MODE_END, "Точен краен час"),
            (MODE_REMAINING, "Оставащо време"),
        ):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.mode_var,
                            command=self._on_mode_change).pack(side="left", padx=(0, 14))
        row += 1

        self.start_var = tk.StringVar(value="сега")
        self.lbl_start = ttk.Label(body, text="Начало:")
        self.lbl_start.grid(row=row, column=0, sticky="w", **pad)
        self.ent_start = ttk.Entry(body, textvariable=self.start_var)
        self.ent_start.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.duration_var = tk.StringVar(value="")
        self.lbl_duration = ttk.Label(body, text="Времетраене:")
        self.lbl_duration.grid(row=row, column=0, sticky="w", **pad)
        self.ent_duration = ttk.Entry(body, textvariable=self.duration_var)
        self.ent_duration.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.end_var = tk.StringVar(value="")
        self.lbl_end = ttk.Label(body, text="Краен час:")
        self.lbl_end.grid(row=row, column=0, sticky="w", **pad)
        self.ent_end = ttk.Entry(body, textvariable=self.end_var)
        self.ent_end.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.remaining_var = tk.StringVar(value="")
        self.lbl_remaining = ttk.Label(body, text="Оставащо време:")
        self.lbl_remaining.grid(row=row, column=0, sticky="w", **pad)
        self.ent_remaining = ttk.Entry(body, textvariable=self.remaining_var)
        self.ent_remaining.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        ttk.Label(
            body,
            text="Приема се 3д 4ч 20м, 3d 4h 20m, 03:42:10, 1.5h, 90m "
                 "или само число (минути).",
            style="Muted.TLabel", wraplength=440, justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=10)
        row += 1

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        # --- повторение и известяване ---
        self.repeat_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Пускай автоматично нов цикъл след потвърждаване",
                        variable=self.repeat_var,
                        command=self._on_repeat_change).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=10, pady=4)
        row += 1

        self.cycles_var = tk.StringVar(value="0")
        self.lbl_cycles = ttk.Label(body, text="Брой цикли (0 = без край):")
        self.lbl_cycles.grid(row=row, column=0, sticky="w", **pad)
        self.spn_cycles = ttk.Spinbox(body, from_=0, to=999, textvariable=self.cycles_var)
        self.spn_cycles.grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.prewarn_var = tk.StringVar(value="0")
        ttk.Label(body, text="Предупреди ме N минути по-рано\n(0 = както е в настройките):",
                  justify="left").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(body, from_=0, to=1440, textvariable=self.prewarn_var).grid(
            row=row, column=1, sticky="ew", **pad)
        row += 1

        self.note_var = tk.StringVar(value="")
        ttk.Label(body, text="Бележка:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(body, textvariable=self.note_var).grid(
            row=row, column=1, sticky="ew", **pad)
        row += 1

        # --- преглед на сметката ---
        preview = ttk.Frame(body, style="Surface.TFrame", padding=10)
        preview.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        preview.columnconfigure(0, weight=1)
        self.preview_var = tk.StringVar(value="")
        self.preview_label = ttk.Label(
            preview, textvariable=self.preview_var, style="Surface.TLabel",
            justify="left", wraplength=460)
        self.preview_label.grid(row=0, column=0, sticky="w")
        row += 1

        # --- бутони ---
        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", padx=10, pady=(10, 0))
        ttk.Button(buttons, text="Отказ", command=self._cancel).pack(
            side="right", padx=(8, 0))
        ttk.Button(buttons, text="Запиши", style="Accent.TButton",
                   command=self._save).pack(side="right")

        # Преизчисляване при всяка промяна.
        for var in (self.start_var, self.duration_var, self.end_var,
                    self.remaining_var, self.quantity_var, self.product_var,
                    self.quality_var, self.type_var, self.line_var):
            var.trace_add("write", lambda *_a: self._update_preview())
        self._on_mode_change()
        self._on_repeat_change()

    # -------------------------------------------------------------- данни

    def _product_names(self) -> list[str]:
        try:
            return [p.name for p in self.db.list_products()]
        except Exception:
            return []

    def _known_qualities(self) -> list[str]:
        """Качествата, които вече си ползвал — за бърз избор."""
        seen: list[str] = []
        try:
            for product in self.db.list_products():
                if product.quality.strip() and product.quality not in seen:
                    seen.append(product.quality)
        except Exception:
            pass
        return seen

    def _line_names(self) -> list[str]:
        count = int(self.settings.get("default_lines", 4) or 4)
        names = [f"Линия {i}" for i in range(1, count + 1)]
        try:
            for timer in self.db.list_timers(None):
                if timer.line.strip() and timer.line not in names:
                    names.append(timer.line)
        except Exception:
            pass
        return names

    def _load(self, timer: Timer | None) -> None:
        if timer is None:
            return
        self.type_var.set(type_label(timer.type))
        self.product_var.set(timer.product)
        self.quality_var.set(timer.quality)
        qty = timer.quantity
        self.quantity_var.set(
            "" if not qty else (str(int(qty)) if float(qty).is_integer() else str(qty)))
        self.line_var.set(timer.line)
        self.start_var.set(format_dt(timer.start_at, "%d.%m.%Y %H:%M:%S"))
        self.duration_var.set(format_duration(timer.duration_sec))
        self.end_var.set(format_dt(timer.end_at, "%d.%m.%Y %H:%M:%S"))
        self.remaining_var.set(format_duration(max(0, timer.end_at - time_now())))
        self.repeat_var.set(bool(timer.repeat_enabled))
        self.cycles_var.set(str(timer.cycles_planned))
        self.prewarn_var.set(str(int(timer.prewarn_sec // 60)))
        self.note_var.set(timer.note)
        self._on_repeat_change()

    def _on_product_selected(self, _event=None) -> None:
        """Предлага запомненото времетраене и количество за продукта."""
        name = self.product_var.get().strip()
        if not name:
            return
        product = self.db.get_product(name, self.quality_var.get().strip())
        if product is None:
            return
        if product.default_duration_sec and not self.duration_var.get().strip():
            self.duration_var.set(format_duration(product.default_duration_sec))
        if product.default_quantity and not self.quantity_var.get().strip():
            qty = product.default_quantity
            self.quantity_var.set(
                str(int(qty)) if float(qty).is_integer() else str(qty))
        if product.default_type:
            self.type_var.set(type_label(product.default_type))

    # ------------------------------------------------------------ режими

    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        widgets = {
            MODE_START_DURATION: (self.lbl_start, self.ent_start,
                                  self.lbl_duration, self.ent_duration),
            MODE_END: (self.lbl_start, self.ent_start, self.lbl_end, self.ent_end),
            MODE_REMAINING: (self.lbl_remaining, self.ent_remaining),
        }
        active = widgets[mode]
        all_widgets = (self.lbl_start, self.ent_start, self.lbl_duration,
                       self.ent_duration, self.lbl_end, self.ent_end,
                       self.lbl_remaining, self.ent_remaining)
        for widget in all_widgets:
            if widget in active:
                widget.grid()
                if isinstance(widget, ttk.Entry):
                    widget.state(["!disabled"])
            else:
                widget.grid_remove()
        self._update_preview()

    def _on_repeat_change(self) -> None:
        enabled = self.repeat_var.get()
        state = "normal" if enabled else "disabled"
        self.spn_cycles.configure(state=state)
        self.lbl_cycles.configure(
            style="TLabel" if enabled else "Muted.TLabel")

    # ------------------------------------------------- сметка и проверка

    def _compute(self) -> tuple[float, float, int]:
        """Връща (начало, край, времетраене) или хвърля ValueError."""
        mode = self.mode_var.get()
        now = time_now()
        if mode == MODE_START_DURATION:
            start = parse_datetime(self.start_var.get(), now)
            duration = parse_duration(self.duration_var.get())
            end = planner.end_from_start_duration(start, duration)
        elif mode == MODE_END:
            start = parse_datetime(self.start_var.get(), now)
            end = parse_datetime(self.end_var.get(), now)
            duration = planner.duration_from_start_end(start, end)
        else:
            remaining = parse_duration(self.remaining_var.get())
            start = now
            end = planner.end_from_remaining(remaining, now)
            duration = int(remaining)
        return start, end, int(duration)

    def _update_preview(self) -> None:
        try:
            start, end, duration = self._compute()
        except ValueError as exc:
            self.preview_var.set(f"⚠ Проверка: {exc}")
            return

        now = time_now()
        left = end - now
        lines = [
            f"Край: {format_dt_relative(end, now)}  ({format_dt(end, '%d.%m.%Y %H:%M:%S')})",
            f"Времетраене: {format_duration(duration)}   ·   "
            f"{'Остават' if left >= 0 else 'Просрочено с'} {format_duration(abs(left))}",
        ]

        quantity = _as_float(self.quantity_var.get())
        if quantity and duration:
            rate = planner.throughput(quantity, duration)
            lines.append(
                f"Производителност: {rate.per_hour:,.1f} бр./час  ·  "
                f"{rate.per_day:,.0f} бр./ден".replace(",", " "))
            product = self.db.get_product(self.product_var.get().strip(),
                                          self.quality_var.get().strip())
            if product and (product.unit_price or product.unit_cost):
                money = planner.profit(quantity, product.unit_cost,
                                       product.unit_price, duration)
                lines.append(
                    f"Печалба: {planner.format_money(money.total)}  ·  "
                    f"{planner.format_money(money.per_hour)} на час")
        self.preview_var.set("\n".join(lines))

    # ----------------------------------------------------------- запазване

    def _on_return(self, event) -> None:
        if isinstance(event.widget, (ttk.Button, tk.Button)):
            return
        self._save()

    def _save(self) -> None:
        try:
            start, end, duration = self._compute()
        except ValueError as exc:
            self.preview_var.set(f"⚠ Не мога да запиша: {exc}")
            self.bell()
            return

        timer = self.original or Timer()
        timer.product = self.product_var.get().strip()
        timer.quality = self.quality_var.get().strip()
        timer.type = label_to_type(self.type_var.get())
        timer.quantity = _as_float(self.quantity_var.get())
        timer.line = self.line_var.get().strip()
        timer.start_at = start
        timer.end_at = end
        timer.duration_sec = duration
        timer.repeat_enabled = 1 if self.repeat_var.get() else 0
        timer.cycles_planned = int(_as_float(self.cycles_var.get()))
        timer.prewarn_sec = int(_as_float(self.prewarn_var.get()) * 60)
        timer.note = self.note_var.get().strip()
        if self.original is None:
            timer.status = TimerStatus.RUNNING.value
            timer.cycle_no = 1
            timer.created_at = time_now()
        else:
            # При промяна на времето известието трябва да се задейства пак.
            timer.notified_at = None
            timer.prewarned_at = None
            timer.reminded_at = None
            timer.missed = 0

        self.settings.set("last_type", timer.type)
        self.result = timer
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

    def _center_on(self, master) -> None:
        try:
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass


def _as_float(text: str) -> float:
    try:
        return float(str(text).strip().replace(",", ".") or 0)
    except ValueError:
        return 0.0
