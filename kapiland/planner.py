"""Изчисления — тук е „да смята“ от заданието.

Всичко тук са чисти функции без интерфейс и без база, за да могат да се
тестват. Времената са UTC epoch секунди.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Timer, TimerStatus, type_label
from .timeutil import DAY, HOUR, MINUTE

# ---------------------------------------------------------------- краен час


def end_from_start_duration(start_at: float, duration_sec: float) -> float:
    """Режим 1: начало + времетраене."""
    if duration_sec < 0:
        raise ValueError("Времетраенето не може да е отрицателно.")
    return start_at + duration_sec


def duration_from_start_end(start_at: float, end_at: float) -> int:
    """Режим 2: зададен краен час."""
    if end_at < start_at:
        raise ValueError("Краят не може да е преди началото.")
    return int(round(end_at - start_at))


def end_from_remaining(remaining_sec: float, now: float) -> float:
    """Режим 3: оставащо време, копирано от играта."""
    if remaining_sec < 0:
        raise ValueError("Оставащото време не може да е отрицателно.")
    return now + remaining_sec


def remaining(timer: Timer, now: float) -> float:
    return timer.end_at - now


def progress(timer: Timer, now: float) -> float:
    return timer.progress(now)


def next_start_suggestion(end_at: float, prep_lead_sec: float = 0.0) -> float:
    """Кога да си пред компютъра, за да пуснеш следващата партида."""
    return end_at - max(0.0, prep_lead_sec)


# ------------------------------------------------------- производителност


@dataclass
class Throughput:
    per_hour: float
    per_day: float
    seconds_per_unit: float


def throughput(quantity: float, duration_sec: float) -> Throughput:
    """Колко бройки на час и на ден дава партидата."""
    if duration_sec <= 0 or quantity <= 0:
        return Throughput(0.0, 0.0, 0.0)
    per_hour = quantity * HOUR / duration_sec
    return Throughput(per_hour, per_hour * 24, duration_sec / quantity)


def cycles_per_day(duration_sec: float) -> float:
    if duration_sec <= 0:
        return 0.0
    return DAY / duration_sec


# --------------------------------------------------------------- печалба


@dataclass
class Profit:
    total: float
    per_unit: float
    per_hour: float
    per_day: float


def profit(quantity: float, unit_cost: float, unit_price: float,
           duration_sec: float = 0.0) -> Profit:
    """Печалба от партидата и печалба на час — кой продукт си струва."""
    per_unit = unit_price - unit_cost
    total = per_unit * quantity
    if duration_sec and duration_sec > 0:
        per_hour = total * HOUR / duration_sec
    else:
        per_hour = 0.0
    return Profit(total, per_unit, per_hour, per_hour * 24)


def rank_by_profit_per_hour(candidates: list[dict]) -> list[dict]:
    """Подрежда продукти по печалба на час (най-изгодният е пръв).

    Всеки елемент трябва да има ``name``, ``quantity``, ``unit_cost``,
    ``unit_price`` и ``duration_sec``. Връща копия с добавен ``profit``.
    """
    ranked = []
    for item in candidates:
        p = profit(
            float(item.get("quantity", 0)),
            float(item.get("unit_cost", 0)),
            float(item.get("unit_price", 0)),
            float(item.get("duration_sec", 0)),
        )
        row = dict(item)
        row["profit_total"] = p.total
        row["profit_per_hour"] = p.per_hour
        ranked.append(row)
    ranked.sort(key=lambda r: r["profit_per_hour"], reverse=True)
    return ranked


# ------------------------------------------------------ линии и фабрики


@dataclass
class LineStatus:
    name: str
    busy: bool
    timer: Timer | None = None
    free_at: float | None = None

    @property
    def free_in(self) -> float:
        return 0.0 if self.free_at is None else self.free_at


def line_status(timers: list[Timer], lines: list[str], now: float) -> list[LineStatus]:
    """Коя линия е заета, коя е свободна и кога се освобождава."""
    active = [t for t in timers if t.status == TimerStatus.RUNNING.value]
    result: list[LineStatus] = []
    for name in lines:
        on_line = [t for t in active if t.line.strip() == name.strip() and t.end_at > now]
        if on_line:
            soonest = min(on_line, key=lambda t: t.end_at)
            result.append(LineStatus(name, True, soonest, soonest.end_at))
        else:
            result.append(LineStatus(name, False, None, None))
    return result


def free_lines(timers: list[Timer], lines: list[str], now: float) -> list[str]:
    return [ls.name for ls in line_status(timers, lines, now) if not ls.busy]


def next_line_free_at(timers: list[Timer], lines: list[str], now: float) -> float | None:
    """Кога се освобождава първата линия (None, ако вече има свободна)."""
    statuses = line_status(timers, lines, now)
    if any(not ls.busy for ls in statuses):
        return None
    busy = [ls.free_at for ls in statuses if ls.free_at is not None]
    return min(busy) if busy else None


# ------------------------------------------------------------- струпване


def find_collisions(timers: list[Timer], window_sec: float, now: float = 0.0) -> list[list[Timer]]:
    """Групи таймери, които свършват в рамките на ``window_sec`` един от друг.

    Полезно, за да знаеш кога ще ти се струпат няколко партиди наведнъж.
    """
    active = sorted(
        (t for t in timers if t.status == TimerStatus.RUNNING.value and t.end_at >= now),
        key=lambda t: t.end_at,
    )
    groups: list[list[Timer]] = []
    current: list[Timer] = []
    for timer in active:
        if current and timer.end_at - current[-1].end_at <= window_sec:
            current.append(timer)
        else:
            if len(current) > 1:
                groups.append(current)
            current = [timer]
    if len(current) > 1:
        groups.append(current)
    return groups


# --------------------------------------------------------------- програма


@dataclass
class AgendaItem:
    timer: Timer
    end_at: float
    in_seconds: float


def agenda(timers: list[Timer], now: float, horizon_sec: float = DAY) -> list[AgendaItem]:
    """Какво приключва в следващите ``horizon_sec`` секунди, по ред."""
    items = [
        AgendaItem(t, t.end_at, t.end_at - now)
        for t in timers
        if t.status == TimerStatus.RUNNING.value and now <= t.end_at <= now + horizon_sec
    ]
    items.sort(key=lambda i: i.end_at)
    return items


def next_due(timers: list[Timer], now: float) -> Timer | None:
    """Следващият таймер, който ще стане готов."""
    upcoming = [
        t for t in timers if t.status == TimerStatus.RUNNING.value and t.end_at > now
    ]
    return min(upcoming, key=lambda t: t.end_at) if upcoming else None


def due_now(timers: list[Timer], now: float) -> list[Timer]:
    """Готовите, но непотвърдени таймери."""
    return [t for t in timers if t.is_due(now)]


def idle_time(timers: list[Timer], line: str, now: float, horizon_sec: float = DAY) -> float:
    """Колко време линията ще стои празна в дадения хоризонт."""
    busy = sorted(
        (t for t in timers
         if t.status == TimerStatus.RUNNING.value
         and t.line.strip() == line.strip()
         and t.end_at > now),
        key=lambda t: t.start_at,
    )
    horizon_end = now + horizon_sec
    cursor = now
    occupied = 0.0
    for timer in busy:
        start = max(cursor, timer.start_at)
        end = min(horizon_end, timer.end_at)
        if end > start:
            occupied += end - start
            cursor = end
    return max(0.0, horizon_sec - occupied)


# -------------------------------------------------------------- статистика


def summarize_history(entries: list) -> list[dict]:
    """Обобщение по продукт: цикли, количество, средно време, печалба на час."""
    by_key: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (entry.product or "—", entry.quality, entry.type)
        row = by_key.setdefault(key, {
            "product": entry.product or "—",
            "quality": entry.quality,
            "type": entry.type,
            "type_label": type_label(entry.type),
            "cycles": 0,
            "quantity": 0.0,
            "total_seconds": 0.0,
            "profit": 0.0,
        })
        row["cycles"] += 1
        row["quantity"] += entry.quantity
        row["total_seconds"] += entry.duration_sec
        row["profit"] += entry.profit

    rows = []
    for row in by_key.values():
        cycles = row["cycles"] or 1
        row["avg_seconds"] = row["total_seconds"] / cycles
        hours = row["total_seconds"] / HOUR
        row["profit_per_hour"] = row["profit"] / hours if hours else 0.0
        row["quantity_per_hour"] = row["quantity"] / hours if hours else 0.0
        rows.append(row)
    rows.sort(key=lambda r: (-r["cycles"], r["product"]))
    return rows


def format_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


# ------------------------------------------------- компании и изговаряне

def _company_key(world: str, name: str) -> tuple[str, str]:
    return (world.strip().lower(), name.strip().lower())


def idle_accounts(accounts: list, timers: list[Timer], now: float) -> list:
    """Компании без нищо, което още тече — там може веднага да се пусне нещо."""
    busy = {
        _company_key(t.world, t.line)
        for t in timers
        if t.status == TimerStatus.RUNNING.value and t.end_at > now and t.line.strip()
    }
    return [a for a in accounts if _company_key(a.world, a.name) not in busy]


def account_timers(account, timers: list[Timer]) -> list[Timer]:
    key = _company_key(account.world, account.name)
    return sorted((t for t in timers
                   if t.status == TimerStatus.RUNNING.value
                   and _company_key(t.world, t.line) == key),
                  key=lambda t: t.end_at)


def group_by_world(timers: list[Timer]) -> dict[str, list[Timer]]:
    groups: dict[str, list[Timer]] = {}
    for timer in sorted(timers, key=lambda t: t.end_at):
        groups.setdefault(timer.world.strip(), []).append(timer)
    return dict(sorted(groups.items(), key=lambda item: item[0].lower()))


def describe_spoken(timer: Timer) -> str:
    """„1000 Бензин, Алфа маркет 7, Немска двойка“ — кратко, за изговаряне."""
    what = timer.display_name if timer.product.strip() else type_label(timer.type)
    parts = [what]
    if timer.line.strip():
        parts.append(timer.line.strip())
    if timer.world.strip():
        parts.append(timer.world.strip())
    return ", ".join(parts)


def spoken_summary(timers: list[Timer], now: float, limit: int = 3) -> str:
    """Какво е готово и какво следва — едно изречение за екранния четец."""
    from .timeutil import format_when_spoken

    running = [t for t in timers if t.status == TimerStatus.RUNNING.value]
    if not running:
        return "Няма активни таймери."
    sentences = []
    due = sorted(due_now(running, now), key=lambda t: t.end_at)
    if due:
        names = "; ".join(describe_spoken(t) for t in due[:limit])
        more = f"; и още {len(due) - limit}" if len(due) > limit else ""
        head = "Готово" if len(due) == 1 else f"Готови {len(due)}"
        sentences.append(f"{head}: {names}{more}.")
    else:
        sentences.append("Нищо не е готово.")
    upcoming = next_due(running, now)
    if upcoming is not None:
        sentences.append(
            f"Следващо: {describe_spoken(upcoming)}, "
            f"{format_when_spoken(upcoming.end_at, now)}.")
    return " ".join(sentences)
