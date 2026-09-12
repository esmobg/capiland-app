"""Каталог с продукти.

Приложението не идва с готови времена за производство — те зависят от
нивото на фабриката ти в играта. Затова каталогът тръгва само с имена и
категории, а времената, количествата и цените се запомнят автоматично от
това, което въвеждаш (виж ``Database.remember_product``).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .db import Database
from .models import Product, TimerType

# Отраслите, които самата игра назовава на страницата „За Kapilands?“:
# говеда, агрокултура, високотехнологична продукция, мода.
CATEGORIES: tuple[str, ...] = (
    "Суровини",
    "Агрокултура",
    "Животновъдство",
    "Високи технологии",
    "Мода",
    "Строителни",
    "Наука",
    "Друго",
)

# Начални имена за удобство — всички полета се редактират от раздела „Каталог“.
SEED_PRODUCTS: tuple[tuple[str, str], ...] = (
    ("Пшеница", "Агрокултура"),
    ("Царевица", "Агрокултура"),
    ("Захарно цвекло", "Агрокултура"),
    ("Брашно", "Агрокултура"),
    ("Хляб", "Агрокултура"),
    ("Захар", "Агрокултура"),
    ("Говеда", "Животновъдство"),
    ("Мляко", "Животновъдство"),
    ("Сирене", "Животновъдство"),
    ("Месо", "Животновъдство"),
    ("Вълна", "Животновъдство"),
    ("Дървен материал", "Суровини"),
    ("Желязна руда", "Суровини"),
    ("Въглища", "Суровини"),
    ("Нефт", "Суровини"),
    ("Вода", "Суровини"),
    ("Дъски", "Строителни"),
    ("Тухли", "Строителни"),
    ("Цимент", "Строителни"),
    ("Стъкло", "Строителни"),
    ("Стомана", "Високи технологии"),
    ("Пластмаса", "Високи технологии"),
    ("Ток", "Високи технологии"),
    ("Електроника", "Високи технологии"),
    ("Хартия", "Високи технологии"),
    ("Плат", "Мода"),
    ("Прежда", "Мода"),
    ("Дрехи", "Мода"),
    ("Обувки", "Мода"),
    ("Кожа", "Мода"),
)

_SEED_FLAG = "__seeded__"

CSV_COLUMNS = (
    "name", "quality", "category", "default_type", "default_duration_sec",
    "default_quantity", "unit_cost", "unit_price", "note",
)


def ensure_seed(db: Database) -> int:
    """Попълва началните имена само при първо стартиране. Връща броя добавени."""
    if db.list_products():
        return 0
    added = 0
    for name, category in SEED_PRODUCTS:
        db.upsert_product(Product(
            name=name,
            category=category,
            default_type=TimerType.PRODUCTION.value,
        ))
        added += 1
    return added


def product_names(db: Database) -> list[str]:
    return [p.name for p in db.list_products()]


def export_csv(db: Database, path: str | Path) -> int:
    """Записва каталога в CSV (с BOM, за да се отваря правилно в Excel)."""
    products = db.list_products()
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for p in products:
            writer.writerow([getattr(p, column) for column in CSV_COLUMNS])
    return len(products)


def import_csv(db: Database, path: str | Path) -> int:
    """Чете каталог от CSV. Съществуващите продукти се обновяват по име."""
    count = 0
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            quality = (row.get("quality") or "").strip()
            product = (db.get_product(name, quality)
                       or Product(name=name, quality=quality))
            product.name = name
            product.quality = quality
            product.category = (row.get("category") or product.category).strip()
            product.default_type = (row.get("default_type")
                                    or product.default_type).strip()
            product.default_duration_sec = _as_int(
                row.get("default_duration_sec"), product.default_duration_sec)
            product.default_quantity = _as_float(
                row.get("default_quantity"), product.default_quantity)
            product.unit_cost = _as_float(row.get("unit_cost"), product.unit_cost)
            product.unit_price = _as_float(row.get("unit_price"), product.unit_price)
            product.note = (row.get("note") or product.note).strip()
            db.upsert_product(product)
            count += 1
    return count


def _as_int(value, default: int) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
