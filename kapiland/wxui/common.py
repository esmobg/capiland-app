"""Общи помощници за достъпен интерфейс.

Правилата, които налагат:

* всяко поле има етикет, създаден **непосредствено преди** него — Windows
  взима от него името, което четецът изговаря;
* списъците пазят фокуса върху същия запис при обновяване и не се
  пренареждат сами;
* цветовете на редовете са проверените палитри от ``a11y`` и не се
  задават, когато Windows е в режим „Висок контраст“.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import wx

from .. import a11y

SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001


class _HIGHCONTRAST(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR)]


def high_contrast_active() -> bool:
    if sys.platform != "win32":
        return False
    info = _HIGHCONTRAST()
    info.cbSize = ctypes.sizeof(_HIGHCONTRAST)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST, info.cbSize, ctypes.byref(info), 0)
    except (AttributeError, OSError):
        return False
    return bool(ok) and bool(info.dwFlags & HCF_HIGHCONTRASTON)


def system_dark() -> bool:
    try:
        return wx.SystemSettings.GetAppearance().IsDark()
    except AttributeError:
        return False


# -------------------------------------------------------------- имена

def name_control(control: wx.Window, label: str) -> None:
    """Име за четеца. Полето го взима от етикета преди него; числовите полета
    имат и отделни стрелки (msctls_updown32), които трябва да се именуват ръчно.
    """
    name = label.rstrip(": ")
    control.SetName(name)
    if isinstance(control, wx.SpinCtrl) and sys.platform == "win32":
        try:
            ctypes.windll.user32.SetWindowTextW(control.GetHandle(), name)
        except (AttributeError, OSError):
            pass


# -------------------------------------------------------------- форми

class Form:
    """Двуколонна форма: етикет, после полето (в този ред за четеца)."""

    def __init__(self, parent: wx.Window, gap: int = 6) -> None:
        self.parent = parent
        self.sizer = wx.FlexGridSizer(cols=2, vgap=gap, hgap=10)
        self.sizer.AddGrowableCol(1, 1)

    def add(self, label: str, factory, *args, **kwargs) -> wx.Window:
        text = wx.StaticText(self.parent, label=label)
        control = factory(self.parent, *args, **kwargs)
        name_control(control, label)
        self.sizer.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
        self.sizer.Add(control, 1, wx.EXPAND)
        return control

    def add_full(self, window: wx.Window) -> wx.Window:
        self.sizer.Add(window, 0)
        self.sizer.AddSpacer(0)
        return window


def labeled(parent: wx.Window, sizer: wx.Sizer, label: str, factory,
            *args, proportion: int = 0, **kwargs) -> wx.Window:
    """Етикет над полето (за списъци и големи полета)."""
    text = wx.StaticText(parent, label=label)
    control = factory(parent, *args, **kwargs)
    name_control(control, label)
    sizer.Add(text, 0, wx.TOP | wx.LEFT | wx.RIGHT, 6)
    sizer.Add(control, proportion, wx.EXPAND | wx.ALL, 6)
    return control


def read_only_text(parent: wx.Window, lines: int = 3) -> wx.TextCtrl:
    """Поле само за четене — четецът го прочита цялото, когато получи фокус."""
    # Обикновено поле, не RichEdit: не праща събития за всяка промяна на текста.
    style = wx.TE_MULTILINE | wx.TE_READONLY
    control = wx.TextCtrl(parent, style=style)
    control.SetMinSize((-1, max(2, lines) * 20))
    return control


def message(parent, text: str, title: str = "Kapilands Таймер",
            icon: int = wx.ICON_INFORMATION) -> None:
    wx.MessageBox(text, title, wx.OK | icon, parent)


def confirm(parent, text: str, title: str = "Потвърждение") -> bool:
    return wx.MessageBox(text, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                         parent) == wx.YES


def show_error(parent, text: str, focus: wx.Window | None = None) -> None:
    """Грешка: съобщение, което четецът чете, после фокус върху грешното поле."""
    wx.MessageBox(text, "Проверка", wx.OK | wx.ICON_WARNING, parent)
    if focus is not None:
        focus.SetFocus()
        if isinstance(focus, wx.TextCtrl):
            focus.SelectAll()


def apply_font_scale(window: wx.Window, percent: int) -> None:
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    font = wx.Font(base)
    font.SetFractionalPointSize(base.GetFractionalPointSize() * max(100, min(200, percent)) / 100)

    def walk(win: wx.Window) -> None:
        win.SetFont(font)
        for child in win.GetChildren():
            walk(child)

    walk(window)
    window.Layout()


# ------------------------------------------------------------ списък

class RowList(wx.ListCtrl):
    """Отчетен списък, който пази фокуса и не се пренарежда сам.

    Редовете се подават като ``(id, [текстове], състояние)``. Ако редът на
    id-тата не се е сменил, се обновяват само променените клетки.
    """

    def __init__(self, parent: wx.Window, columns: list[tuple[str, int, int]],
                 checkboxes: bool = False, name: str = "") -> None:
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_THEME)
        if name:
            self.SetName(name)
        if checkboxes:
            self.EnableCheckBoxes(True)
        for index, (title, width, align) in enumerate(columns):
            self.InsertColumn(index, title, align, self.FromDIP(width))
        self.column_count = len(columns)
        self._ids: list[int] = []
        self._states: dict[int, str] = {}
        self.palette: dict | None = None

    # --- id ---
    def ids(self) -> list[int]:
        return list(self._ids)

    def id_at(self, index: int) -> int | None:
        return self._ids[index] if 0 <= index < len(self._ids) else None

    def selected_id(self) -> int | None:
        index = self.GetFirstSelected()
        if index < 0:
            index = self.GetFocusedItem()
        return self.id_at(index)

    def focus_id(self, row_id: int, select: bool = True) -> bool:
        if row_id not in self._ids:
            return False
        index = self._ids.index(row_id)
        if select:
            self.Select(index, True)
        self.Focus(index)
        self.EnsureVisible(index)
        return True

    # --- данни ---
    def set_rows(self, rows: list[tuple[int, list[str], str]]) -> bool:
        """Връща True, ако списъкът е преначертан изцяло."""
        new_ids = [row[0] for row in rows]
        if new_ids != self._ids:
            keep = self.selected_id()
            keep_index = max(0, self.GetFirstSelected())
            self.Freeze()
            try:
                self.DeleteAllItems()
                self._states.clear()
                for index, (row_id, texts, state) in enumerate(rows):
                    self.InsertItem(index, texts[0] if texts else "")
                    for column, value in enumerate(texts[1:self.column_count], start=1):
                        self.SetItem(index, column, value)
                    self._paint(index, row_id, state)
                self._ids = new_ids
            finally:
                self.Thaw()
            if keep is not None and keep in new_ids:
                self.focus_id(keep)
            elif new_ids:
                index = min(keep_index, len(new_ids) - 1)
                self.Select(index, True)
                self.Focus(index)
            return True

        for index, (row_id, texts, state) in enumerate(rows):
            for column, value in enumerate(texts[:self.column_count]):
                if self.GetItemText(index, column) != value:
                    self.SetItem(index, column, value)
            if self._states.get(row_id) != state:
                self._paint(index, row_id, state)
        return False

    def _paint(self, index: int, row_id: int, state: str) -> None:
        self._states[row_id] = state
        if self.palette is None or high_contrast_active():
            return
        colours = self.palette.get("rows", {}).get(state)
        if colours:
            self.SetItemBackgroundColour(index, wx.Colour(colours["bg"]))
            self.SetItemTextColour(index, wx.Colour(colours["fg"]))

    def checked_ids(self) -> list[int]:
        return [row_id for index, row_id in enumerate(self._ids) if self.IsItemChecked(index)]


def palette_for(theme_setting: str) -> dict:
    if theme_setting == "dark" or (theme_setting == "system" and system_dark()):
        return a11y.theme("dark")
    return a11y.theme("light")
