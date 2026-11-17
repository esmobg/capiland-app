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
    control.text_lines = max(2, lines)
    fit_text_height(control)
    return control


def fit_text_height(control: wx.TextCtrl) -> None:
    """Височина за толкова реда с текущия шрифт — и при 200% текстът се побира."""
    lines = getattr(control, "text_lines", 0)
    if lines:
        control.SetMinSize((-1, max(lines * 20, lines * control.GetCharHeight() + 10)))


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
    """Размер на текста 100–200% за прозореца и всичко в него (WCAG 1.4.4).

    Заедно с текста растат колоните на списъците и полетата за четене —
    иначе при 200% думите се режат. Диалозите, отворени след това, взимат
    размера с ``adopt_parent_font``.
    """
    percent = max(100, min(200, percent))
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    font = wx.Font(base)
    font.SetFractionalPointSize(base.GetFractionalPointSize() * percent / 100)
    window.font_scale = percent

    def walk(win: wx.Window) -> None:
        win.SetFont(font)
        if isinstance(win, RowList):
            win.scale_columns(percent)
        elif isinstance(win, wx.TextCtrl):
            fit_text_height(win)
        for child in win.GetChildren():
            walk(child)
        if win.GetSizer() is not None:
            win.Layout()  # и разделите, които не са на екрана в момента

    walk(window)
    window.Layout()


def adopt_parent_font(dialog: wx.Window) -> int:
    """Диалогът взима размера на текста от главния прозорец.

    Вика се веднага след създаването на диалога, преди елементите му: те
    наследяват шрифта сами. Връща мащаба в проценти — за списъците вътре.
    """
    parent = dialog.GetParent()
    if parent is None:
        return 100
    dialog.SetFont(parent.GetFont())
    dialog.font_scale = int(getattr(parent, "font_scale", 100) or 100)
    return dialog.font_scale


def display_area(window: wx.Window) -> wx.Rect:
    """Свободната част на екрана, на който е прозорецът (без лентата на задачите)."""
    index = wx.Display.GetFromWindow(window.GetParent() or window)
    return wx.Display(0 if index == wx.NOT_FOUND else index).GetClientArea()


def scroll_area(dialog: wx.Dialog) -> wx.ScrolledWindow:
    """Място за полетата на диалог, което се превърта, когато не се побира.

    При едър текст на малък екран диалогът би излязъл извън екрана и бутоните
    му биха останали отдолу. Полетата се създават тук, а бутоните — направо в
    диалога, за да се виждат винаги. Фокусираното поле се превърта само в
    изгледа.
    """
    area = wx.ScrolledWindow(dialog, style=wx.TAB_TRAVERSAL)
    area.SetLabel("")  # иначе четецът може да изговори името на класа
    return area


def fit_dialog(dialog: wx.Dialog, area: wx.ScrolledWindow | None = None,
               min_width: int = 0, min_height: int = 0) -> None:
    """Размер по съдържанието, но никога по-голям от екрана.

    ``min_width`` и ``min_height`` са при 100% текст и растат с мащаба му.
    """
    scale = int(getattr(dialog, "font_scale", 100) or 100) / 100
    step = max(8, dialog.GetCharHeight())
    if area is not None:
        area.SetScrollRate(step, step)
        area.SetMinSize(area.GetSizer().CalcMin())  # колкото иска съдържанието
    dialog.SetMinSize(wx.DefaultSize)
    wanted = dialog.GetSizer().ComputeFittingWindowSize(dialog)
    wanted.IncTo(dialog.FromDIP(wx.Size(int(min_width * scale), int(min_height * scale))))
    wanted.DecTo(display_area(dialog).GetSize())
    if area is not None:
        area.SetMinSize(wx.Size(step * 12, step * 4))  # по-малко от това — превърта се
    dialog.SetSize(wanted)
    dialog.Layout()


# ------------------------------------------------------------ списък

def _inherited_scale(window: wx.Window | None) -> int:
    """Мащабът на текста, зададен на прозореца или диалога, в който е елементът."""
    while window is not None:
        scale = getattr(window, "font_scale", None)
        if scale:
            return int(scale)
        window = window.GetParent()
    return 100


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
        self._widths: list[int] = []
        self._scale = _inherited_scale(parent)
        self.column_count = 0
        for index, (title, width, align) in enumerate(columns):
            self.add_column(index, title, width, align)
        self._ids: list[int] = []
        self._states: dict[int, str] = {}
        self.palette: dict | None = None

    # --- колони ---
    def _scaled(self, width: int) -> int:
        return self.FromDIP(int(round(width * self._scale / 100)))

    def add_column(self, index: int, title: str, width: int, align: int) -> None:
        self.InsertColumn(index, title, align, self._scaled(width))
        self._widths.insert(index, width)
        self.column_count = len(self._widths)

    def remove_column(self, index: int) -> None:
        self.DeleteColumn(index)
        del self._widths[index]
        self.column_count = len(self._widths)

    def scale_columns(self, percent: int) -> None:
        """Колоните следват размера на текста, за да не се реже при 200%."""
        if percent == self._scale:
            return
        self._scale = percent
        for index, width in enumerate(self._widths):
            self.SetColumnWidth(index, self._scaled(width))

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
