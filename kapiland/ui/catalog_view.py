"""Раздел „Каталог“ — продукти, времена, цени и сравнение по печалба."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import catalog, planner
from ..models import TYPE_LABELS, Product, label_to_type, type_label
from ..timeutil import format_duration, parse_duration

COLUMNS = (
    ("name", "Продукт", 165, "w"),
    ("quality", "Качество", 85, "w"),
    ("category", "Категория", 125, "w"),
    ("type", "Тип", 110, "w"),
    ("duration", "Времетраене", 120, "e"),
    ("quantity", "Количество", 100, "e"),
    ("cost", "Себестойност", 110, "e"),
    ("price", "Цена", 100, "e"),
    ("profit_hour", "Печалба/час", 120, "e"),
)


class CatalogView(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.db = app.db
        self._products: dict[int, Product] = {}
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(
            self,
            text="Времената и цените се запомнят сами от таймерите, които "
                 "въвеждаш. Тук можеш да ги поправиш и да сравниш кой продукт "
                 "носи най-много печалба на час.",
            style="Muted.TLabel", wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text="Нов продукт", style="Accent.TButton",
                   command=self.new_product).pack(side="left")
        for text, command in (
            ("Редактирай", self.edit_product),
            ("Изтрий", self.delete_product),
        ):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Внеси от CSV", command=self.import_csv).pack(
            side="right", padx=(8, 0))
        ttk.Button(bar, text="Изнеси в CSV", command=self.export_csv).pack(side="right")

        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse", takefocus=True)
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "name"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.app.style.tag_tree(self.tree)
        self.tree.bind("<Double-1>", lambda _e: self.edit_product())
        self.tree.bind("<Return>", lambda _e: self.edit_product())
        self.tree.bind("<Delete>", lambda _e: self.delete_product())

        hint = ttk.Frame(self, style="Surface.TFrame", padding=10)
        hint.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        hint.columnconfigure(0, weight=1)
        self.hint_var = tk.StringVar(value="")
        ttk.Label(hint, textvariable=self.hint_var, style="Surface.TLabel",
                  justify="left", wraplength=900).grid(row=0, column=0, sticky="w")

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        products = self.db.list_products()
        self._products = {p.id: p for p in products if p.id is not None}
        self.tree.delete(*self.tree.get_children())
        best = None
        for product in products:
            money = planner.profit(product.default_quantity, product.unit_cost,
                                   product.unit_price, product.default_duration_sec)
            self.tree.insert("", "end", iid=str(product.id), values=(
                product.name,
                product.quality or "—",
                product.category or "—",
                type_label(product.default_type),
                format_duration(product.default_duration_sec)
                if product.default_duration_sec else "—",
                _num(product.default_quantity),
                _num(product.unit_cost),
                _num(product.unit_price),
                planner.format_money(money.per_hour) if money.per_hour else "—",
            ))
            if money.per_hour and (best is None or money.per_hour > best[1]):
                best = (product.display_name, money.per_hour)
        if best:
            self.hint_var.set(
                f"Най-изгоден в момента: {best[0]} — "
                f"{planner.format_money(best[1])} печалба на час.")
        else:
            self.hint_var.set(
                "Попълни времетраене, количество, себестойност и цена, за да "
                "видиш кой продукт носи най-много печалба на час.")

    def _selected(self) -> Product | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._products.get(int(selection[0]))

    # ------------------------------------------------------------------

    def new_product(self) -> None:
        self._edit(None)

    def edit_product(self) -> None:
        product = self._selected()
        if product is None:
            self.app.set_status("Първо изберете продукт.")
            return
        self._edit(product)

    def _edit(self, product: Product | None) -> None:
        dialog = ProductDialog(self.app.root, self.app.style, product)
        self.app.root.wait_window(dialog)
        if dialog.result is not None:
            self.db.upsert_product(dialog.result)
            self.refresh()
            self.app.set_status(f"Записан продукт: {dialog.result.display_name}")

    def delete_product(self) -> None:
        product = self._selected()
        if product is None:
            self.app.set_status("Първо изберете продукт.")
            return
        if not messagebox.askyesno(
            "Изтриване", f"Да изтрия ли „{product.display_name}“ от каталога?",
            parent=self.app.root,
        ):
            return
        self.db.delete_product(product.id)
        self.refresh()
        self.app.set_status(f"Изтрит продукт: {product.name}")

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="Изнасяне на каталога",
            defaultextension=".csv", initialfile="katalog.csv",
            filetypes=[("CSV файл", "*.csv")])
        if not path:
            return
        try:
            count = catalog.export_csv(self.db, path)
        except OSError as exc:
            messagebox.showerror("Грешка", f"Не можах да запиша файла:\n{exc}",
                                 parent=self.app.root)
            return
        self.app.set_status(f"Изнесени {count} продукта в {path}")

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Внасяне на каталог",
            filetypes=[("CSV файл", "*.csv"), ("Всички файлове", "*.*")])
        if not path:
            return
        try:
            count = catalog.import_csv(self.db, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Грешка", f"Не можах да прочета файла:\n{exc}",
                                 parent=self.app.root)
            return
        self.refresh()
        self.app.set_status(f"Внесени {count} продукта.")


class ProductDialog(tk.Toplevel):
    """Диалог за един продукт."""

    def __init__(self, master, app_style, product: Product | None) -> None:
        super().__init__(master)
        self.result: Product | None = None
        self.original = product
        self.title("Редактиране на продукт" if product else "Нов продукт")
        self.transient(master)
        self.configure(background=app_style.colors["bg"])

        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        pad = {"padx": 10, "pady": 5}

        self.name_var = tk.StringVar(value=product.name if product else "")
        self.quality_var = tk.StringVar(value=product.quality if product else "")
        self.category_var = tk.StringVar(
            value=product.category if product else catalog.CATEGORIES[0])
        self.type_var = tk.StringVar(
            value=type_label(product.default_type) if product else
            type_label("production"))
        self.duration_var = tk.StringVar(
            value=format_duration(product.default_duration_sec)
            if product and product.default_duration_sec else "")
        self.quantity_var = tk.StringVar(
            value=_num(product.default_quantity) if product else "")
        self.cost_var = tk.StringVar(value=_num(product.unit_cost) if product else "")
        self.price_var = tk.StringVar(value=_num(product.unit_price) if product else "")
        self.note_var = tk.StringVar(value=product.note if product else "")

        rows = (
            ("Име:", ttk.Entry(body, textvariable=self.name_var)),
            ("Качество:", ttk.Entry(body, textvariable=self.quality_var)),
            ("Категория:", ttk.Combobox(body, textvariable=self.category_var,
                                        values=list(catalog.CATEGORIES))),
            ("Тип по подразбиране:", ttk.Combobox(
                body, textvariable=self.type_var, state="readonly",
                values=list(TYPE_LABELS.values()))),
            ("Времетраене (напр. 2ч 30м):",
             ttk.Entry(body, textvariable=self.duration_var)),
            ("Количество:", ttk.Entry(body, textvariable=self.quantity_var)),
            ("Себестойност за бройка:", ttk.Entry(body, textvariable=self.cost_var)),
            ("Цена за бройка:", ttk.Entry(body, textvariable=self.price_var)),
            ("Бележка:", ttk.Entry(body, textvariable=self.note_var)),
        )
        for index, (label, widget) in enumerate(rows):
            ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", **pad)
            widget.grid(row=index, column=1, sticky="ew", **pad)
        self.first_widget = rows[0][1]

        self.error_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.error_var, style="Muted.TLabel",
                  wraplength=380, justify="left").grid(
            row=len(rows), column=0, columnspan=2, sticky="w", padx=10)

        buttons = ttk.Frame(body)
        buttons.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e",
                     padx=10, pady=(12, 0))
        ttk.Button(buttons, text="Отказ", command=self._cancel).pack(
            side="right", padx=(8, 0))
        ttk.Button(buttons, text="Запиши", style="Accent.TButton",
                   command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._save())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.grab_set()
        self.first_widget.focus_set()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            self.error_var.set("⚠ Името е задължително.")
            self.bell()
            return
        duration = 0
        text = self.duration_var.get().strip()
        if text:
            try:
                duration = parse_duration(text)
            except ValueError as exc:
                self.error_var.set(f"⚠ {exc}")
                self.bell()
                return
        product = self.original or Product()
        product.name = name
        product.quality = self.quality_var.get().strip()
        product.category = self.category_var.get().strip()
        product.default_type = label_to_type(self.type_var.get())
        product.default_duration_sec = duration
        product.default_quantity = _as_float(self.quantity_var.get())
        product.unit_cost = _as_float(self.cost_var.get())
        product.unit_price = _as_float(self.price_var.get())
        product.note = self.note_var.get().strip()
        self.result = product
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


def _num(value: float) -> str:
    if not value:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _as_float(text: str) -> float:
    try:
        return float(str(text).strip().replace(",", ".") or 0)
    except ValueError:
        return 0.0
