"""Диалог „Внос на списък“ — поставяш бележките, проверяваш, внасяш."""

from __future__ import annotations

import wx

from .. import catalog, importer
from ..models import TYPE_LABELS, TYPE_ORDER, type_label
from ..timeutil import format_when, now as time_now
from .timers_panel import quantity_text
from .common import RowList, labeled, read_only_text, show_error

COLUMNS = [
    ("Кога", 150, wx.LIST_FORMAT_LEFT),
    ("Продукт", 150, wx.LIST_FORMAT_LEFT),
    ("Количество", 90, wx.LIST_FORMAT_RIGHT),
    ("Компания", 140, wx.LIST_FORMAT_LEFT),
    ("Свят", 130, wx.LIST_FORMAT_LEFT),
    ("Дейност", 100, wx.LIST_FORMAT_LEFT),
    ("Бележка", 160, wx.LIST_FORMAT_LEFT),
]


class ImportDialog(wx.Dialog):
    def __init__(self, parent, db, settings, speak) -> None:
        super().__init__(parent, title="Внос на списък",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        self.db = db
        self.settings = settings
        self.speak = speak
        self.result: importer.ImportResult | None = None
        self.applied: dict | None = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(
            self, label="Постави бележките си така, както ги водиш. Данни за вход "
                        "(потребителски имена и пароли) се пропускат и не се пазят."),
            0, wx.ALL, 8)

        self.text = labeled(self, sizer, "Постави списъка тук:", wx.TextCtrl,
                            style=wx.TE_MULTILINE | wx.TE_DONTWRAP, proportion=2)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Свят за редовете без посочен свят:"),
                0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        worlds = list(dict.fromkeys(list(catalog.KNOWN_WORLDS) + db.list_worlds()))
        self.world = wx.ComboBox(self, choices=worlds)
        self.world.SetName("Свят за редовете без посочен свят")
        self.world.SetValue(str(settings.get("default_world", "") or ""))
        row.Add(self.world, 1, wx.RIGHT, 8)
        self.parse_button = wx.Button(self, label="&Разпознай")
        row.Add(self.parse_button, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.summary = labeled(self, sizer, "Обобщение:", read_only_text, lines=3)

        self.list = labeled(self, sizer, "Разпознати таймери (интервалът слага или маха отметка):",
                            RowList, COLUMNS, checkboxes=True, proportion=3)

        actions = wx.WrapSizer(wx.HORIZONTAL)
        self.action_buttons = []
        for label, handler in (
            ("Отметни всички", lambda: self._check_all(True)),
            ("Махни всички отметки", lambda: self._check_all(False)),
            ("Смени &дейността на избрания…", self._change_type),
            ("Смени &света на избрания…", self._change_world),
        ):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            actions.Add(button, 0, wx.ALL, 4)
            self.action_buttons.append(button)
        sizer.Add(actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        self.unrecognized = labeled(self, sizer, "Неразпознати редове:", read_only_text, lines=3)

        buttons = wx.StdDialogButtonSizer()
        self.ok = wx.Button(self, wx.ID_OK, "&Внеси отметнатите")
        buttons.AddButton(self.ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL, "Затвори"))
        buttons.Realize()
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(sizer)
        self.SetSize(self.FromDIP(wx.Size(1000, 780)))
        self.CentreOnParent()

        self.parse_button.Bind(wx.EVT_BUTTON, lambda _e: self._parse())
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.list.Bind(wx.EVT_LIST_ITEM_CHECKED, lambda e: self._on_check(e, True))
        self.list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, lambda e: self._on_check(e, False))
        self._set_result_enabled(False)
        wx.CallAfter(self.text.SetFocus)

    # ------------------------------------------------------------ разпознаване

    def _set_result_enabled(self, enabled: bool) -> None:
        for control in [self.list, self.ok] + self.action_buttons:
            control.Enable(enabled)

    def parse_text(self, text: str, world: str) -> importer.ImportResult:
        known = [p.name for p in self.db.list_products()]
        result = importer.parse(text, world, now=time_now(), known_products=known)
        importer.mark_existing(result, self.db)
        return result

    def _parse(self) -> None:
        text = self.text.GetValue()
        if not text.strip():
            show_error(self, "Първо постави списъка в полето.", self.text)
            return
        world = self.world.GetValue().strip()
        self.result = self.parse_text(text, world)
        self._fill()
        summary = self.result.summary()
        if not world and any(importer.NOTE_NO_WORLD in e.notes for e in self.result.entries):
            summary += " Някои редове са без свят — избери свят и натисни „Разпознай“ пак."
        self.summary.SetValue(summary)
        self.unrecognized.SetValue(
            "\n".join(f"ред {n}: {t}" for n, t in self.result.unrecognized) or "Няма.")
        self._set_result_enabled(bool(self.result.entries))
        self.summary.SetFocus()
        self.speak(summary)

    def _fill(self) -> None:
        now = time_now()
        rows = []
        for index, entry in enumerate(self.result.entries):
            rows.append((index, [
                format_when(entry.end_at, now),
                entry.product or type_label(entry.type),
                quantity_text(entry.quantity),
                entry.company or "—",
                entry.world or "—",
                type_label(entry.type),
                ", ".join(entry.notes),
            ], "running" if entry.selected else "paused"))
        self.list._ids = []
        self.list.set_rows(rows)
        for index, entry in enumerate(self.result.entries):
            self.list.CheckItem(index, entry.selected)

    def _on_check(self, event, checked: bool) -> None:
        if self.result is not None and 0 <= event.GetIndex() < len(self.result.entries):
            self.result.entries[event.GetIndex()].selected = checked

    def _check_all(self, checked: bool) -> None:
        if self.result is None:
            return
        for index, entry in enumerate(self.result.entries):
            entry.selected = checked
            self.list.CheckItem(index, checked)
        self.speak("Всички са отметнати." if checked else "Всички отметки са махнати.")

    def _selected_entry(self):
        index = self.list.GetFirstSelected()
        if self.result is None or index < 0:
            self.speak("Първо избери ред от списъка.")
            return None, -1
        return self.result.entries[index], index

    def _change_type(self) -> None:
        entry, index = self._selected_entry()
        if entry is None:
            return
        labels = [TYPE_LABELS[t] for t in TYPE_ORDER]
        dialog = wx.SingleChoiceDialog(self, "Дейност:", "Смяна на дейността", labels)
        dialog.SetSelection(TYPE_ORDER.index(entry.type) if entry.type in TYPE_ORDER else 0)
        if dialog.ShowModal() == wx.ID_OK:
            entry.type = TYPE_ORDER[dialog.GetSelection()]
            self.list.SetItem(index, 5, type_label(entry.type))
        dialog.Destroy()
        self.list.SetFocus()

    def _change_world(self) -> None:
        entry, index = self._selected_entry()
        if entry is None:
            return
        worlds = list(dict.fromkeys(list(catalog.KNOWN_WORLDS) + self.db.list_worlds()))
        dialog = wx.SingleChoiceDialog(self, "Свят:", "Смяна на света", worlds)
        if entry.world in worlds:
            dialog.SetSelection(worlds.index(entry.world))
        if dialog.ShowModal() == wx.ID_OK:
            entry.world = worlds[dialog.GetSelection()]
            if importer.NOTE_NO_WORLD in entry.notes:
                entry.notes.remove(importer.NOTE_NO_WORLD)
            self.list.SetItem(index, 4, entry.world)
            self.list.SetItem(index, 6, ", ".join(entry.notes))
        dialog.Destroy()
        self.list.SetFocus()

    # -------------------------------------------------------------- внос

    def _on_ok(self, _event) -> None:
        if self.result is None:
            show_error(self, "Първо натисни „Разпознай“.", self.parse_button)
            return
        selected = len(self.result.selected_entries)
        if selected == 0:
            show_error(self, "Няма отметнат нито един таймер.", self.list)
            return
        world = self.world.GetValue().strip()
        if world:
            self.settings.set("default_world", world)
            self.settings.save()
        self.applied = importer.apply(self.result, self.db, now=time_now())
        self.EndModal(wx.ID_OK)
