"""Раздел „История“ — завършени цикли и обобщение по продукт."""

from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import planner
from ..models import type_label
from ..timeutil import format_duration, format_dt

LOG_COLUMNS = (
    ("finished", "Потвърдено", 140, "w"),
    ("product", "Продукт", 165, "w"),
    ("quality", "Качество", 85, "w"),
    ("type", "Тип", 105, "w"),
    ("quantity", "Кол.", 80, "e"),
    ("line", "Линия", 100, "w"),
    ("duration", "Времетраене", 120, "e"),
    ("cycle", "Цикъл", 70, "center"),
    ("profit", "Печалба", 110, "e"),
)

SUM_COLUMNS = (
    ("product", "Продукт", 165, "w"),
    ("quality", "Качество", 85, "w"),
    ("type", "Тип", 105, "w"),
    ("cycles", "Цикли", 80, "e"),
    ("quantity", "Общо бройки", 120, "e"),
    ("avg", "Средно време", 130, "e"),
    ("qty_hour", "Бр./час", 100, "e"),
    ("profit", "Обща печалба", 130, "e"),
    ("profit_hour", "Печалба/час", 120, "e"),
)


class HistoryView(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.db = app.db
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(3, weight=2)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(bar, text="Завършени цикли", style="Heading.TLabel").pack(side="left")
        ttk.Button(bar, text="Изчисти историята", command=self.clear).pack(side="right")
        ttk.Button(bar, text="Изнеси в CSV", command=self.export).pack(
            side="right", padx=(0, 8))

        self.log = self._make_tree(LOG_COLUMNS, row=1)

        ttk.Label(self, text="Обобщение по продукт", style="Heading.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 6))
        self.summary = self._make_tree(SUM_COLUMNS, row=3)

        total = ttk.Frame(self, style="Surface.TFrame", padding=10)
        total.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        total.columnconfigure(0, weight=1)
        self.total_var = tk.StringVar(value="")
        ttk.Label(total, textvariable=self.total_var, style="Surface.TLabel",
                  justify="left", wraplength=900).grid(row=0, column=0, sticky="w")

    def _make_tree(self, columns, row: int) -> ttk.Treeview:
        frame = ttk.Frame(self)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                            selectmode="browse", takefocus=True)
        for key, title, width, anchor in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor=anchor, stretch=(key == "product"))
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        self.app.style.tag_tree(tree)
        return tree

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        entries = self.db.list_history()
        self.log.delete(*self.log.get_children())
        for entry in entries:
            self.log.insert("", "end", iid=str(entry.id), values=(
                format_dt(entry.finished_at, "%d.%m.%Y %H:%M"),
                entry.product or "—",
                entry.quality or "—",
                type_label(entry.type),
                _num(entry.quantity),
                entry.line or "—",
                format_duration(entry.duration_sec),
                entry.cycle_no,
                planner.format_money(entry.profit) if entry.profit else "—",
            ))

        rows = planner.summarize_history(entries)
        self.summary.delete(*self.summary.get_children())
        for index, row in enumerate(rows):
            self.summary.insert("", "end", iid=f"s{index}", values=(
                row["product"],
                row["quality"] or "—",
                row["type_label"],
                row["cycles"],
                _num(row["quantity"]),
                format_duration(row["avg_seconds"]),
                f"{row['quantity_per_hour']:.1f}" if row["quantity_per_hour"] else "—",
                planner.format_money(row["profit"]) if row["profit"] else "—",
                planner.format_money(row["profit_per_hour"])
                if row["profit_per_hour"] else "—",
            ))

        if entries:
            total_profit = sum(e.profit for e in entries)
            total_hours = sum(e.duration_sec for e in entries) / 3600.0
            best = max(rows, key=lambda r: r["profit_per_hour"], default=None)
            text = (f"Общо {len(entries)} завършени цикъла, "
                    f"{format_duration(total_hours * 3600)} производство, "
                    f"обща печалба {planner.format_money(total_profit)}.")
            if best and best["profit_per_hour"]:
                text += (f"  Най-доходен продукт: {best['product']} — "
                         f"{planner.format_money(best['profit_per_hour'])} на час.")
            self.total_var.set(text)
        else:
            self.total_var.set(
                "Още няма завършени цикли. Потвърдете готов таймер с бутона "
                "„Готово“ и той ще се запише тук.")

    # ------------------------------------------------------------------

    def export(self) -> None:
        entries = self.db.list_history()
        if not entries:
            self.app.set_status("Историята е празна — няма какво да се изнесе.")
            return
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="Изнасяне на историята",
            defaultextension=".csv", initialfile="istoriya.csv",
            filetypes=[("CSV файл", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["Потвърдено", "Продукт", "Качество", "Тип",
                                 "Количество",
                                 "Линия", "Старт", "Край", "Времетраене (сек)",
                                 "Цикъл", "Печалба"])
                for entry in entries:
                    writer.writerow([
                        format_dt(entry.finished_at, "%d.%m.%Y %H:%M:%S"),
                        entry.product, entry.quality, type_label(entry.type),
                        entry.quantity,
                        entry.line,
                        format_dt(entry.start_at, "%d.%m.%Y %H:%M:%S"),
                        format_dt(entry.end_at, "%d.%m.%Y %H:%M:%S"),
                        entry.duration_sec, entry.cycle_no, entry.profit,
                    ])
        except OSError as exc:
            messagebox.showerror("Грешка", f"Не можах да запиша файла:\n{exc}",
                                 parent=self.app.root)
            return
        self.app.set_status(f"Изнесени {len(entries)} записа в {path}")

    def clear(self) -> None:
        if not messagebox.askyesno(
            "Изчистване",
            "Да изтрия ли цялата история?\nДействието не може да се върне.",
            parent=self.app.root,
        ):
            return
        self.db.clear_history()
        self.refresh()
        self.app.set_status("Историята е изчистена.")


def _num(value: float) -> str:
    if not value:
        return "—"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"
