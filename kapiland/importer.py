"""Внос на списък в свободен текст — така, както играчът си води бележките.

Пример за формата, който се разпознава::

    Алфа маркет 7
    Бензин – 17 септември – 17 ч
    Гама83 – Двигатели – 02 септември – 07 ч, 05 септември – 07 ч
    Допълнителни:
    ламбда
    Строят се бензиностанции
    Ще бъдат готови на 17 декември – 18 ч
    Немска двойка – Тау – Токът ще бъде готов на 08 октомври – 07 ч
    Науки:
    Немска единица – 14 септември – 07 ч
    Магазини
    Холандска единица
    1500 джинси 03 октомври –07 ч

**Данни за вход не се пазят.** В блок „Компании на …“ ред само от цифри е
парола, а редът точно преди него — потребителско име. И двата се пропускат;
съдържанието им не се връща никъде, само броят.

Модулът е без база и без интерфейс: ``parse()`` дава резултат за преглед,
``apply()`` записва отметнатото.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import catalog
from .models import Account, Product, Timer, TimerStatus, TimerType
from .timeutil import (
    anchor_moment,
    bg_time_anchors,
    format_dt,
    normalize_dashes,
    now as time_now,
    resolve_anchor_day,
)

PRODUCTION = TimerType.PRODUCTION.value
RESEARCH = TimerType.RESEARCH.value
SALE = TimerType.SALE.value
BUILD = TimerType.BUILD.value
EXPAND = TimerType.EXPAND.value

NOTE_PAST = "в миналото"
NOTE_DUPLICATE = "дубликат"
NOTE_EXISTS = "вече го има"
NOTE_NEW_PRODUCT = "нов продукт"
NOTE_NO_WORLD = "без свят"

_SECTION_RESEARCH = re.compile(r"^науки\s*:?$", re.IGNORECASE)
_SECTION_SALE = re.compile(r"^магазини\s*:?$", re.IGNORECASE)
_SECTION_EXTRA = re.compile(r"^допълнителни\s*:?$", re.IGNORECASE)
_SECTION_OWNER = re.compile(r"^компании\s+на\s+(.+?)\s*:?$", re.IGNORECASE)
_CREDENTIAL = re.compile(r"^\d{4,}$")
# Потребителско име извън блок „Компании на …“: една дума с букви и цифри.
_LOGIN_LIKE = re.compile(r"^(?=\S*\d)(?=\S*[A-Za-zА-Яа-я])\S+$")
_IDLE = re.compile(r"^не\s+произвежда\s*,?\s*не\s+продава\b", re.IGNORECASE)
_VERBS = (
    (re.compile(r"^произвежда(?:т)?(?:\s+се)?\b", re.IGNORECASE), PRODUCTION),
    (re.compile(r"^продава(?:т)?(?:\s+се)?\b", re.IGNORECASE), SALE),
    (re.compile(r"^стро(?:и|ят)\s+се\b", re.IGNORECASE), BUILD),
    (re.compile(r"^разширява(?:т)?\s+се\b", re.IGNORECASE), EXPAND),
)
_FILLER = re.compile(
    r",?\s*\bще\s+(?:бъде|бъдат|са)\s+готов[аои]?\b(?:\s+на\b)?"
    r"|\bготов[аои]?\s+на\b",
    re.IGNORECASE)
_QUANTITY = re.compile(r"^(\d{3,})\s+(?:и\s+)?", re.IGNORECASE)
_PART_SPLIT = re.compile(r"\s*-+\s+|\s+-+\s*|^-+|-+$")
_LETTERS = re.compile(r"[A-Za-zА-Яа-яЁё]")
_AND = re.compile(r"\s+и\s+", re.IGNORECASE)
MAX_COMPANY_WORDS = 4


# ------------------------------------------------------------------ данни

@dataclass
class ImportEntry:
    """Един таймер, разпознат от текста."""

    line_no: int
    world: str
    company: str
    owner: str
    building: str
    type: str
    product: str
    quantity: float
    end_at: float
    known_product: bool = True
    notes: list[str] = field(default_factory=list)
    selected: bool = True

    def key(self) -> tuple:
        return (self.world.lower(), self.company.lower(), self.product.lower(),
                self.type, int(round(self.end_at)))

    def add_note(self, note: str, deselect: bool = False) -> None:
        if note not in self.notes:
            self.notes.append(note)
        if deselect:
            self.selected = False


@dataclass
class ImportAccount:
    """Една компания, разпозната от текста."""

    world: str
    name: str
    owner: str = ""
    buildings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    idle: bool = False
    line_no: int = 0
    has_data: bool = False

    def key(self) -> tuple:
        return (self.world.lower(), self.name.lower())

    def add_building(self, building: str) -> None:
        if building and building.lower() not in (b.lower() for b in self.buildings):
            self.buildings.append(building)
        self.has_data = True

    def add_note(self, note: str) -> None:
        if note and note not in self.notes:
            self.notes.append(note)
        self.has_data = True


@dataclass
class ImportResult:
    entries: list[ImportEntry]
    accounts: list[ImportAccount]
    skipped_credentials: int
    unrecognized: list[tuple[int, str]]
    default_world: str = ""

    @property
    def selected_entries(self) -> list[ImportEntry]:
        return [e for e in self.entries if e.selected]

    @property
    def worlds(self) -> list[str]:
        found = {e.world for e in self.entries if e.world}
        found |= {a.world for a in self.accounts if a.world}
        return sorted(found, key=str.lower)

    def count_note(self, note: str) -> int:
        return sum(1 for e in self.entries if note in e.notes)

    def summary(self) -> str:
        """Обобщение с думи — и за екрана, и за изговаряне."""
        timers = len(self.entries)
        companies = len(self.accounts)
        worlds = len(self.worlds)
        parts = [
            f"Разпознати {timers} {_plural(timers, 'таймер', 'таймера')} "
            f"в {companies} {_plural(companies, 'компания', 'компании')} "
            f"и {worlds} {_plural(worlds, 'свят', 'свята')}."
        ]
        details = []
        past = self.count_note(NOTE_PAST)
        if past:
            details.append(f"{past} в миналото")
        duplicates = self.count_note(NOTE_DUPLICATE)
        if duplicates:
            details.append(f"{duplicates} {_plural(duplicates, 'дубликат', 'дубликата')}")
        exists = self.count_note(NOTE_EXISTS)
        if exists:
            details.append(f"{exists} вече ги има")
        new_products = len({e.product.lower() for e in self.entries
                            if NOTE_NEW_PRODUCT in e.notes})
        if new_products:
            details.append(f"{new_products} {_plural(new_products, 'нов продукт', 'нови продукта')}")
        if self.skipped_credentials:
            details.append(
                f"{self.skipped_credentials} "
                f"{_plural(self.skipped_credentials, 'ред', 'реда')} с данни за вход пропуснати")
        if self.unrecognized:
            count = len(self.unrecognized)
            details.append(f"{count} {_plural(count, 'ред не е разпознат', 'реда не са разпознати')}")
        if details:
            parts.append(", ".join(details).capitalize() + ".")
        selected = len(self.selected_entries)
        parts.append(f"Отметнати за внос: {selected}.")
        return " ".join(parts)


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


# ----------------------------------------------------------------- помощни

def _clean(text: str) -> str:
    return (text or "").strip(" \t,.;:-")


def _split_verb(text: str) -> tuple[str | None, str]:
    for pattern, kind in _VERBS:
        match = pattern.match(text)
        if match:
            return kind, _clean(text[match.end():])
    return None, text


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _parts(head: str) -> list[str]:
    head = _FILLER.sub(" ", head or "")
    return [p for p in (_clean(x) for x in _PART_SPLIT.split(head)) if p]


# ------------------------------------------------------------------ парсер

class _Parser:
    def __init__(self, default_world: str, now: float, known_products: list[str]) -> None:
        self.default_world = default_world.strip()
        self.now = now
        self.known_products = known_products

        self.world = self.default_world
        self.section: str | None = None
        self.owner = ""
        self.in_owner_block = False
        self.company: ImportAccount | None = None
        self.prev_company: ImportAccount | None = None
        self.pending: dict | None = None
        self.prev_kind = ""
        self.last_header_created = False

        self.entries: list[ImportEntry] = []
        self.accounts: dict[tuple, ImportAccount] = {}
        self.skipped_credentials = 0
        self.unrecognized: list[tuple[int, str]] = []

    # ------------------------------------------------------------ компании

    def _account(self, name: str, line_no: int, world: str | None = None) -> tuple[ImportAccount, bool]:
        world = self.world if world is None else world
        key = (world.lower(), name.lower())
        account = self.accounts.get(key)
        if account is not None:
            if self.owner and not account.owner:
                account.owner = self.owner
            return account, False
        account = ImportAccount(world=world, name=name, owner=self.owner, line_no=line_no)
        self.accounts[key] = account
        return account, True

    def _open_company(self, name: str, line_no: int) -> None:
        account, created = self._account(name, line_no)
        self.prev_company = self.company
        self.company = account
        self.last_header_created = created
        self.prev_kind = "header"

    # ------------------------------------------------------------- раздели

    def _enter_section(self, section: str | None, owner: str = "") -> None:
        self._flush_pending()
        self.section = section
        self.owner = owner
        self.in_owner_block = bool(owner)
        self.world = self.default_world
        self.company = None
        self.prev_company = None

    # ------------------------------------------------------- неизползвано

    def _flush_pending(self) -> None:
        """Дейност, за която не дойде час — остава бележка към компанията."""
        if not self.pending:
            return
        pending, self.pending = self.pending, None
        account = pending.get("company")
        if account is None:
            self.unrecognized.append((pending["line_no"], pending["text"]))
            return
        account.add_note(f"{pending['text']} (без час)")

    # --------------------------------------------------------------- ред

    def feed(self, line_no: int, raw: str) -> None:
        text = " ".join(normalize_dashes(raw).split())
        if not text:
            return

        if _SECTION_RESEARCH.match(text):
            self._enter_section(RESEARCH)
        elif _SECTION_SALE.match(text):
            self._enter_section(SALE)
        elif _SECTION_EXTRA.match(text):
            self._enter_section(None)
        elif (owner := _SECTION_OWNER.match(text)) is not None:
            self._enter_section(None, owner=_capitalize(owner.group(1).strip()))
        elif _CREDENTIAL.match(text):
            self._credential()
            return
        else:
            self._content(line_no, text)
            return
        self.prev_kind = "section"

    def _credential(self) -> None:
        self.skipped_credentials += 1
        if (self.prev_kind == "header" and self.company is not None
                and self.last_header_created and not self.company.has_data
                and (self.in_owner_block or _LOGIN_LIKE.match(self.company.name))):
            # Редът преди паролата е потребителско име, а не компания.
            self.accounts.pop(self.company.key(), None)
            self.skipped_credentials += 1
            self.company = self.prev_company
        self.prev_kind = "credential"

    def _content(self, line_no: int, text: str) -> None:
        is_world_line = False
        world = catalog.parse_world(text)
        if world is not None:
            self._flush_pending()
            self.world, rest = world[0], _clean(world[1])
            self.company = None
            if self.section is None:
                self.owner = ""
                self.in_owner_block = False
            if not rest:
                self.prev_kind = "world"
                return
            text = rest
            is_world_line = True

        anchors = bg_time_anchors(text)
        if any(kind == "hour" for _s, _e, kind, _v in anchors):
            self._timed(line_no, text, anchors, is_world_line)
        else:
            self._untimed(line_no, text, is_world_line)

    # ------------------------------------------------------ ред без час

    def _untimed(self, line_no: int, text: str, is_world_line: bool) -> None:
        self._flush_pending()
        clean = _clean(text)
        if not clean:
            return

        if _IDLE.match(clean):
            if self.company is None:
                self.unrecognized.append((line_no, clean))
            else:
                self.company.idle = True
                self.company.add_note("не произвежда, не продава")
            self.prev_kind = "info"
            return

        kind, rest = _split_verb(clean)
        if kind is not None:
            info = self._activity(clean)
            if info["building"] and self.company is not None:
                self.company.add_building(info["building"])
            self.pending = dict(info, company=self.company, line_no=line_no, text=clean)
            self.prev_kind = "activity"
            return

        building = catalog.find_building(clean)
        if building and catalog.find_building(clean) and self._is_whole_building(clean):
            if self.company is None:
                self.unrecognized.append((line_no, clean))
            else:
                self.company.add_building(building)
            self.prev_kind = "building"
            return

        if is_world_line:
            parts = _parts(clean)
            company = None
            if len(parts) >= 2:
                company, _ = self._account(" ".join(parts[:-1]), line_no)
                self.company = company
            info = self._activity(parts[-1] if parts else clean)
            self.pending = dict(info, company=company, line_no=line_no, text=clean)
            self.prev_kind = "activity"
            return

        if not _LETTERS.search(clean) or len(clean.split()) > MAX_COMPANY_WORDS:
            self.unrecognized.append((line_no, clean))
            self.prev_kind = "unrecognized"
            return

        self._open_company(clean, line_no)

    @staticmethod
    def _is_whole_building(text: str) -> bool:
        building = catalog.find_building(text)
        if building is None:
            return False
        words = len(text.split())
        aliases = [building] + [a for a, c in catalog._BUILDING_ALIASES.items() if c == building]
        return any(len(a.split()) == words for a in aliases)

    # ------------------------------------------------------- ред с час

    def _timed(self, line_no: int, text: str, anchors: list, is_world_line: bool) -> None:
        source = normalize_dashes(text)
        groups: list[tuple[str, list[float]]] = []
        cursor = 0
        current_day = None
        for start, end, kind, value in anchors:
            gap = source[cursor:start]
            if not groups or _LETTERS.search(_FILLER.sub(" ", gap)):
                groups.append((gap, []))
            if kind in ("date", "relative"):
                current_day = resolve_anchor_day(kind, value, self.now)
            else:
                moment = anchor_moment(current_day, value)
                if moment is not None:
                    groups[-1][1].append(moment)
            cursor = end

        created_any = False
        previous: tuple[dict, ImportAccount | None] | None = None
        for head, moments in groups:
            if not moments:
                continue
            parts = _parts(head)
            account = self.company
            if not parts:
                if self.pending is not None:
                    info = {k: self.pending[k] for k in ("type", "products", "quantity", "building")}
                    account = self.pending["company"]
                    self.pending = None
                elif previous is not None:
                    info, account = previous
                else:
                    info = self._activity("")
            else:
                if len(parts) >= 2:
                    name = " ".join(parts[:-1])
                    if _split_verb(name)[0] is None and not self._is_whole_building(name):
                        account, _ = self._account(name, line_no)
                        self.company = account
                info = self._activity(parts[-1])
                if self.pending is not None and not info["products"] and not info["building"]:
                    info["products"] = self.pending["products"]
                    info["quantity"] = info["quantity"] or self.pending["quantity"]
                self.pending = None
            previous = (info, account)

            if not info["products"] and info["type"] not in (RESEARCH, BUILD, EXPAND) \
                    and account is None and self.section is None:
                continue

            building = info["building"] or self._pick_building(account, info["products"])
            if building and account is not None and info["type"] in (BUILD, EXPAND):
                account.add_building(building)
            for product in info["products"] or [""]:
                known = not product or catalog.find_product(product, self.known_products) is not None
                for moment in moments:
                    entry = ImportEntry(
                        line_no=line_no,
                        world=account.world if account is not None else self.world,
                        company=account.name if account is not None else "",
                        owner=account.owner if account is not None else self.owner,
                        building=building,
                        type=info["type"],
                        product=product,
                        quantity=info["quantity"],
                        end_at=moment,
                        known_product=known,
                    )
                    self.entries.append(entry)
                    created_any = True
            if account is not None:
                account.has_data = True

        if not created_any:
            self.unrecognized.append((line_no, _clean(text)))
        self.prev_kind = "timer"

    # ------------------------------------------------------------ дейност

    def _activity(self, text: str) -> dict:
        """Разчита „Произвеждат 10000000 бензин“ и подобни."""
        text = _clean(_FILLER.sub(" ", text or ""))
        kind = self.section or PRODUCTION
        verb, rest = _split_verb(text)
        if verb is not None:
            kind = verb if self.section != RESEARCH else RESEARCH
        else:
            rest = text

        building = ""
        if verb in (BUILD, EXPAND):
            building = catalog.find_building(rest) or ""
            if building:
                rest = ""

        quantity = 0.0
        match = _QUANTITY.match(rest)
        if match:
            quantity = float(match.group(1))
            rest = rest[match.end():]
        rest = _clean(rest)

        products: list[str] = []
        if rest:
            pieces = _AND.split(rest)
            known = [catalog.find_product(p, self.known_products) for p in pieces]
            if len(pieces) > 1 and all(known):
                products = [k for k in known if k]
            else:
                products = [catalog.find_product(rest, self.known_products) or _capitalize(rest)]
        return {"type": kind, "products": products, "quantity": quantity, "building": building}

    @staticmethod
    def _pick_building(account: ImportAccount | None, products: list[str]) -> str:
        """Сграда само от сградите, изброени за компанията — без гадаене.

        Каталогът знае, че компютрите се правят във „Фабрики за електроника“,
        но „Ипсилон продава компютри“ е в магазин. Затова връзката от каталога се
        ползва само за избор между сградите, които компанията вече има.
        """
        if account is None or not account.buildings:
            return ""
        mapped = catalog.building_for_product(products[0]) if products else ""
        if mapped and mapped in account.buildings:
            return mapped
        return account.buildings[-1]

    # ------------------------------------------------------------- край

    def finish(self) -> ImportResult:
        self._flush_pending()
        seen: set[tuple] = set()
        for entry in self.entries:
            key = entry.key()
            if key in seen:
                entry.add_note(NOTE_DUPLICATE, deselect=True)
            seen.add(key)
            if entry.end_at < self.now:
                entry.add_note(NOTE_PAST, deselect=True)
            if not entry.known_product:
                entry.add_note(NOTE_NEW_PRODUCT)
            if not entry.world:
                entry.add_note(NOTE_NO_WORLD)
        return ImportResult(
            entries=self.entries,
            accounts=list(self.accounts.values()),
            skipped_credentials=self.skipped_credentials,
            unrecognized=self.unrecognized,
            default_world=self.default_world,
        )


# -------------------------------------------------------------- публични

def parse(text: str, default_world: str = "", now: float | None = None,
          known_products: list[str] | None = None) -> ImportResult:
    """Разчита поставения текст. Нищо не записва."""
    parser = _Parser(default_world, time_now() if now is None else now,
                     list(known_products or []))
    for number, line in enumerate((text or "").splitlines(), start=1):
        parser.feed(number, line)
    return parser.finish()


def mark_existing(result: ImportResult, db) -> int:
    """Маха отметката от таймери, които вече ги има в базата."""
    existing = {
        (t.world.lower(), t.line.lower(), t.product.lower(), t.type, int(round(t.end_at)))
        for t in db.list_timers(TimerStatus.RUNNING.value)
    }
    count = 0
    for entry in result.entries:
        if entry.key() in existing:
            if entry.selected:
                count += 1  # броят се само махнатите отметки
            entry.add_note(NOTE_EXISTS, deselect=True)
    return count


def apply(result: ImportResult, db, now: float | None = None) -> dict:
    """Записва компаниите и **отметнатите** таймери. Връща броя записани."""
    ts = time_now() if now is None else now
    stamp = format_dt(ts, "%d.%m.%Y %H:%M")
    companies = 0
    for account in result.accounts:
        db.upsert_account(Account(
            world=account.world,
            name=account.name,
            owner=account.owner,
            buildings="; ".join(account.buildings),
            note="; ".join(account.notes),
        ))
        companies += 1

    timers = 0
    new_products = 0
    for entry in result.selected_entries:
        past = entry.end_at <= ts
        timer = Timer(
            product=entry.product,
            type=entry.type,
            quantity=entry.quantity,
            line=entry.company,
            world=entry.world,
            building=entry.building,
            start_at=entry.end_at if past else ts,
            end_at=entry.end_at,
            duration_sec=max(0, int(round(entry.end_at - ts))),
            status=TimerStatus.RUNNING.value,
            note=f"Внесено на {stamp}",
            created_at=ts,
        )
        if past:
            # Без буря от известия за отдавна минали неща — показват се като пропуснати.
            timer.missed = 1
            timer.notified_at = ts
        db.add_timer(timer)
        timers += 1
        if entry.product and db.get_product(entry.product) is None:
            db.upsert_product(Product(name=entry.product,
                                      building=entry.building,
                                      default_type=entry.type))
            new_products += 1
    return {"companies": companies, "timers": timers, "new_products": new_products}
