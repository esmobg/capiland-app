"""Раздел „История“ — завършени цикли и обобщение."""

from __future__ import annotations

import csv

import wx

from .. import planner
from ..models import type_label
from ..timeutil import format_duration, format_dt
from .timers_panel import quantity_text
from .common import RowList, confirm, message, read_only_text

LOG_COLUMNS = [
    ("Потвърдено", 140, wx.LIST_FORMAT_LEFT),
    ("Продукт", 160, wx.LIST_FORMAT_LEFT),
    ("Количество", 90, wx.LIST_FORMAT_RIGHT),
    ("Компания", 140, wx.LIST_FORMAT_LEFT),
    ("Свят", 130, wx.LIST_FORMAT_LEFT),
    ("Дейност", 100, wx.LIST_FORMAT_LEFT),
    ("Печалба", 100, wx.LIST_FORMAT_RIGHT),
]
SUM_COLUMNS = [
    ("Продукт", 170, wx.LIST_FORMAT_LEFT),
    ("Качество", 80, wx.LIST_FORMAT_LEFT),
    ("Дейност", 110, wx.LIST_FORMAT_LEFT),
    ("Цикли", 70, wx.LIST_FORMAT_RIGHT),
    ("Общо бройки", 110, wx.LIST_FORMAT_RIGHT),
    ("Средно време", 110, wx.LIST_FORMAT_RIGHT),
    ("Печалба на час", 120, wx.LIST_FORMAT_RIGHT),
]


class HistoryPanel(wx.Panel):
    def __init__(self, parent, frame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.db = frame.db
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Завършени цикли:"), 0, wx.TOP | wx.LEFT | wx.RIGHT, 8)
        self.log = RowList(self, LOG_COLUMNS, name="Завършени цикли")
        sizer.Add(self.log, 2, wx.EXPAND | wx.ALL, 8)
        sizer.Add(wx.StaticText(self, label="Обобщение по продукт:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.summary = RowList(self, SUM_COLUMNS, name="Обобщение по продукт")
        sizer.Add(self.summary, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(wx.StaticText(self, label="Общо:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.total = read_only_text(self, lines=2)
        self.total.SetName("Общо")
        sizer.Add(self.total, 0, wx.EXPAND | wx.ALL, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Изнеси в CSV", self.export), ("Изчисти историята", self.clear)):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            buttons.Add(button, 0, wx.ALL, 4)
        sizer.Add(buttons, 0, wx.ALL, 4)
        self.SetSizer(sizer)

    def refresh(self) -> None:
        entries = self.db.list_history()
        self.log.set_rows([(e.id, [format_dt(e.finished_at, "%d.%m.%Y %H:%M"), e.product or type_label(e.type),
                                   quantity_text(e.quantity),
                                   e.line or "—", e.world or "—", type_label(e.type),
                                   planner.format_money(e.profit) if e.profit else "—"], "running")
                           for e in entries])
        rows = planner.summarize_history(entries)
        self.summary.set_rows([(i, [r["product"], r["quality"] or "—", r["type_label"], str(r["cycles"]),
                                    quantity_text(r["quantity"]) or "—",
                                    format_duration(r["avg_seconds"]),
                                    planner.format_money(r["profit_per_hour"]) if r["profit_per_hour"] else "—"],
                               "running") for i, r in enumerate(rows)])
        if entries:
            profit = sum(e.profit for e in entries)
            text = f"{len(entries)} завършени цикъла, обща печалба {planner.format_money(profit)}."
        else:
            text = "Още няма завършени цикли. Потвърди готов таймер с Ctrl+D и ще се запише тук."
        if not self.total.HasFocus():
            self.total.SetValue(text)

    def export(self) -> None:
        entries = self.db.list_history()
        if not entries:
            self.frame.announce("Историята е празна.", interrupt=True)
            return
        with wx.FileDialog(self.frame, "Изнасяне на историята", defaultFile="istoriya.csv",
                           wildcard="CSV файл (*.csv)|*.csv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["Потвърдено", "Продукт", "Качество", "Дейност", "Количество",
                                 "Компания", "Свят", "Край", "Цикъл", "Печалба"])
                for e in entries:
                    writer.writerow([format_dt(e.finished_at, "%d.%m.%Y %H:%M"), e.product, e.quality,
                                     type_label(e.type), e.quantity, e.line, e.world,
                                     format_dt(e.end_at, "%d.%m.%Y %H:%M"), e.cycle_no, e.profit])
        except OSError as exc:
            message(self.frame, f"Не можах да запиша файла: {exc}", "Грешка", wx.ICON_ERROR)
            return
        self.frame.announce(f"Изнесени {len(entries)} записа.")

    def clear(self) -> None:
        if confirm(self.frame, "Да изтрия ли цялата история?\nДействието не може да се върне.",
                   "Изчистване"):
            self.db.clear_history()
            self.refresh()
            self.frame.announce("Историята е изчистена.", interrupt=True)
