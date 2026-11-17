"""Пренос между компютри с един CSV файл: каталог, таймери и компании.

Файлът е този от „Изнеси в CSV“. Започва с каталога — така, както го четат и
по-старите версии — и продължава с две части, чиито редове са с празна първа
колона::

    name;quality;category;…                      каталогът
    Бензин;;Химия;…
    ;#timers;product;quality;type;…;end_at;…     заглавие на частта с таймерите
    ;timer;Бензин;Q2;production;…;1800025200;…
    ;#accounts;world;name;owner;buildings;note   заглавие на частта с компаниите
    ;account;Българска единица;Алфа маркет 7;…

Версия 2.1 прескача всеки ред без име на продукт, затова чете новия файл като
обикновен каталог. Обратното също работи: файл без „#timers“ е само каталог,
а ``import_summary`` казва изрично, че в него няма таймери.

Часовете са UTC epoch секунди — същият момент на всеки компютър, независимо от
часовата зона. Изнасят се само работещите таймери; историята не се пренася.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from . import catalog
from .db import Database
from .models import TYPE_ORDER, Account, Timer, TimerStatus, TimerType
from .timeutil import now as time_now

TIMER_MARK = "#timers"
TIMER_TAG = "timer"
ACCOUNT_MARK = "#accounts"
ACCOUNT_TAG = "account"

# Колона във файла → поле на Timer.
TIMER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("product", "product"),
    ("quality", "quality"),
    ("type", "type"),
    ("quantity", "quantity"),
    ("company", "line"),
    ("world", "world"),
    ("building", "building"),
    ("start_at", "start_at"),
    ("end_at", "end_at"),
    ("duration_sec", "duration_sec"),
    ("repeat_enabled", "repeat_enabled"),
    ("cycles_planned", "cycles_planned"),
    ("cycle_no", "cycle_no"),
    ("prewarn_sec", "prewarn_sec"),
    ("note", "note"),
)
ACCOUNT_COLUMNS: tuple[str, ...] = ("world", "name", "owner", "buildings", "note")


def timer_key(timer: Timer) -> tuple:
    """По това се познава, че таймерът вече го има (и не се внася втори път)."""
    return (timer.world.strip().lower(), timer.line.strip().lower(),
            timer.product.strip().lower(), timer.quality.strip().lower(),
            timer.type, int(round(timer.end_at)))


# ------------------------------------------------------------------ износ

def _number(value: float):
    """Цяло число без „.0“ — Excel не го превръща в „1,8E+09“."""
    value = float(value)
    return int(value) if value.is_integer() else round(value, 3)


def export_file(db: Database, path: str | Path) -> dict[str, int]:
    """Записва каталога, работещите таймери и компаниите.

    С BOM, за да се отваря правилно в Excel. Връща броя на всяко:
    {"products": …, "timers": …, "accounts": …}.
    """
    products = db.list_products()
    timers = db.list_timers(TimerStatus.RUNNING.value)
    accounts = db.list_accounts()
    numeric = {"quantity", "start_at", "end_at"}
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(catalog.CSV_COLUMNS)
        for product in products:
            writer.writerow([getattr(product, column) for column in catalog.CSV_COLUMNS])

        writer.writerow(["", TIMER_MARK] + [column for column, _field in TIMER_COLUMNS])
        for timer in timers:
            writer.writerow(["", TIMER_TAG] + [
                _number(getattr(timer, name)) if column in numeric else getattr(timer, name)
                for column, name in TIMER_COLUMNS])

        writer.writerow(["", ACCOUNT_MARK] + list(ACCOUNT_COLUMNS))
        for account in accounts:
            writer.writerow(["", ACCOUNT_TAG] + [getattr(account, c) for c in ACCOUNT_COLUMNS])
    return {"products": len(products), "timers": len(timers), "accounts": len(accounts)}


# ------------------------------------------------------------------- внос

def _rows(path: str | Path) -> list[list[str]]:
    text = catalog.read_text(path)
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _as_dict(columns: list[str], cells: list[str]) -> dict[str, str]:
    return {column: (cells[index] if index < len(cells) else "")
            for index, column in enumerate(columns) if column}


def _timer_from_row(row: dict[str, str]) -> Timer | None:
    """Таймер от ред на файла; None, ако няма разбираем краен час."""
    end_at = catalog.as_float(row.get("end_at"), 0.0)
    if end_at <= 0:
        return None
    kind = (row.get("type") or "").strip()
    duration = max(0, catalog.as_int(row.get("duration_sec"), 0))
    start_at = catalog.as_float(row.get("start_at"), 0.0)
    if start_at <= 0 or start_at > end_at:
        start_at = end_at - duration
    return Timer(
        product=(row.get("product") or "").strip(),
        quality=(row.get("quality") or "").strip(),
        type=kind if kind in TYPE_ORDER else TimerType.PRODUCTION.value,
        quantity=max(0.0, catalog.as_float(row.get("quantity"), 0.0)),
        line=(row.get("company") or "").strip(),
        world=(row.get("world") or "").strip(),
        building=(row.get("building") or "").strip(),
        start_at=start_at,
        end_at=end_at,
        duration_sec=duration,
        status=TimerStatus.RUNNING.value,
        repeat_enabled=1 if catalog.as_int(row.get("repeat_enabled"), 0) else 0,
        cycles_planned=max(0, catalog.as_int(row.get("cycles_planned"), 0)),
        cycle_no=max(1, catalog.as_int(row.get("cycle_no"), 1)),
        prewarn_sec=max(0, catalog.as_int(row.get("prewarn_sec"), 0)),
        note=(row.get("note") or "").strip(),
    )


def import_file(db: Database, path: str | Path, now: float | None = None) -> dict:
    """Чете файл от ``export_file`` (или стар каталог само с продукти).

    Продуктите се обновяват по име и качество, компаниите се допълват, а
    таймерите се добавят към работещите. Таймер, който вече го има, не се
    внася втори път. Отминалите идват като „пропуснати“ — без известие за
    всеки поотделно, както при вноса на бележки.

    Връща {"products", "timers", "timers_existing", "timers_past",
    "timers_bad", "accounts", "has_timers"}.
    Хвърля ``ValueError``, ако файлът не е каталог на приложението.
    """
    ts = time_now() if now is None else now
    rows = _rows(path)
    header = [cell.strip().lower() for cell in rows[0]] if rows else []
    if "name" not in header:
        raise ValueError(
            "това не е файл от „Изнеси в CSV“ на Kapilands Таймер — на първия ред "
            "липсва колоната „name“.")

    result = {"products": 0, "timers": 0, "timers_existing": 0, "timers_past": 0,
              "timers_bad": 0, "accounts": 0, "has_timers": False}
    known = {timer_key(t) for t in db.list_timers(TimerStatus.RUNNING.value)}
    section, columns = "", header
    for cells in rows[1:]:
        if cells[0].strip():
            if catalog.import_product_row(db, _as_dict(header, cells)):
                result["products"] += 1
            continue
        tag = cells[1].strip().lower() if len(cells) > 1 else ""
        if tag.startswith("#"):
            section, columns = tag, [cell.strip().lower() for cell in cells[2:]]
            if section == TIMER_MARK:
                result["has_timers"] = True
            continue
        row = _as_dict(columns, cells[2:])
        if section == TIMER_MARK and tag == TIMER_TAG:
            timer = _timer_from_row(row)
            if timer is None:
                result["timers_bad"] += 1
                continue
            key = timer_key(timer)
            if key in known:
                result["timers_existing"] += 1
                continue
            known.add(key)
            timer.created_at = ts
            if timer.end_at <= ts:
                timer.missed = 1
                timer.notified_at = ts
                result["timers_past"] += 1
            db.add_timer(timer)
            result["timers"] += 1
        elif section == ACCOUNT_MARK and tag == ACCOUNT_TAG:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            db.upsert_account(Account(
                world=(row.get("world") or "").strip(), name=name,
                owner=(row.get("owner") or "").strip(),
                buildings=(row.get("buildings") or "").strip(),
                note=(row.get("note") or "").strip()))
            result["accounts"] += 1
    return result


# -------------------------------------------------- думи за екрана и четеца

def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " и " + parts[-1]


def _counts(result: dict) -> list[str]:
    parts = [_count(result["products"], "продукт", "продукта")]
    if result.get("timers"):
        parts.append(_count(result["timers"], "таймер", "таймера"))
    if result.get("accounts"):
        parts.append(_count(result["accounts"], "компания", "компании"))
    return parts


def export_summary(counts: dict) -> str:
    """„Изнесени 48 продукта, 57 таймера и 41 компании.“"""
    parts = [_count(counts["products"], "продукт", "продукта"),
             _count(counts["timers"], "таймер", "таймера"),
             _count(counts["accounts"], "компания", "компании")]
    return f"Изнесени {_join(parts)}."


def import_summary(result: dict) -> str:
    """Какво е влязло — и изрично, ако във файла няма таймери."""
    parts = _counts(result)
    only_one = len(parts) == 1 and result["products"] == 1
    sentences = [f"{'Внесен' if only_one else 'Внесени'} {_join(parts)}."]
    if result.get("timers"):
        sentences.append("Таймерите са в раздел „Таймери“, Ctrl+1.")
    existing = result.get("timers_existing", 0)
    if existing:
        sentences.append(f"{_count(existing, 'таймер', 'таймера')} вече ги имаше "
                         "и не са внесени втори път.")
    past = result.get("timers_past", 0)
    if past:
        sentences.append(f"{past} {'е' if past == 1 else 'са'} с минал час и "
                         f"{'чака' if past == 1 else 'чакат'} потвърждение.")
    bad = result.get("timers_bad", 0)
    if bad:
        sentences.append(f"{_count(bad, 'ред', 'реда')} с таймери не са разчетени.")
    if not result.get("has_timers"):
        sentences.append(
            "Във файла няма таймери — изнесен е от по-стара версия на приложението. "
            "Изнеси го наново от другия компютър с тази версия и таймерите ще дойдат.")
    elif not (result.get("timers") or existing or bad):
        sentences.append("Във файла няма таймери.")
    return " ".join(sentences)
