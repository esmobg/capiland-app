"""Кой продукт в коя наука се изследва и в коя сграда се произвежда.

Двата списъка са вградени дословно така, както играчът си ги води в
бележник (``Изследвания.txt`` и ``Производство.txt``), за да ги има на всеки
компютър без да се носят файлове. Същият формат се чете и пише и от раздела
„Каталог“ (``catalog.import_lists`` / ``catalog.export_lists``).

Формат::

    изследват се продуктите в      ← заглавие (по него се познава видът)

    химическа                      ← група: наука или сграда
    паста за зъби                  ← продукти, по един на ред
    перилни препарати

    храна                          ← празен ред започва нова група
    ...

Модулът е без база и без интерфейс.
"""

from __future__ import annotations

from functools import lru_cache

RESEARCH = "research"
PRODUCTION = "production"

HEADERS: dict[str, str] = {
    RESEARCH: "изследват се продуктите в",
    PRODUCTION: "продуктите се произвеждат в",
}

FILE_NAMES: dict[str, str] = {
    RESEARCH: "Изследвания.txt",
    PRODUCTION: "Производство.txt",
}

RESEARCH_TEXT = """\
изследват се продуктите в

химическа
паста за зъби
перилни препарати
шампоани
лосиони
парфюми
сребърни огърлици
диамантени пръстени
златни огърлици
златни часовници
играчки
дървени играчки
плюшени играчки
джинси
кожени якета
кожени ръкавици
кожа
пуловери
обувки
текстил
стомана
силиций
стъкло
пластмаса
химикали
бензин

храна
сладолед лимон
сладолед шоколад
сладолед портокал
сладолед кафе
сладолед ягода
сладолед банан
портокалов сок
ябълков сок
опаковано какао
какао на прах
вина
капи кола
бири
захар
шоколадчета
брашно
хляб
бисквити
кафе на прах
сладки
салама
свинско месо
мляно месо
говеждо месо
храна за животни
агнешко

техническа
маси
гардероби
легла
столове
компютри
телевизори
монитори
принтери
е компоненти
процесори
автомобили
мотори
кабриолети
гуми
двигатели
купета

добитък и плантация
лимони
портокали
банани
ягоди
круши
ябълки
грозде
вълна
прасета
добитък
млека
кокошки
яйца
агнета
захарна тръстика
семена
каучук
картофи
кафе на зърна
какао
царевица
дърва
памук

мини и кладенец
нефт
кварц
желязо
въглища
сребро
минерали
злато
диаманти

медийна
реклами

производствени сгради
"""

PRODUCTION_TEXT = """\
продуктите се произвеждат в

мина
камъни
диаманти
въглища
железа
сребро
злато
минерали
кварц

сладоледена фабрика
сладоледи

химическа
лосиони
шампоани
перилни препарати
паста за зъби
парфюми

фабрика за бижута
сребърни огърлици
диамантени пръстени
златни огърлици
златни часовници

фабрика за играчки
играчки

фабрика за мебели
гардероби
столове
легла
маси

фабрика за напитки
портокалов сок
ябълков сок
опаковано какао
капи кола
вина
бири

фабрика за храна
какао на прах
кафе на прах
захар
шоколадчета
сладки
бисквити
хляб
брашно

плодова плантация
лимони
круши
ябълки
ягоди
грозде
портокали
банани

фабрика за електроника
е компоненти
компютри
монитори
принтери
телевизори
процесори

фабрика за коли
гуми
мотори
двигатели
купета
кабриолети
автомобили

текстилна фабрика
текстил
кожа
джинси
обувки
пуловери
кожени ръкавици
кожени якета

месарница
храна за животни
свинско месо
говеждо месо
мляно месо
салама
агнешко

ферма
прасета
добитък
вълна
агнета
млека
яйца
кокошки

плантация
захарна тръстика
семена
каучук
картофи
кафе на зърна
какао
дърва
царевица
памук

фабрика
силиций
стомана
стъкло
пластмаса
химикали
бензин

кладенец
нефт
вода

тиви станция
реклами

елцентрала
ток
"""

# Едно и също нещо, писано различно в двата списъка или в стария каталог.
PRODUCT_ALIASES: dict[str, str] = {
    "железа": "Желязо",
    "е компоненти": "Компоненти",
    "е-компоненти": "Компоненти",
    "електронни компоненти": "Компоненти",
}

# Видове от един общ продукт: „Сладолед лимон“ се прави там, където „Сладоледи“.
_FAMILIES: dict[str, str] = {
    "сладолед": "сладоледи",
    "играчки": "играчки",
}


# ----------------------------------------------------------------- помощни

def _key(text: str) -> str:
    return " ".join((text or "").lower().split())


def _capitalize(text: str) -> str:
    text = " ".join((text or "").split())
    return text[:1].upper() + text[1:] if text else text


def normalize_product(name: str) -> str:
    """``  железа `` → ``Желязо``; ``капи кола`` → ``Капи кола``."""
    key = _key(name)
    return PRODUCT_ALIASES.get(key) or _capitalize(name)


def normalize_group(name: str) -> str:
    return _capitalize(name)


def detect_kind(line: str) -> str | None:
    """Видът по заглавния ред, или ``None`` ако редът не е заглавие."""
    key = _key(line).rstrip(" :")
    if not key:
        return None
    for kind, header in HEADERS.items():
        if key == header:
            return kind
    if "изследва" in key and "продукт" in key:
        return RESEARCH
    if "произвежда" in key and "продукт" in key:
        return PRODUCTION
    return None


# ------------------------------------------------------------- чете и пише

def parse_groups(text: str) -> tuple[str | None, dict[str, list[str]]]:
    """Разчита списъка. Връща (вид, {група: [продукти]}).

    Видът е ``None``, ако няма заглавен ред. Група без продукти се пази
    празна (напр. „Производствени сгради“). Повторенията се махат.
    """
    kind: str | None = None
    groups: dict[str, list[str]] = {}
    current: str | None = None
    first = True
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if first and line:
            first = False
            kind = detect_kind(line)
            if kind is not None:
                continue
        if not line:
            current = None
            continue
        if current is None:
            current = normalize_group(line)
            existing = next((g for g in groups if g.lower() == current.lower()), None)
            if existing is None:
                groups[current] = []
            else:
                current = existing
            continue
        product = normalize_product(line)
        if product.lower() not in (p.lower() for p in groups[current]):
            groups[current].append(product)
    return kind, groups


def format_groups(kind: str, groups: dict[str, list[str]]) -> str:
    """Обратното на ``parse_groups`` — същият формат като бележника."""
    lines = [HEADERS[kind], ""]
    for group, products in groups.items():
        lines.append(group)
        lines.extend(products)
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------- вградените

@lru_cache(maxsize=None)
def research_groups() -> dict[str, tuple[str, ...]]:
    _kind, groups = parse_groups(RESEARCH_TEXT)
    return {g: tuple(p) for g, p in groups.items()}


@lru_cache(maxsize=None)
def production_groups() -> dict[str, tuple[str, ...]]:
    _kind, groups = parse_groups(PRODUCTION_TEXT)
    return {g: tuple(p) for g, p in groups.items()}


def _index(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for group, products in groups.items():
        for product in products:
            index.setdefault(product.lower(), group)
    return index


@lru_cache(maxsize=None)
def _research_index() -> dict[str, str]:
    return _index(research_groups())


@lru_cache(maxsize=None)
def _production_index() -> dict[str, str]:
    return _index(production_groups())


RESEARCH_BRANCHES: tuple[str, ...] = tuple(research_groups())


def research_for_product(name: str) -> str:
    """Науката, в която се изследва продуктът, или празно."""
    return _research_index().get(normalize_product(name).lower(), "")


def production_group_for_product(name: str) -> str:
    """Сградата от списъка „Производство“ (както е писана там), или празно."""
    index = _production_index()
    key = normalize_product(name).lower()
    if key in index:
        return index[key]
    for word in key.split():
        family = _FAMILIES.get(word)
        if family and family in index:
            return index[family]
    return ""


@lru_cache(maxsize=None)
def all_product_names() -> tuple[str, ...]:
    """Всички продукти от двата списъка, без повторения, в реда на списъците."""
    names: dict[str, str] = {}
    for groups in (research_groups(), production_groups()):
        for products in groups.values():
            for product in products:
                names.setdefault(product.lower(), product)
    return tuple(names.values())
