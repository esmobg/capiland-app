"""Парсване и форматиране на дати, часове и времетраения.

Времената се пазят навсякъде като UTC epoch секунди (float) и се
показват в локалното време на компютъра.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

MINUTE = 60
HOUR = 3600
DAY = 86400

# Единици за времетраене на латиница и кирилица.
_UNITS: dict[str, int] = {}
for _names, _mult in (
    (("d", "day", "days", "д", "дн", "ден", "дни", "денонощие"), DAY),
    (("h", "hr", "hrs", "hour", "hours", "ч", "час", "часа", "часов"), HOUR),
    (("m", "min", "mins", "minute", "minutes", "м", "мин", "минута", "минути"), MINUTE),
    (("s", "sec", "secs", "second", "seconds", "с", "сек", "секунда", "секунди"), 1),
):
    for _n in _names:
        _UNITS[_n] = _mult

_TOKEN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([^\d\s,;]*)", re.UNICODE)

DATETIME_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M",
)
_TIME_ONLY_FORMATS = ("%H:%M:%S", "%H:%M")


def now() -> float:
    """Текущо време в UTC epoch секунди."""
    return time.time()


def parse_duration(text: str) -> int:
    """Превръща текст във времетраене в секунди.

    Приема ``3d 4h 20m``, ``3д 4ч 20м``, ``03:42:10`` (ч:м:с),
    ``2:30`` (ч:м), ``1.5h``, ``90m``. Само число без мерна единица
    се приема за минути.

    Хвърля ``ValueError`` при непознат или отрицателен вход.
    """
    if text is None:
        raise ValueError("Липсва времетраене.")
    raw = str(text).strip().lower().replace("\u00a0", " ")
    if not raw:
        raise ValueError("Липсва времетраене.")

    if ":" in raw:
        # Смесен запис като „1д 02:30:15“ — сумира се част по част.
        total = sum(
            _parse_clock_group(chunk, text) if ":" in chunk
            else _parse_unit_tokens(chunk, text)
            for chunk in raw.split()
        )
        return int(round(total))

    total = _parse_unit_tokens(raw, text)
    if total < 0:
        raise ValueError("Времетраенето не може да е отрицателно.")
    return int(round(total))


def _parse_clock_group(chunk: str, original: str) -> float:
    """``ч:м``, ``ч:м:с`` или ``д:ч:м:с``."""
    parts = [p.strip() for p in chunk.split(":")]
    if not all(re.fullmatch(r"\d+(?:[.,]\d+)?", p or "") for p in parts):
        raise ValueError(f"Непознат формат за време: {original!r}")
    nums = [float(p.replace(",", ".")) for p in parts]
    factors = {
        2: [HOUR, MINUTE],
        3: [HOUR, MINUTE, 1],
        4: [DAY, HOUR, MINUTE, 1],
    }.get(len(nums))
    if factors is None:
        raise ValueError(f"Непознат формат за време: {original!r}")
    return sum(n * f for n, f in zip(nums, factors))


def _parse_unit_tokens(chunk: str, original: str) -> float:
    """``3d 4h 20m``, ``3д 4ч 20м`` или голо число (минути)."""
    total = 0.0
    matched = 0
    for match in _TOKEN_RE.finditer(chunk):
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2).strip(".") or "m"  # голо число = минути
        if unit not in _UNITS:
            raise ValueError(f"Непозната мерна единица: {match.group(2)!r}")
        total += value * _UNITS[unit]
        matched += 1
    if not matched:
        raise ValueError(f"Непознат формат за време: {original!r}")
    return total


def format_duration(seconds: float, with_days: bool = True) -> str:
    """``9015`` -> ``02:30:15``; над 24 часа -> ``1д 02:30:15``."""
    total = int(round(seconds))
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rest = divmod(total, DAY)
    hours, rest = divmod(rest, HOUR)
    minutes, secs = divmod(rest, MINUTE)
    if days and with_days:
        return f"{sign}{days}д {hours:02d}:{minutes:02d}:{secs:02d}"
    if days:
        hours += days * 24
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"


def format_duration_words(seconds: float) -> str:
    """Четим запис за екранни четци: ``2 часа и 30 минути``."""
    total = int(round(abs(seconds)))
    days, rest = divmod(total, DAY)
    hours, rest = divmod(rest, HOUR)
    minutes, secs = divmod(rest, MINUTE)
    parts = []
    if days:
        parts.append(f"{days} {'ден' if days == 1 else 'дни'}")
    if hours:
        parts.append(f"{hours} {'час' if hours == 1 else 'часа'}")
    if minutes:
        parts.append(f"{minutes} {'минута' if minutes == 1 else 'минути'}")
    if secs and not days:
        parts.append(f"{secs} {'секунда' if secs == 1 else 'секунди'}")
    if not parts:
        return "0 секунди"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " и " + parts[-1]


def parse_datetime(text: str, base: float | None = None) -> float:
    """Превръща текст в epoch секунди (локално време).

    Приема ``12.09.2026 14:30``, ``2026-09-12 14:30``, ``12.09 14:30``
    (текущата година), ``14:30`` (днес, или утре ако часът вече е минал),
    както и ``сега`` / ``now``.
    """
    if text is None:
        raise ValueError("Липсва дата и час.")
    raw = str(text).strip().replace("\u00a0", " ")
    if not raw:
        raise ValueError("Липсва дата и час.")
    base_ts = now() if base is None else base
    if raw.lower() in ("сега", "now", "веднага"):
        return base_ts

    base_dt = datetime.fromtimestamp(base_ts)
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    # Кратка дата без година („12.09 14:30“) — добавяме текущата година.
    short = re.match(r"^(\d{1,2})\.(\d{1,2})(?!\.)(.*)$", raw)
    if short:
        candidate = (f"{short.group(1)}.{short.group(2)}."
                     f"{base_dt.year}{short.group(3)}")
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                return datetime.strptime(candidate, fmt).timestamp()
            except ValueError:
                continue
    for fmt in _TIME_ONLY_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        candidate = base_dt.replace(
            hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=0
        )
        if candidate.timestamp() < base_ts:
            candidate += timedelta(days=1)  # часът вече е минал -> утре
        return candidate.timestamp()
    raise ValueError(f"Непозната дата/час: {text!r}")


def format_dt(ts: float, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return datetime.fromtimestamp(ts).strftime(fmt)


def format_dt_relative(ts: float, base: float | None = None) -> str:
    """``днес 14:30`` / ``утре 09:05`` / ``15.09 09:05``."""
    base_ts = now() if base is None else base
    target = datetime.fromtimestamp(ts)
    today = datetime.fromtimestamp(base_ts).date()
    delta_days = (target.date() - today).days
    clock = target.strftime("%H:%M:%S")
    if delta_days == 0:
        return f"днес {clock}"
    if delta_days == 1:
        return f"утре {clock}"
    if delta_days == -1:
        return f"вчера {clock}"
    return target.strftime("%d.%m %H:%M:%S")
