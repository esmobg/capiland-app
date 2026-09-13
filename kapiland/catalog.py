"""Каталог с продукти.

Приложението не идва с готови времена за производство — те зависят от
нивото на фабриката ти в играта. Затова каталогът тръгва само с имена и
категории, а времената, количествата и цените се запомнят автоматично от
това, което въвеждаш (виж ``Database.remember_product``).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

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
    "Мебели",
    "Химия",
    "Енергия",
    "Автомобили",
    "Бижута",
    "Строителни",
    "Наука",
    "Друго",
)

# ------------------------------------------------------------------ светове
# „Немска двойка“ = втори свят на немския сървър.

WORLD_COUNTRIES: tuple[str, ...] = (
    "Българска", "Немска", "Английска", "Холандска", "Френска",
)
WORLD_ORDINALS: tuple[str, ...] = (
    "единица", "двойка", "тройка", "четворка", "петица",
    "шестица", "седмица", "осмица", "деветка", "десетка",
)
# Световете, които се срещат в бележките на играча — за падащите списъци.
KNOWN_WORLDS: tuple[str, ...] = (
    "Българска единица",
    "Немска единица", "Немска двойка", "Немска тройка",
    "Немска четворка", "Немска петица", "Немска шестица",
    "Английска единица", "Английска двойка",
    "Холандска единица",
    "Френска единица",
)

_WORLD_RE = re.compile(
    r"^\s*(" + "|".join(WORLD_COUNTRIES) + r")\s+(" + "|".join(WORLD_ORDINALS) + r")\b",
    re.IGNORECASE)


def world_name(country: str, number: int) -> str:
    return f"{country.capitalize()} {WORLD_ORDINALS[number - 1]}"


def parse_world(text: str) -> tuple[str, str] | None:
    """``Немска двойка – Тау`` → (``Немска двойка``, ``– Тау``)."""
    match = _WORLD_RE.match(text or "")
    if not match:
        return None
    name = f"{match.group(1).capitalize()} {match.group(2).lower()}"
    return name, text[match.end():]


# ------------------------------------------------------------------ сгради
# Точно както се пишат в играта; вторите имена са форми, срещани в бележките.

BUILDINGS: tuple[tuple[str, str], ...] = (
    ("Фабрики за електроника", "Високи технологии"),
    ("Фабрики за храна", "Агрокултура"),
    ("Химически фабрики", "Химия"),
    ("Текстилни фабрики", "Мода"),
    ("Плантация", "Агрокултура"),
    ("Плодова плантация", "Агрокултура"),
    ("Ферма", "Животновъдство"),
    ("Мини", "Суровини"),
    ("Бензиностанции", "Химия"),
    ("Магазини за електроника", "Високи технологии"),
    ("Мебелни магазини", "Мебели"),
    ("Текстилни магазини", "Мода"),
    ("Аптека", "Химия"),
    ("Автосалон", "Автомобили"),
    ("Бижутерия", "Бижута"),
)
_BUILDING_ALIASES: dict[str, str] = {
    "фабрика за електроника": "Фабрики за електроника",
    "фабрика за храна": "Фабрики за храна",
    "химическа фабрика": "Химически фабрики",
    "текстилна фабрика": "Текстилни фабрики",
    "плантации": "Плантация",
    "плодови плантации": "Плодова плантация",
    "ферми": "Ферма",
    "мина": "Мини",
    "бензиностанция": "Бензиностанции",
    "магазин за електроника": "Магазини за електроника",
    "мебелен магазин": "Мебелни магазини",
    "текстилен магазин": "Текстилни магазини",
    "аптеки": "Аптека",
    "автосалони": "Автосалон",
    "бижутерии": "Бижутерия",
}

# ----------------------------------------------------------------- продукти
# (име, категория, сграда). Сградата е попълнена само където бележките на
# играча показват в коя сграда се прави или продава — останалите не се гадаят.

PRODUCTS_V2: tuple[tuple[str, str, str], ...] = (
    ("Бензин", "Химия", "Химически фабрики"),
    ("Газ", "Енергия", ""),
    ("Ток", "Енергия", ""),
    ("Минерали", "Суровини", ""),
    ("Вода", "Суровини", ""),
    ("Сребро", "Суровини", "Мини"),
    ("Захарна тръстика", "Агрокултура", "Плантация"),
    ("Каучук", "Агрокултура", "Плантация"),
    ("Банани", "Агрокултура", "Плодова плантация"),
    ("Рози", "Агрокултура", ""),
    ("Свинско месо", "Животновъдство", ""),
    ("Компютри", "Високи технологии", "Фабрики за електроника"),
    ("Компоненти", "Високи технологии", "Фабрики за електроника"),
    ("Телевизори", "Високи технологии", "Магазини за електроника"),
    ("Двигатели", "Автомобили", ""),
    ("Мотори", "Автомобили", "Автосалон"),
    ("Автомобили", "Автомобили", "Автосалон"),
    ("Гардероби", "Мебели", "Мебелни магазини"),
    ("Легла", "Мебели", ""),
    ("Мебели", "Мебели", ""),
    ("Парфюми", "Химия", "Аптека"),
    ("Кожа", "Мода", "Текстилни фабрики"),
    ("Текстил", "Мода", "Текстилни фабрики"),
    ("Кожени якета", "Мода", "Текстилни магазини"),
    ("Кожени ръкавици", "Мода", ""),
    ("Джинси", "Мода", ""),
    ("Пръстени", "Бижута", "Бижутерия"),
    ("Сребърни огърлици", "Бижута", ""),
)

# Членувани и множествени форми, които се срещат в бележките.
_ARTICLE_SUFFIXES = ("ите", "ът", "ят", "та", "то", "те", "а", "я")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def building_names() -> list[str]:
    return [name for name, _category in BUILDINGS]


def find_building(text: str) -> str | None:
    """Разпознава сграда в началото на текста (``Строят се бензиностанции``)."""
    wanted = _norm(text)
    if not wanted:
        return None
    candidates = [(name.lower(), name) for name, _c in BUILDINGS]
    candidates += list(_BUILDING_ALIASES.items())
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)  # първо най-дългото
    for key, canonical in candidates:
        if wanted == key or wanted.startswith(key + " ") or wanted.startswith(key + ","):
            return canonical
    return None


def product_names_v2() -> list[str]:
    return [name for name, _c, _b in PRODUCTS_V2]


def find_product(text: str, extra: Iterable[str] = ()) -> str | None:
    """Разпознава продукт, включително членуван: ``Токът`` → ``Ток``."""
    wanted = _norm(text)
    if not wanted:
        return None
    names = list(dict.fromkeys(list(product_names_v2()) + list(extra)))
    by_key = {_norm(name): name for name in names}
    if wanted in by_key:
        return by_key[wanted]
    for suffix in _ARTICLE_SUFFIXES:
        if wanted.endswith(suffix) and len(wanted) > len(suffix) + 2:
            stem = wanted[: -len(suffix)]
            if stem in by_key:
                return by_key[stem]
            for key, name in by_key.items():
                if key.endswith(("и", "а", "я")) and key[:-1] == stem:
                    return name  # „Парфюмите“ → „парфюм“ + „и“
    return None


def building_for_product(product: str) -> str:
    for name, _category, building in PRODUCTS_V2:
        if name.lower() == (product or "").lower():
            return building
    return ""


def upgrade_catalog_v2(db: Database) -> int:
    """Еднократно добавя сградите и продуктите от бележките на играча.

    Не презаписва нищо, което потребителят вече е попълнил: на съществуващ
    продукт се попълват само празните категория и сграда.
    """
    if db.get_meta("catalog_v2") == "1":
        return 0
    added = 0
    for name, category, building in PRODUCTS_V2:
        product = db.get_product(name)
        if product is None:
            db.upsert_product(Product(name=name, category=category, building=building,
                                      default_type=TimerType.PRODUCTION.value))
            added += 1
            continue
        changed = False
        if not product.category.strip():
            product.category = category
            changed = True
        if not product.building.strip() and building:
            product.building = building
            changed = True
        if changed:
            db.upsert_product(product)
    db.set_meta("catalog_v2", "1")
    return added

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
    "name", "quality", "category", "building", "default_type", "default_duration_sec",
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
            product.building = (row.get("building") or product.building).strip()
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
