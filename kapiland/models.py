"""Типове данни на приложението."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class TimerType(str, Enum):
    PRODUCTION = "production"
    RESEARCH = "research"
    SALE = "sale"
    BUILD = "build"
    EXPAND = "expand"
    TRANSPORT = "transport"


TYPE_LABELS: dict[str, str] = {
    TimerType.PRODUCTION.value: "Производство",
    TimerType.RESEARCH.value: "Наука",
    TimerType.SALE.value: "Продажба",
    TimerType.BUILD.value: "Строеж",
    TimerType.EXPAND.value: "Разширяване",
    TimerType.TRANSPORT.value: "Транспорт",
}

TYPE_ORDER: tuple[str, ...] = tuple(TYPE_LABELS)

# Какво да пише в известието за всеки тип.
TYPE_ACTIONS: dict[str, str] = {
    TimerType.PRODUCTION.value: "Пусни следваща продукция.",
    TimerType.RESEARCH.value: "Пусни следващото изследване.",
    TimerType.SALE.value: "Офертата изтече — прибери парите и пусни нова.",
    TimerType.BUILD.value: "Строежът е готов — пусни следващия.",
    TimerType.EXPAND.value: "Разширяването е готово — пусни следващото.",
    TimerType.TRANSPORT.value: "Превозът пристигна — разтовари и пусни следващия.",
}


def type_label(value: str) -> str:
    return TYPE_LABELS.get(value, value)


def label_to_type(label: str) -> str:
    for value, text in TYPE_LABELS.items():
        if text == label:
            return value
    return TimerType.PRODUCTION.value


class TimerStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


# Състояния за показване (не се пазят в базата, изчисляват се).
STATE_RUNNING = "running"
STATE_SOON = "soon"
STATE_DUE = "due"
STATE_MISSED = "missed"
STATE_PAUSED = "paused"


@dataclass
class Timer:
    id: int | None = None
    product: str = ""
    quality: str = ""          # качество според играта: Q1, А, високо…
    type: str = TimerType.PRODUCTION.value
    quantity: float = 0.0
    line: str = ""             # компанията (акаунтът) в играта
    world: str = ""            # светът: „Немска двойка“, „Българска единица“…
    building: str = ""         # сградата: „Химически фабрики“…
    start_at: float = 0.0
    end_at: float = 0.0
    duration_sec: int = 0
    status: str = TimerStatus.RUNNING.value
    repeat_enabled: int = 0
    cycles_planned: int = 0
    cycle_no: int = 1
    prewarn_sec: int = 0
    notified_at: float | None = None
    prewarned_at: float | None = None
    reminded_at: float | None = None
    missed: int = 0
    note: str = ""
    created_at: float = 0.0

    # --- изчисления -------------------------------------------------
    def remaining(self, now: float) -> float:
        return self.end_at - now

    def is_due(self, now: float) -> bool:
        return self.status == TimerStatus.RUNNING.value and now >= self.end_at

    def progress(self, now: float) -> float:
        """0.0 – 1.0."""
        if self.duration_sec <= 0:
            return 1.0
        done = (now - self.start_at) / float(self.duration_sec)
        return min(1.0, max(0.0, done))

    def state(self, now: float, soon_sec: int = 0) -> str:
        if self.status == TimerStatus.CANCELLED.value:
            return STATE_PAUSED
        if self.status == TimerStatus.DONE.value:
            return STATE_PAUSED
        if now >= self.end_at:
            return STATE_MISSED if self.missed else STATE_DUE
        if soon_sec and self.remaining(now) <= soon_sec:
            return STATE_SOON
        return STATE_RUNNING

    @property
    def display_name(self) -> str:
        name = self.product.strip() or type_label(self.type)
        if self.quality.strip():
            name = f"{name} [{self.quality.strip()}]"
        if self.quantity:
            qty = int(self.quantity) if float(self.quantity).is_integer() else self.quantity
            name = f"{qty}× {name}"
        return name

    @property
    def cycle_text(self) -> str:
        if not self.repeat_enabled:
            return "—"
        if self.cycles_planned:
            return f"{self.cycle_no}/{self.cycles_planned}"
        return f"{self.cycle_no}/∞"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Account:
    """Компания (акаунт) в един свят на играта."""

    id: int | None = None
    world: str = ""
    name: str = ""
    owner: str = ""            # чия е: „Иван“, „Мария“…
    buildings: str = ""        # сградите, разделени с „; “
    note: str = ""
    created_at: float = 0.0

    @property
    def building_list(self) -> list[str]:
        return [b.strip() for b in self.buildings.split(";") if b.strip()]

    def add_building(self, building: str) -> None:
        building = building.strip()
        if not building:
            return
        current = self.building_list
        if building.lower() not in (b.lower() for b in current):
            current.append(building)
        self.buildings = "; ".join(current)

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.world})" if self.world.strip() else self.name


@dataclass
class Product:
    id: int | None = None
    name: str = ""
    quality: str = ""          # едно име в различно качество = различен запис
    category: str = ""
    building: str = ""         # в коя сграда се прави или продава
    research: str = ""         # в коя наука се изследва: „Химическа“…
    default_type: str = TimerType.PRODUCTION.value
    default_duration_sec: int = 0
    default_quantity: float = 0.0
    unit_cost: float = 0.0
    unit_price: float = 0.0
    note: str = ""

    @property
    def margin(self) -> float:
        return self.unit_price - self.unit_cost

    @property
    def display_name(self) -> str:
        return f"{self.name} [{self.quality}]" if self.quality.strip() else self.name


@dataclass
class HistoryEntry:
    id: int | None = None
    product: str = ""
    quality: str = ""          # качество според играта: Q1, А, високо…
    type: str = TimerType.PRODUCTION.value
    quantity: float = 0.0
    line: str = ""             # компанията (акаунтът) в играта
    world: str = ""            # светът: „Немска двойка“, „Българска единица“…
    building: str = ""         # сградата: „Химически фабрики“…
    start_at: float = 0.0
    end_at: float = 0.0
    duration_sec: int = 0
    finished_at: float = 0.0
    cycle_no: int = 1
    profit: float = 0.0
    note: str = ""
