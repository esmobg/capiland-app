"""Раздел „Каталог“ — продукти, сгради, времена и цени."""

from __future__ import annotations

import wx

from .. import catalog, gamedata, planner
from ..models import TYPE_LABELS, TYPE_ORDER, Product, type_label
from ..timeutil import format_duration, parse_duration
from .common import Form, RowList, confirm, message, read_only_text, show_error

COLUMNS = [
    ("Продукт", 170, wx.LIST_FORMAT_LEFT),
    ("Качество", 80, wx.LIST_FORMAT_LEFT),
    ("Категория", 130, wx.LIST_FORMAT_LEFT),
    ("Сграда", 180, wx.LIST_FORMAT_LEFT),
    ("Наука", 140, wx.LIST_FORMAT_LEFT),
    ("Времетраене", 100, wx.LIST_FORMAT_RIGHT),
    ("Цена", 80, wx.LIST_FORMAT_RIGHT),
    ("Печалба на час", 120, wx.LIST_FORMAT_RIGHT),
]


def _num(value: float) -> str:
    if not value:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _as_float(text: str) -> float | None:
    text = (text or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


class ProductDialog(wx.Dialog):
    def __init__(self, parent, product: Product | None) -> None:
        super().__init__(parent, title="Редактиране на продукт" if product else "Нов продукт",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.original = product
        self.result: Product | None = None
        outer = wx.BoxSizer(wx.VERTICAL)
        form = Form(self)
        self.name = form.add("Име:", wx.TextCtrl)
        self.quality = form.add("Качество:", wx.TextCtrl)
        self.category = form.add("Категория:", wx.ComboBox, choices=list(catalog.CATEGORIES))
        self.building = form.add("Сграда:", wx.ComboBox, choices=catalog.building_names())
        self.research = form.add("Наука:", wx.ComboBox, choices=list(gamedata.RESEARCH_BRANCHES))
        self.kind = form.add("Дейност по подразбиране:", wx.Choice,
                             choices=[TYPE_LABELS[t] for t in TYPE_ORDER])
        self.duration = form.add("Времетраене (напр. 2ч 30м):", wx.TextCtrl)
        self.quantity = form.add("Количество:", wx.TextCtrl)
        self.cost = form.add("Себестойност за бройка:", wx.TextCtrl)
        self.price = form.add("Цена за бройка:", wx.TextCtrl)
        self.note = form.add("Бележка:", wx.TextCtrl)
        outer.Add(form.sizer, 1, wx.EXPAND | wx.ALL, 12)
        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, "Запиши")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL, "Отказ"))
        buttons.Realize()
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(outer)

        p = product or Product()
        self.name.SetValue(p.name)
        self.quality.SetValue(p.quality)
        self.category.SetValue(p.category)
        self.building.SetValue(p.building)
        self.research.SetValue(p.research)
        self.kind.SetSelection(TYPE_ORDER.index(p.default_type) if p.default_type in TYPE_ORDER else 0)
        self.duration.SetValue(format_duration(p.default_duration_sec) if p.default_duration_sec else "")
        self.quantity.SetValue(_num(p.default_quantity))
        self.cost.SetValue(_num(p.unit_cost))
        self.price.SetValue(_num(p.unit_price))
        self.note.SetValue(p.note)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.CentreOnParent()
        wx.CallAfter(self.name.SetFocus)

    def _on_ok(self, _event) -> None:
        name = self.name.GetValue().strip()
        if not name:
            show_error(self, "Името е задължително.", self.name)
            return
        duration = 0
        if self.duration.GetValue().strip():
            try:
                duration = parse_duration(self.duration.GetValue())
            except ValueError as exc:
                show_error(self, str(exc), self.duration)
                return
        numbers = {}
        for key, control, label in (("quantity", self.quantity, "Количеството"),
                                    ("cost", self.cost, "Себестойността"),
                                    ("price", self.price, "Цената")):
            value = _as_float(control.GetValue())
            if value is None:
                show_error(self, f"{label} трябва да е число.", control)
                return
            numbers[key] = value
        product = self.original or Product()
        product.name = name
        product.quality = self.quality.GetValue().strip()
        product.category = self.category.GetValue().strip()
        product.building = self.building.GetValue().strip()
        product.research = self.research.GetValue().strip()
        product.default_type = TYPE_ORDER[max(0, self.kind.GetSelection())]
        product.default_duration_sec = duration
        product.default_quantity = numbers["quantity"]
        product.unit_cost = numbers["cost"]
        product.unit_price = numbers["price"]
        product.note = self.note.GetValue().strip()
        self.result = product
        self.EndModal(wx.ID_OK)


class CatalogPanel(wx.Panel):
    def __init__(self, parent, frame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.db = frame.db
        self._products: dict[int, Product] = {}
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Продукти:"), 0, wx.TOP | wx.LEFT | wx.RIGHT, 8)
        self.list = RowList(self, COLUMNS, name="Продукти")
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(wx.StaticText(self, label="Най-изгоден:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.hint = read_only_text(self, lines=2)
        self.hint.SetName("Най-изгоден")
        sizer.Add(self.hint, 0, wx.EXPAND | wx.ALL, 8)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (("&Нов продукт", self.new_product), ("&Редактирай", self.edit_selected),
                               ("Изтрий", self.delete_selected), ("Изнеси в CSV", self.export_csv),
                               ("Внеси от CSV", self.import_csv),
                               ("Внеси списък (TXT)", self.import_lists),
                               ("Изнеси списъци (TXT)", self.export_lists)):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            buttons.Add(button, 0, wx.ALL, 4)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.edit_selected())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def refresh(self) -> None:
        products = self.db.list_products()
        self._products = {p.id: p for p in products if p.id is not None}
        rows, best = [], None
        for p in products:
            money = planner.profit(p.default_quantity, p.unit_cost, p.unit_price, p.default_duration_sec)
            rows.append((p.id, [p.name, p.quality or "—", p.category or "—", p.building or "—",
                                p.research or "—",
                                format_duration(p.default_duration_sec) if p.default_duration_sec else "—",
                                _num(p.unit_price) or "—",
                                planner.format_money(money.per_hour) if money.per_hour else "—"],
                         "running"))
            if money.per_hour and (best is None or money.per_hour > best[1]):
                best = (p.display_name, money.per_hour)
        self.list.set_rows(rows)
        text = (f"{best[0]} — {planner.format_money(best[1])} печалба на час." if best else
                "Попълни времетраене, количество, себестойност и цена, за да видиш кой продукт "
                "носи най-много печалба на час.")
        if not self.hint.HasFocus():
            self.hint.SetValue(text)

    def selected(self) -> Product | None:
        row_id = self.list.selected_id()
        return self._products.get(row_id) if row_id is not None else None

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE and not event.HasAnyModifiers():
            self.delete_selected()
            return
        event.Skip()

    def _edit(self, product: Product | None) -> None:
        dialog = ProductDialog(self.frame, product)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.result is not None:
                self.db.upsert_product(dialog.result)
                self.refresh()
                self.list.focus_id(dialog.result.id)
                self.frame.announce("Записано.")
        finally:
            dialog.Destroy()
        self.list.SetFocus()

    def new_product(self) -> None:
        self._edit(None)

    def edit_selected(self) -> None:
        product = self.selected()
        if product is None:
            self.frame.announce("Първо избери продукт.", interrupt=True)
            return
        self._edit(product)

    def delete_selected(self) -> None:
        product = self.selected()
        if product is None:
            self.frame.announce("Първо избери продукт.", interrupt=True)
            return
        if confirm(self.frame, f"Да изтрия ли „{product.display_name}“ от каталога?", "Изтриване"):
            self.db.delete_product(product.id)
            self.refresh()
            self.frame.announce("Изтрито.", interrupt=True)
        self.list.SetFocus()

    def export_csv(self) -> None:
        with wx.FileDialog(self.frame, "Изнасяне на каталога", defaultFile="katalog.csv",
                           wildcard="CSV файл (*.csv)|*.csv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            count = catalog.export_csv(self.db, path)
        except OSError as exc:
            message(self.frame, f"Не можах да запиша файла: {exc}", "Грешка", wx.ICON_ERROR)
            return
        self.frame.announce(f"Изнесени {count} продукта.")

    def import_csv(self) -> None:
        with wx.FileDialog(self.frame, "Внасяне на каталог", wildcard="CSV файл (*.csv)|*.csv",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            count = catalog.import_csv(self.db, path)
        except (OSError, ValueError) as exc:
            message(self.frame, f"Не можах да прочета файла: {exc}", "Грешка", wx.ICON_ERROR)
            return
        self.refresh()
        self.frame.announce(f"Внесени {count} продукта.")

    def import_lists(self) -> None:
        with wx.FileDialog(self.frame, "Внасяне на списък с изследвания или производство",
                           wildcard="Текстов файл (*.txt)|*.txt",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            result = catalog.import_lists(self.db, path)
        except (OSError, ValueError) as exc:
            message(self.frame, f"Не можах да внеса списъка: {exc}", "Грешка", wx.ICON_ERROR)
            return
        self.refresh()
        self.frame.announce(import_lists_summary(result))

    def export_lists(self) -> None:
        with wx.DirDialog(self.frame, "Папка за Изследвания.txt и Производство.txt",
                          style=wx.DD_DEFAULT_STYLE) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            folder = dialog.GetPath()
        try:
            counts = catalog.export_lists(self.db, folder)
        except OSError as exc:
            message(self.frame, f"Не можах да запиша файловете: {exc}", "Грешка", wx.ICON_ERROR)
            return
        self.frame.announce(
            f"Изнесени: {counts[gamedata.RESEARCH]} продукта в Изследвания.txt и "
            f"{counts[gamedata.PRODUCTION]} в Производство.txt.")


def import_lists_summary(result: dict) -> str:
    """„Внесени 103 продукта в 7 науки, 5 от тях нови.“ — за екрана и четеца."""
    where = "науки" if result["kind"] == gamedata.RESEARCH else "сгради"
    count = result["products"]
    text = f"Внесени {count} {'продукт' if count == 1 else 'продукта'} в {result['groups']} {where}"
    if result["added"]:
        text += f", {result['added']} от тях нови"
    return text + "."
