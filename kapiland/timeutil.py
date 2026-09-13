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

# Български месеци — пълни и съкратени (в играта и в бележките се пишат и двете).
BG_MONTHS: dict[str, int] = {
    "януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6,
    "юли": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11,
    "декември": 12,
}
_BG_MONTH_PREFIXES: tuple[tuple[str, int], ...] = (
    ("яну", 1), ("фев", 2), ("мар", 3), ("апр", 4), ("май", 5), ("юни", 6),
    ("юли", 7), ("авг", 8), ("сеп", 9), ("окт", 10), ("ное", 11), ("дек", 12),
)
BG_MONTHS_GENITIVE = ("", "януари", "февруари", "март", "април", "май", "юни",
                      "юли", "август", "септември", "октомври", "ноември",
                      "декември")
BG_WEEKDAYS = ("понеделник", "вторник", "сряда", "четвъртък", "петък",
               "събота", "неделя")
BG_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "нд")

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‒": "-", "―": "-"})
# Съкращенията изискват край на думата — иначе „мар“ хваща „маркет“.
_BG_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*\.?\s*(януари|февруари|март|април|май|юни|юли|август|"
    r"септември|октомври|ноември|декември|"
    r"яну|фев|мар|апр|авг|септ|сеп|окт|ное|дек)\b\.?",
    re.IGNORECASE)
_BG_HOUR_RE = re.compile(
    r"(?<![\d.:])(\d{1,2})(?:[:.](\d{2}))?\s*(?:ч\b|ч\.|часа\b|h\b)",
    re.IGNORECASE)
_BG_RELATIVE_RE = re.compile(r"\b(днес|утре|вдругиден)\b", re.IGNORECASE)

PAST_TOLERANCE_DAYS = 60


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


def format_remaining_words(seconds: float) -> str:
    """Като ``format_duration_words``, но без секунди — текстът не се мени
    всяка секунда и четецът няма какво да препрочита."""
    total = int(abs(seconds))
    if total < MINUTE:
        return "по-малко от минута"
    return format_duration_words(total - total % MINUTE)


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

    # Български запис: „17 септември – 17 ч“, „утре 7 ч“, „17 ч“.
    moments = parse_bg_datetimes(raw, base_ts)
    if moments:
        return moments[0]
    hour_only = _BG_HOUR_RE.fullmatch(raw.strip())
    if hour_only:
        hour, minute = int(hour_only.group(1)), int(hour_only.group(2) or 0)
        if hour < 24 and minute < 60:
            candidate = base_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate.timestamp() < base_ts:
                candidate += timedelta(days=1)
            return candidate.timestamp()
    raise ValueError(f"Непозната дата/час: {text!r}")


def normalize_dashes(text: str) -> str:
    """Всички видове тирета стават „-“."""
    return (text or "").translate(_DASHES)


def month_from_word(word: str) -> int | None:
    lowered = word.lower().strip(".")
    if lowered in BG_MONTHS:
        return BG_MONTHS[lowered]
    for prefix, month in _BG_MONTH_PREFIXES:
        if lowered.startswith(prefix):
            return month
    return None


def infer_year(month: int, day: int, base: float,
               past_tolerance_days: int = PAST_TOLERANCE_DAYS) -> int:
    """Година за дата без година: текущата, освен ако излиза много назад."""
    base_dt = datetime.fromtimestamp(base)
    try:
        candidate = datetime(base_dt.year, month, day)
    except ValueError:
        return base_dt.year
    if (base_dt - candidate).days > past_tolerance_days:
        return base_dt.year + 1
    return base_dt.year


def bg_time_anchors(text: str) -> list[tuple[int, int, str, object]]:
    """Датите, часовете и „днес/утре“ в текста: (начало, край, вид, стойност).

    Видове: ``date`` → (ден, месец), ``relative`` → отместване в дни,
    ``hour`` → (час, минути). Подредени по място в текста.
    """
    source = normalize_dashes(text or "")
    anchors: list[tuple[int, int, str, object]] = []
    date_spans: list[tuple[int, int]] = []
    for match in _BG_DATE_RE.finditer(source):
        month = month_from_word(match.group(2))
        if month:
            anchors.append((match.start(), match.end(), "date",
                            (int(match.group(1)), month)))
            date_spans.append((match.start(), match.end()))
    for match in _BG_RELATIVE_RE.finditer(source):
        offset = {"днес": 0, "утре": 1, "вдругиден": 2}[match.group(1).lower()]
        anchors.append((match.start(), match.end(), "relative", offset))
    for match in _BG_HOUR_RE.finditer(source):
        if any(start <= match.start() < stop for start, stop in date_spans):
            continue
        anchors.append((match.start(), match.end(), "hour",
                        (int(match.group(1)), int(match.group(2) or 0))))
    anchors.sort(key=lambda item: item[0])
    return anchors


def resolve_anchor_day(kind: str, value, base: float) -> datetime | None:
    """Денят, който задава една котва от вид ``date`` или ``relative``."""
    if kind == "date":
        day, month = value
        try:
            return datetime(infer_year(month, day, base), month, day)
        except ValueError:
            return None
    if kind == "relative":
        base_dt = datetime.fromtimestamp(base)
        return base_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=value)
    return None


def anchor_moment(day: datetime | None, value) -> float | None:
    """Момент от ден и котва ``hour``; None при невалиден час."""
    if day is None:
        return None
    hour, minute = value
    if hour >= 24 or minute >= 60:
        return None
    return day.replace(hour=hour, minute=minute).timestamp()


def parse_bg_datetimes(text: str, base: float | None = None) -> list[float]:
    """Всички моменти в свободен български текст, по реда им.

    ``13 септември – 12 ч, 19 ч, 21 ч`` дава три момента;
    ``07 октомври – 16 ч, 08 октомври – 16 ч`` — два;
    ``утре 7 ч`` — един. Дата без час не се връща.
    """
    base_ts = now() if base is None else base
    moments: list[float] = []
    current_day: datetime | None = None
    for _start, _end, kind, value in bg_time_anchors(text):
        if kind in ("date", "relative"):
            current_day = resolve_anchor_day(kind, value, base_ts)
        else:
            moment = anchor_moment(current_day, value)
            if moment is not None:
                moments.append(moment)
    return moments


def format_when(ts: float, base: float | None = None) -> str:
    """Кратко и **неподвижно** време за списъци: ``днес 17:00``, ``ср 17.09 17:00``.

    Не съдържа секунди и не се мени, докато времето тече — екранният четец
    не препрочита реда всяка секунда.
    """
    base_ts = now() if base is None else base
    target = datetime.fromtimestamp(ts)
    base_dt = datetime.fromtimestamp(base_ts)
    delta_days = (target.date() - base_dt.date()).days
    clock = target.strftime("%H:%M")
    if delta_days == 0:
        return f"днес {clock}"
    if delta_days == 1:
        return f"утре {clock}"
    if delta_days == -1:
        return f"вчера {clock}"
    if 1 < delta_days < 7:
        return f"{BG_WEEKDAYS_SHORT[target.weekday()]} {target.strftime('%d.%m')} {clock}"
    if target.year != base_dt.year:
        return target.strftime("%d.%m.%Y %H:%M")
    return target.strftime("%d.%m %H:%M")


def _spoken_clock(target: datetime) -> str:
    if target.minute:
        return f"{target.hour}:{target.minute:02d}"
    return f"{target.hour} часа"


def format_when_spoken(ts: float, base: float | None = None) -> str:
    """Време за изговаряне: „днес в 17 часа“, „в сряда, 17 септември, в 7:30“."""
    base_ts = now() if base is None else base
    target = datetime.fromtimestamp(ts)
    base_dt = datetime.fromtimestamp(base_ts)
    delta_days = (target.date() - base_dt.date()).days
    clock = _spoken_clock(target)
    if delta_days == 0:
        return f"днес в {clock}"
    if delta_days == 1:
        return f"утре в {clock}"
    if delta_days == -1:
        return f"вчера в {clock}"
    date_words = f"{target.day} {BG_MONTHS_GENITIVE[target.month]}"
    if target.year != base_dt.year:
        date_words += f" {target.year}"
    if 1 < delta_days < 7:
        weekday = BG_WEEKDAYS[target.weekday()]
        preposition = "във" if weekday.startswith(("в", "ф")) else "в"
        return f"{preposition} {weekday}, {date_words}, в {clock}"
    return f"на {date_words} в {clock}"


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
