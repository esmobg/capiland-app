"""Главният екран: таблица с активните таймери и обратно броене."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import a11y, planner
from ..models import Timer, TimerStatus, type_label
from ..timeutil import (
    format_duration,
    format_duration_words,
    format_dt,
    format_dt_relative,
    now as time_now,
)
from .timer_dialog import TimerDialog

COLUMNS = (
    ("state", "Статус", 110, "w"),
    ("product", "Продукт", 175, "w"),
    ("quality", "Качество", 85, "w"),
    ("type", "Тип", 105, "w"),
    ("quantity", "Кол.", 70, "e"),
    ("line", "Линия", 100, "w"),
    ("start", "Старт", 130, "w"),
    ("end", "Край", 150, "w"),
    ("left", "Остава", 110, "e"),
    ("percent", "Готово", 75, "e"),
    ("cycle", "Цикъл", 70, "center"),
)


class TimersView(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.db = app.db
        self.settings = app.settings
        self._known_ids: list[int] = []
        self._timers: dict[int, Timer] = {}
        self._build()

    # ------------------------------------------------------------- градеж

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.btn_new = ttk.Button(bar, text="Нов таймер (Ctrl+N)",
                                  style="Accent.TButton", command=self.new_timer)
        self.btn_new.pack(side="left")
        for text, command in (
            ("Редактирай", self.edit_timer),
            ("Готово ✔", self.complete_selected),
            ("Нов цикъл", self.restart_selected),
            ("Спри", self.cancel_selected),
            ("Изтрий", self.delete_selected),
        ):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Потвърди всички готови",
                   command=self.complete_all_due).pack(side="right")

        # --- таблица ---
        table = ttk.Frame(self)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table, columns=[c[0] for c in COLUMNS], show="headings",
            selectmode="browse", takefocus=True)
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title,
                              command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "product"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.app.style.tag_tree(self.tree)

        self.tree.bind("<Double-1>", lambda _e: self.edit_timer())
        self.tree.bind("<Return>", lambda _e: self.edit_timer())
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_details())

        # --- подробности за избрания (важно при екранна лупа/четец) ---
        details = ttk.Frame(self, style="Surface.TFrame", padding=10)
        details.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        details.columnconfigure(0, weight=1)
        self.details_var = tk.StringVar(value="Изберете таймер от таблицата.")
        ttk.Label(details, textvariable=self.details_var, style="Surface.TLabel",
                  justify="left", wraplength=900).grid(row=0, column=0, sticky="w")

        # --- обобщение ---
        summary = ttk.Frame(self, style="Surface.TFrame", padding=10)
        summary.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        summary.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="")
        ttk.Label(summary, textvariable=self.summary_var, style="Surface.TLabel",
                  justify="left", wraplength=900).grid(row=0, column=0, sticky="w")

        self._sort_key = "left"
        self._sort_reverse = False

    # -------------------------------------------------------------- данни

    def _soon_seconds(self) -> int:
        return int(self.settings.get("prewarn_minutes", 0) or 0) * 60

    def _line_names(self) -> list[str]:
        count = int(self.settings.get("default_lines", 4) or 4)
        names = [f"Линия {i}" for i in range(1, count + 1)]
        for timer in self._timers.values():
            if timer.line.strip() and timer.line not in names:
                names.append(timer.line)
        return names

    def selected_timer(self) -> Timer | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._timers.get(int(selection[0]))

    # ------------------------------------------------------------ рисуване

    def refresh(self, full: bool = True) -> None:
        now = time_now()
        timers = self.db.list_timers(TimerStatus.RUNNING.value)
        self._timers = {t.id: t for t in timers if t.id is not None}
        ids = [t.id for t in self._sorted(timers, now)]

        if full or ids != self._known_ids:
            selected = self.tree.selection()
            self.tree.delete(*self.tree.get_children())
            for timer_id in ids:
                self.tree.insert("", "end", iid=str(timer_id),
                                 values=self._row_values(self._timers[timer_id], now))
            self._known_ids = ids
            for item in selected:
                if item in self.tree.get_children():
                    self.tree.selection_set(item)
        else:
            for timer_id in ids:
                timer = self._timers[timer_id]
                values = self._row_values(timer, now)
                item = str(timer_id)
                for (key, _t, _w, _a), value in zip(COLUMNS, values):
                    if self.tree.set(item, key) != value:
                        self.tree.set(item, key, value)

        soon = self._soon_seconds()
        for timer_id in ids:
            state = self._timers[timer_id].state(now, soon)
            self.tree.item(str(timer_id), tags=(state,))

        self._update_details(now)
        self._update_summary(timers, now)

    def _sorted(self, timers: list[Timer], now: float) -> list[Timer]:
        key = self._sort_key
        getters = {
            "state": lambda t: (0 if t.is_due(now) else 1, t.end_at),
            "product": lambda t: (t.product.lower(), t.quality.lower()),
            "quality": lambda t: (t.quality.lower(), t.product.lower()),
            "type": lambda t: type_label(t.type),
            "quantity": lambda t: t.quantity,
            "line": lambda t: t.line.lower(),
            "start": lambda t: t.start_at,
            "end": lambda t: t.end_at,
            "left": lambda t: t.end_at,
            "percent": lambda t: t.progress(now),
            "cycle": lambda t: t.cycle_no,
        }
        return sorted(timers, key=getters.get(key, getters["left"]),
                      reverse=self._sort_reverse)

    def _sort_by(self, key: str) -> None:
        if self._sort_key == key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = key
            self._sort_reverse = False
        self.refresh(full=True)

    def _row_values(self, timer: Timer, now: float) -> tuple:
        state = timer.state(now, self._soon_seconds())
        left = timer.remaining(now)
        left_text = format_duration(left) if left >= 0 else "+" + format_duration(-left)
        quantity = timer.quantity
        qty_text = ("" if not quantity else
                    (str(int(quantity)) if float(quantity).is_integer() else f"{quantity:g}"))
        return (
            a11y.state_text(state),
            timer.product or "—",
            timer.quality or "—",
            type_label(timer.type),
            qty_text,
            timer.line or "—",
            format_dt(timer.start_at, "%d.%m %H:%M"),
            format_dt_relative(timer.end_at, now),
            left_text,
            f"{timer.progress(now) * 100:.0f}%",
            timer.cycle_text,
        )

    def _update_details(self, now: float | None = None) -> None:
        now = time_now() if now is None else now
        timer = self.selected_timer()
        if timer is None:
            self.details_var.set("Изберете таймер от таблицата, за да видите подробности.")
            return
        left = timer.remaining(now)
        state = timer.state(now, self._soon_seconds())
        parts = [
            f"{timer.display_name} — {type_label(timer.type)}"
            + (f", {timer.line}" if timer.line else ""),
            f"Статус: {a11y.state_text(state)}.",
        ]
        if left >= 0:
            parts.append(f"Остават {format_duration_words(left)} "
                         f"(готово в {format_dt(timer.end_at, '%d.%m.%Y %H:%M:%S')}).")
        else:
            parts.append(f"Готово от {format_duration_words(-left)} "
                         f"— потвърдете с бутона „Готово“.")
        if timer.quantity and timer.duration_sec:
            rate = planner.throughput(timer.quantity, timer.duration_sec)
            parts.append(f"Производителност: {rate.per_hour:,.1f} бр./час."
                         .replace(",", " "))
        if timer.repeat_enabled:
            parts.append(f"Цикъл {timer.cycle_text}.")
        if timer.note:
            parts.append(f"Бележка: {timer.note}")
        self.details_var.set("  ".join(parts))

    def _update_summary(self, timers: list[Timer], now: float) -> None:
        lines: list[str] = []
        due = planner.due_now(timers, now)
        if due:
            names = ", ".join(t.display_name for t in due[:3])
            more = f" и още {len(due) - 3}" if len(due) > 3 else ""
            lines.append(f"✔ ГОТОВИ ({len(due)}): {names}{more} — пусни следващите.")

        upcoming = planner.next_due(timers, now)
        if upcoming is not None:
            where = f" ({upcoming.line})" if upcoming.line else ""
            lines.append(
                f"▶ Следващ готов: {upcoming.display_name}{where} след "
                f"{format_duration(upcoming.remaining(now))}.")
        elif not due:
            lines.append("Няма активни таймери. Натиснете „Нов таймер“ (Ctrl+N).")

        lines_list = self._line_names()
        free = planner.free_lines(timers, lines_list, now)
        if free:
            lines.append(f"Свободни линии ({len(free)}): " + ", ".join(free) + ".")
        else:
            free_at = planner.next_line_free_at(timers, lines_list, now)
            if free_at is not None:
                lines.append("Всички линии са заети. Първата се освобождава след "
                             f"{format_duration(free_at - now)}.")

        window = int(self.settings.get("collision_window_minutes", 5) or 5) * 60
        groups = planner.find_collisions(timers, window, now)
        if groups:
            group = groups[0]
            lines.append(
                f"⚠ Струпване: {len(group)} партиди свършват в рамките на "
                f"{window // 60} мин. около "
                f"{format_dt(group[0].end_at, '%d.%m %H:%M')}.")
        self.summary_var.set("\n".join(lines))

    # ------------------------------------------------------------ действия

    def new_timer(self) -> None:
        dialog = TimerDialog(self.app.root, self.app.style, self.db, self.settings)
        self.app.root.wait_window(dialog)
        if dialog.result is not None:
            self.db.add_timer(dialog.result)
            self.db.remember_product(dialog.result)
            self.settings.save()
            self.refresh(full=True)
            self.app.set_status(f"Добавен таймер: {dialog.result.display_name}")

    def edit_timer(self) -> None:
        timer = self.selected_timer()
        if timer is None:
            self.app.set_status("Първо изберете таймер от таблицата.")
            return
        dialog = TimerDialog(self.app.root, self.app.style, self.db,
                             self.settings, timer)
        self.app.root.wait_window(dialog)
        if dialog.result is not None:
            self.db.update_timer(dialog.result)
            self.db.remember_product(dialog.result)
            self.refresh(full=True)
            self.app.set_status(f"Записан таймер: {dialog.result.display_name}")

    def complete_selected(self) -> None:
        timer = self.selected_timer()
        if timer is None:
            self.app.set_status("Първо изберете таймер от таблицата.")
            return
        self._complete(timer)
        self.refresh(full=True)

    def complete_all_due(self) -> None:
        now = time_now()
        due = planner.due_now(list(self._timers.values()), now)
        if not due:
            self.app.set_status("Няма готови таймери за потвърждаване.")
            return
        for timer in due:
            self._complete(timer, now)
        self.refresh(full=True)
        self.app.set_status(f"Потвърдени {len(due)} готови таймера.")

    def _complete(self, timer: Timer, now: float | None = None) -> None:
        now = time_now() if now is None else now
        product = (self.db.get_product(timer.product, timer.quality)
                   if timer.product else None)
        profit_value = 0.0
        if product is not None and (product.unit_price or product.unit_cost):
            profit_value = planner.profit(
                timer.quantity, product.unit_cost, product.unit_price).total
        self.db.complete_timer(timer.id, now, profit_value)
        message = f"Готово: {timer.display_name}."
        nxt = self.db.start_next_cycle(timer, now)
        if nxt is not None:
            message += (f" Пуснат е цикъл {nxt.cycle_text}, готов в "
                        f"{format_dt(nxt.end_at, '%d.%m %H:%M')}.")
        self.app.set_status(message)

    def restart_selected(self) -> None:
        """Пуска нов цикъл със същите параметри, независимо от повторението."""
        timer = self.selected_timer()
        if timer is None:
            self.app.set_status("Първо изберете таймер от таблицата.")
            return
        now = time_now()
        clone = Timer(
            product=timer.product, quality=timer.quality, type=timer.type,
            quantity=timer.quantity,
            line=timer.line, start_at=now, end_at=now + timer.duration_sec,
            duration_sec=timer.duration_sec, repeat_enabled=timer.repeat_enabled,
            cycles_planned=timer.cycles_planned, cycle_no=timer.cycle_no + 1,
            prewarn_sec=timer.prewarn_sec, note=timer.note, created_at=now,
        )
        self.db.add_timer(clone)
        self.refresh(full=True)
        self.app.set_status(
            f"Нов цикъл: {clone.display_name}, готов в "
            f"{format_dt(clone.end_at, '%d.%m %H:%M')}.")

    def cancel_selected(self) -> None:
        timer = self.selected_timer()
        if timer is None:
            self.app.set_status("Първо изберете таймер от таблицата.")
            return
        self.db.set_timer_fields(timer.id, status=TimerStatus.CANCELLED.value)
        self.refresh(full=True)
        self.app.set_status(f"Спрян таймер: {timer.display_name}.")

    def delete_selected(self) -> None:
        timer = self.selected_timer()
        if timer is None:
            self.app.set_status("Първо изберете таймер от таблицата.")
            return
        if not messagebox.askyesno(
            "Изтриване",
            f"Да изтрия ли „{timer.display_name}“?\n"
            "Действието не може да се върне.",
            parent=self.app.root,
        ):
            return
        self.db.delete_timer(timer.id)
        self.refresh(full=True)
        self.app.set_status(f"Изтрит таймер: {timer.display_name}.")
