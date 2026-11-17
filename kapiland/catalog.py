"""Каталог с продукти.

Приложението не идва с готови времена за производство — те зависят от
нивото на фабриката ти в играта. Затова каталогът тръгва само с имена и
категории, а времената, количествата и цените се запомнят автоматично от
това, което въвеждаш (виж ``Database.remember_product``).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

from . import gamedata
from .db import Database
from .models import TYPE_ORDER, Product, TimerType

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
    # От списъка „Производство“ на играча:
    ("Сладоледена фабрика", "Агрокултура"),
    ("Фабрика за бижута", "Бижута"),
    ("Фабрика за играчки", "Друго"),
    ("Фабрика за мебели", "Мебели"),
    ("Фабрика за напитки", "Агрокултура"),
    ("Фабрика за коли", "Автомобили"),
    ("Месарница", "Животновъдство"),
    ("Фабрика", "Строителни"),
    ("Кладенец", "Суровини"),
    ("ТВ станция", "Друго"),
    ("Електроцентрала", "Енергия"),
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
    "химическа": "Химически фабрики",
    "сладоледени фабрики": "Сладоледена фабрика",
    "фабрики за бижута": "Фабрика за бижута",
    "фабрики за играчки": "Фабрика за играчки",
    "фабрики за мебели": "Фабрика за мебели",
    "мебелна фабрика": "Фабрика за мебели",
    "мебелни фабрики": "Фабрика за мебели",
    "фабрики за напитки": "Фабрика за напитки",
    "фабрики за коли": "Фабрика за коли",
    "автомобилна фабрика": "Фабрика за коли",
    "автомобилни фабрики": "Фабрика за коли",
    "месарници": "Месарница",
    "фабрики": "Фабрика",
    "кладенци": "Кладенец",
    "тиви станция": "ТВ станция",
    "тиви станции": "ТВ станция",
    "тв станции": "ТВ станция",
    "телевизионна станция": "ТВ станция",
    "елцентрала": "Електроцентрала",
    "елцентрали": "Електроцентрала",
    "електроцентрали": "Електроцентрала",
}

# Отрасъл по наука — за продукт, чиято сграда не е известна.
_CATEGORY_BY_RESEARCH: dict[str, str] = {
    "Химическа": "Химия",
    "Храна": "Агрокултура",
    "Техническа": "Високи технологии",
    "Добитък и плантация": "Агрокултура",
    "Мини и кладенец": "Суровини",
    "Медийна": "Друго",
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


def known_product_names() -> list[str]:
    """Продуктите, които приложението знае само: от бележките и от двата списъка."""
    names: dict[str, str] = {}
    for name in list(product_names_v2()) + list(gamedata.all_product_names()):
        names.setdefault(name.lower(), name)
    return list(names.values())


def find_product(text: str, extra: Iterable[str] = ()) -> str | None:
    """Разпознава продукт, включително членуван: ``Токът`` → ``Ток``."""
    wanted = _norm(text)
    if not wanted:
        return None
    alias = gamedata.PRODUCT_ALIASES.get(wanted)
    if alias:
        return alias
    names = list(dict.fromkeys(known_product_names() + list(extra)))
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


def production_building(product: str) -> str:
    """Сградата, в която се произвежда продуктът според списъка „Производство“."""
    group = gamedata.production_group_for_product(product)
    if not group:
        return ""
    return find_building(group) or group


def buildings_for_product(product: str, kind: str = TimerType.PRODUCTION.value) -> list[str]:
    """Известните сгради за продукта — първо тази, която отговаря на дейността.

    При продажба първо е сградата от бележките (магазинът), иначе — фабриката.
    """
    made = production_building(product)
    noted = building_for_product(product)
    order = [noted, made] if kind == TimerType.SALE.value else [made, noted]
    return [b for b in dict.fromkeys(order) if b]


def category_for_product(product: str) -> str:
    """Отрасъл: от бележките, после от сградата, после от науката."""
    for name, category, _b in PRODUCTS_V2:
        if name.lower() == (product or "").lower():
            return category
    building = production_building(product)
    for name, category in BUILDINGS:
        if name == building:
            return category
    return _CATEGORY_BY_RESEARCH.get(gamedata.research_for_product(product), "")


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


def _products_by_name(db: Database) -> dict[str, list[Product]]:
    found: dict[str, list[Product]] = {}
    for product in db.list_products():
        found.setdefault(product.name.lower(), []).append(product)
    return found


def upgrade_catalog_v3(db: Database) -> int:
    """Еднократно добавя продуктите от списъците „Изследвания“ и „Производство“.

    Като v2: нищо попълнено не се презаписва — на съществуващ продукт (във
    всяко качество) се попълват само празните категория, сграда и наука.
    """
    if db.get_meta("catalog_v3") == "1":
        return 0
    existing = _products_by_name(db)
    added = 0
    for name in gamedata.all_product_names():
        values = {
            "category": category_for_product(name),
            "building": production_building(name),
            "research": gamedata.research_for_product(name),
        }
        found = existing.get(name.lower())
        if not found:
            db.upsert_product(Product(name=name, default_type=TimerType.PRODUCTION.value,
                                      **values))
            added += 1
            continue
        for product in found:
            changed = False
            for field_name, value in values.items():
                if value and not getattr(product, field_name).strip():
                    setattr(product, field_name, value)
                    changed = True
            if changed:
                db.upsert_product(product)
    db.set_meta("catalog_v3", "1")
    return added


# ------------------------------------------------- списъци в текстов вид

def read_text(path: str | Path) -> str:
    """Текстът на файла: UTF-8 (и с BOM), иначе Windows-1251."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251")  # стар Бележник на Windows


def _kind_from_name(path: str | Path) -> str | None:
    stem = Path(path).stem.lower()
    if "изследв" in stem or "наук" in stem or "research" in stem:
        return gamedata.RESEARCH
    if "производ" in stem or "production" in stem:
        return gamedata.PRODUCTION
    return None


def import_lists(db: Database, path: str | Path) -> dict:
    """Внася списък „Изследвания“ или „Производство“ от текстов файл.

    Видът се познава по заглавния ред, а ако го няма — по името на файла.
    Потребителят изрично дава файла, затова науката или сградата на изброените
    продукти се **презаписва**; времена, количества и цени не се пипат.
    Връща {"kind", "groups", "products", "added"}.
    """
    kind, groups = gamedata.parse_groups(read_text(path))
    if kind is None:
        kind = _kind_from_name(path)
    if kind is None:
        raise ValueError(
            "не е ясно дали е списък с изследвания или с производство. Първият ред "
            f"трябва да е „{gamedata.HEADERS[gamedata.RESEARCH]}“ или "
            f"„{gamedata.HEADERS[gamedata.PRODUCTION]}“.")
    field_name = "research" if kind == gamedata.RESEARCH else "building"

    existing = _products_by_name(db)
    seen: set[str] = set()
    added = 0
    for group, products in groups.items():
        value = group if kind == gamedata.RESEARCH else (find_building(group) or group)
        for name in products:
            seen.add(name.lower())
            found = existing.get(name.lower())
            if not found:
                product = Product(name=name, category=category_for_product(name),
                                  default_type=TimerType.PRODUCTION.value)
                setattr(product, field_name, value)
                db.upsert_product(product)
                existing[name.lower()] = [product]
                added += 1
                continue
            for product in found:
                setattr(product, field_name, value)
                if not product.category.strip():
                    product.category = category_for_product(name)
                db.upsert_product(product)
    return {"kind": kind, "groups": len(groups), "products": len(seen), "added": added}


def list_groups(db: Database, kind: str) -> dict[str, list[str]]:
    """Каталогът, подреден в групи по наука или по сграда."""
    field_name = "research" if kind == gamedata.RESEARCH else "building"
    groups: dict[str, list[str]] = {}
    if kind == gamedata.RESEARCH:
        for branch in gamedata.RESEARCH_BRANCHES:
            groups[branch] = []
    for product in db.list_products():
        group = getattr(product, field_name).strip()
        if not group:
            continue
        key = next((g for g in groups if g.lower() == group.lower()), group)
        names = groups.setdefault(key, [])
        if product.name.lower() not in (n.lower() for n in names):
            names.append(product.name)
    return groups


def export_lists(db: Database, folder: str | Path) -> dict[str, int]:
    """Записва ``Изследвания.txt`` и ``Производство.txt`` в същия формат.

    Връща броя продукти във всеки файл: {"research": …, "production": …}.
    """
    folder = Path(folder)
    counts: dict[str, int] = {}
    for kind in (gamedata.RESEARCH, gamedata.PRODUCTION):
        groups = list_groups(db, kind)
        text = gamedata.format_groups(kind, groups)
        (folder / gamedata.FILE_NAMES[kind]).write_text(text, encoding="utf-8-sig")
        counts[kind] = sum(len(p) for p in groups.values())
    return counts

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
    "name", "quality", "category", "building", "research", "default_type",
    "default_duration_sec", "default_quantity", "unit_cost", "unit_price", "note",
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
    """Записва каталога в CSV — заедно с работещите таймери и компаниите.

    Целият файл се прави от ``transfer.export_file``; тук се връща само
    броят на продуктите.
    """
    from . import transfer

    return transfer.export_file(db, path)["products"]


def import_csv(db: Database, path: str | Path) -> int:
    """Чете CSV от ``export_csv``. Съществуващите продукти се обновяват по име.

    Таймерите и компаниите във файла също се внасят (``transfer.import_file``).
    Връща броя на продуктите.
    """
    from . import transfer

    return transfer.import_file(db, path)["products"]


def import_product_row(db: Database, row: dict) -> bool:
    """Един ред от каталога (колона → стойност). False, ако няма име."""
    name = (row.get("name") or "").strip()
    if not name:
        return False
    quality = (row.get("quality") or "").strip()
    product = db.get_product(name, quality) or Product(name=name, quality=quality)
    product.name = name
    product.quality = quality
    product.category = (row.get("category") or product.category).strip()
    product.building = (row.get("building") or product.building).strip()
    product.research = (row.get("research") or product.research).strip()
    kind = (row.get("default_type") or product.default_type).strip()
    product.default_type = kind if kind in TYPE_ORDER else TimerType.PRODUCTION.value
    product.default_duration_sec = max(0, as_int(
        row.get("default_duration_sec"), product.default_duration_sec))
    product.default_quantity = as_float(row.get("default_quantity"), product.default_quantity)
    product.unit_cost = as_float(row.get("unit_cost"), product.unit_cost)
    product.unit_price = as_float(row.get("unit_price"), product.unit_price)
    product.note = (row.get("note") or product.note).strip()
    db.upsert_product(product)
    return True


def as_float(value, default: float) -> float:
    """Число от клетка на CSV; приема и десетична запетая (Excel на български)."""
    try:
        number = float(str(value).replace("\u00a0", "").replace(" ", "")
                       .replace(",", "."))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_int(value, default: int) -> int:
    number = as_float(value, float("nan"))
    return default if math.isnan(number) else int(number)
