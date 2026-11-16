"""Достъп до SQLite базата."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config
from .models import Account, HistoryEntry, Product, Timer, TimerStatus
from .timeutil import now as time_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL,
    quality              TEXT    NOT NULL DEFAULT '',
    category             TEXT    NOT NULL DEFAULT '',
    building             TEXT    NOT NULL DEFAULT '',
    research             TEXT    NOT NULL DEFAULT '',
    default_type         TEXT    NOT NULL DEFAULT 'production',
    default_duration_sec INTEGER NOT NULL DEFAULT 0,
    default_quantity     REAL    NOT NULL DEFAULT 0,
    unit_cost            REAL    NOT NULL DEFAULT 0,
    unit_price           REAL    NOT NULL DEFAULT 0,
    note                 TEXT    NOT NULL DEFAULT '',
    UNIQUE(name, quality)
);

CREATE TABLE IF NOT EXISTS timers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product        TEXT    NOT NULL DEFAULT '',
    quality        TEXT    NOT NULL DEFAULT '',
    type           TEXT    NOT NULL DEFAULT 'production',
    quantity       REAL    NOT NULL DEFAULT 0,
    line           TEXT    NOT NULL DEFAULT '',
    world          TEXT    NOT NULL DEFAULT '',
    building       TEXT    NOT NULL DEFAULT '',
    start_at       REAL    NOT NULL,
    end_at         REAL    NOT NULL,
    duration_sec   INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'running',
    repeat_enabled INTEGER NOT NULL DEFAULT 0,
    cycles_planned INTEGER NOT NULL DEFAULT 0,
    cycle_no       INTEGER NOT NULL DEFAULT 1,
    prewarn_sec    INTEGER NOT NULL DEFAULT 0,
    notified_at    REAL,
    prewarned_at   REAL,
    reminded_at    REAL,
    missed         INTEGER NOT NULL DEFAULT 0,
    note           TEXT    NOT NULL DEFAULT '',
    created_at     REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product      TEXT    NOT NULL DEFAULT '',
    quality      TEXT    NOT NULL DEFAULT '',
    type         TEXT    NOT NULL DEFAULT 'production',
    quantity     REAL    NOT NULL DEFAULT 0,
    line         TEXT    NOT NULL DEFAULT '',
    world        TEXT    NOT NULL DEFAULT '',
    start_at     REAL    NOT NULL DEFAULT 0,
    end_at       REAL    NOT NULL DEFAULT 0,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    finished_at  REAL    NOT NULL DEFAULT 0,
    cycle_no     INTEGER NOT NULL DEFAULT 1,
    profit       REAL    NOT NULL DEFAULT 0,
    note         TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    world       TEXT    NOT NULL DEFAULT '',
    name        TEXT    NOT NULL,
    owner       TEXT    NOT NULL DEFAULT '',
    buildings   TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL DEFAULT 0,
    UNIQUE(world, name)
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_timers_status ON timers(status, end_at);
CREATE INDEX IF NOT EXISTS idx_history_product ON history(product);
"""

PRODUCTS_SCHEMA = SCHEMA.split("CREATE TABLE IF NOT EXISTS timers")[0]

_TIMER_FIELDS = (
    "product", "quality", "type", "quantity", "line", "world", "building",
    "start_at", "end_at", "duration_sec",
    "status", "repeat_enabled", "cycles_planned", "cycle_no", "prewarn_sec",
    "notified_at", "prewarned_at", "reminded_at", "missed", "note", "created_at",
)
_ACCOUNT_FIELDS = ("world", "name", "owner", "buildings", "note", "created_at")

SCHEMA_VERSION = 3

_PRODUCT_FIELDS = (
    "name", "quality", "category", "building", "research", "default_type", "default_duration_sec",
    "default_quantity", "unit_cost", "unit_price", "note",
)


def _pylower(value):
    """Малки букви с поддръжка на кирилица (SQLite lower() е само за ASCII)."""
    return value.lower() if isinstance(value, str) else value


class Database:
    """Тънка обвивка около sqlite3 с готовите операции на приложението."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path else str(config.db_path())
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.create_function("pylower", 1, _pylower)
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Надгражда бази от по-стара версия, без да губи въведеното."""
        for table, column in (("timers", "quality"), ("history", "quality"),
                              ("timers", "world"), ("timers", "building"),
                              ("history", "world")):
            columns = {r["name"] for r in
                       self.conn.execute("PRAGMA table_info(" + table + ")")}
            if column not in columns:
                self.conn.execute(
                    "ALTER TABLE " + table + " ADD COLUMN " + column +
                    " TEXT NOT NULL DEFAULT ''")

        columns = {r["name"] for r in
                   self.conn.execute("PRAGMA table_info(products)")}
        if "quality" not in columns:
            # Старата таблица държи само името за единствено, новата - името
            # заедно с качеството, затова се преписва наново.
            kept = ("name, category, default_type, default_duration_sec, "
                    "default_quantity, unit_cost, unit_price, note")
            self.conn.executescript(
                "ALTER TABLE products RENAME TO products_old;"
                + PRODUCTS_SCHEMA
                + "INSERT INTO products (" + kept + ") SELECT " + kept
                + " FROM products_old;"
                + "DROP TABLE products_old;"
            )

        columns = {r["name"] for r in
                   self.conn.execute("PRAGMA table_info(products)")}
        if "building" not in columns:
            self.conn.execute(
                "ALTER TABLE products ADD COLUMN building TEXT NOT NULL DEFAULT ''")
        if "research" not in columns:
            self.conn.execute(
                "ALTER TABLE products ADD COLUMN research TEXT NOT NULL DEFAULT ''")

        self.set_meta("schema_version", str(SCHEMA_VERSION))

        # Категориите от по-ранна версия стават отраслите от играта.
        for old_name, new_name in (("Храни", "Агрокултура"),
                                   ("Промишлени", "Високи технологии")):
            self.conn.execute(
                "UPDATE products SET category = ? WHERE category = ?",
                (new_name, old_name))

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ---------------- таймери ----------------

    def add_timer(self, timer: Timer) -> int:
        if not timer.created_at:
            timer.created_at = time_now()
        columns = ", ".join(_TIMER_FIELDS)
        placeholders = ", ".join("?" * len(_TIMER_FIELDS))
        values = [getattr(timer, f) for f in _TIMER_FIELDS]
        sql = "INSERT INTO timers (" + columns + ") VALUES (" + placeholders + ")"
        cur = self.conn.execute(sql, values)
        self.conn.commit()
        timer.id = int(cur.lastrowid)
        return timer.id

    def update_timer(self, timer: Timer) -> None:
        if timer.id is None:
            raise ValueError("Таймерът няма id.")
        assignments = ", ".join(f + " = ?" for f in _TIMER_FIELDS)
        values = [getattr(timer, f) for f in _TIMER_FIELDS] + [timer.id]
        self.conn.execute("UPDATE timers SET " + assignments + " WHERE id = ?", values)
        self.conn.commit()

    def set_timer_fields(self, timer_id: int, **fields) -> None:
        keys = [k for k in fields if k in _TIMER_FIELDS]
        if not keys:
            return
        assignments = ", ".join(k + " = ?" for k in keys)
        values = [fields[k] for k in keys] + [timer_id]
        self.conn.execute("UPDATE timers SET " + assignments + " WHERE id = ?", values)
        self.conn.commit()

    def delete_timer(self, timer_id: int) -> None:
        self.conn.execute("DELETE FROM timers WHERE id = ?", (timer_id,))
        self.conn.commit()

    def get_timer(self, timer_id: int) -> Timer | None:
        row = self.conn.execute("SELECT * FROM timers WHERE id = ?", (timer_id,)).fetchone()
        return _row_to_timer(row) if row else None

    def list_timers(self, status: str | None = TimerStatus.RUNNING.value) -> list[Timer]:
        if status is None:
            rows = self.conn.execute("SELECT * FROM timers ORDER BY end_at").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM timers WHERE status = ? ORDER BY end_at", (status,)
            ).fetchall()
        return [_row_to_timer(r) for r in rows]

    def mark_missed_on_startup(self, now: float | None = None) -> list[Timer]:
        """Таймери, изтекли докато приложението е било затворено."""
        ts = time_now() if now is None else now
        rows = self.conn.execute(
            "SELECT * FROM timers WHERE status = ? AND end_at <= ? AND notified_at IS NULL",
            (TimerStatus.RUNNING.value, ts),
        ).fetchall()
        missed = [_row_to_timer(r) for r in rows]
        if missed:
            self.conn.executemany(
                "UPDATE timers SET missed = 1, notified_at = ? WHERE id = ?",
                [(ts, t.id) for t in missed],
            )
            self.conn.commit()
            for t in missed:
                t.missed = 1
                t.notified_at = ts
        return missed

    def complete_timer(self, timer_id: int, now: float | None = None,
                       profit: float = 0.0) -> Timer | None:
        """Отбелязва таймера като готов и го записва в историята."""
        ts = time_now() if now is None else now
        timer = self.get_timer(timer_id)
        if timer is None:
            return None
        self.conn.execute(
            "INSERT INTO history (product, quality, type, quantity, line, world, "
            "start_at, end_at, duration_sec, finished_at, cycle_no, profit, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timer.product, timer.quality, timer.type, timer.quantity,
             timer.line, timer.world, timer.start_at,
             timer.end_at, timer.duration_sec, ts, timer.cycle_no, profit, timer.note),
        )
        self.conn.execute(
            "UPDATE timers SET status = ?, missed = 0 WHERE id = ?",
            (TimerStatus.DONE.value, timer_id),
        )
        self.conn.commit()
        timer.status = TimerStatus.DONE.value
        timer.missed = 0
        return timer

    def start_next_cycle(self, timer: Timer, start_at: float | None = None) -> Timer | None:
        """Създава следващия цикъл на повтарящ се таймер."""
        if not timer.repeat_enabled:
            return None
        if timer.cycles_planned and timer.cycle_no >= timer.cycles_planned:
            return None
        start = time_now() if start_at is None else start_at
        nxt = Timer(
            product=timer.product,
            quality=timer.quality,
            world=timer.world,
            building=timer.building,
            type=timer.type,
            quantity=timer.quantity,
            line=timer.line,
            start_at=start,
            end_at=start + timer.duration_sec,
            duration_sec=timer.duration_sec,
            status=TimerStatus.RUNNING.value,
            repeat_enabled=timer.repeat_enabled,
            cycles_planned=timer.cycles_planned,
            cycle_no=timer.cycle_no + 1,
            prewarn_sec=timer.prewarn_sec,
            note=timer.note,
            created_at=start,
        )
        self.add_timer(nxt)
        return nxt

    # ---------------- продукти ----------------

    def upsert_product(self, product: Product) -> int:
        row = self.conn.execute(
            "SELECT id FROM products WHERE pylower(name) = pylower(?) "
            "AND pylower(quality) = pylower(?)",
            (product.name, product.quality),
        ).fetchone()
        values = [getattr(product, f) for f in _PRODUCT_FIELDS]
        if row:
            assignments = ", ".join(f + " = ?" for f in _PRODUCT_FIELDS)
            self.conn.execute(
                "UPDATE products SET " + assignments + " WHERE id = ?",
                values + [row["id"]],
            )
            self.conn.commit()
            product.id = int(row["id"])
        else:
            columns = ", ".join(_PRODUCT_FIELDS)
            placeholders = ", ".join("?" * len(_PRODUCT_FIELDS))
            cur = self.conn.execute(
                "INSERT INTO products (" + columns + ") VALUES (" + placeholders + ")",
                values,
            )
            self.conn.commit()
            product.id = int(cur.lastrowid)
        return product.id

    def get_product(self, name: str, quality: str = "") -> Product | None:
        row = self.conn.execute(
            "SELECT * FROM products WHERE pylower(name) = pylower(?) "
            "AND pylower(quality) = pylower(?)",
            (name, quality),
        ).fetchone()
        return _row_to_product(row) if row else None

    def list_products(self) -> list[Product]:
        rows = self.conn.execute(
            "SELECT * FROM products ORDER BY category, name, quality").fetchall()
        return [_row_to_product(r) for r in rows]

    def delete_product(self, product_id: int) -> None:
        self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.conn.commit()

    def remember_product(self, timer: Timer) -> None:
        """Запомня последното времетраене, количество и тип за продукта."""
        name = timer.product.strip()
        if not name:
            return
        quality = timer.quality.strip()
        product = (self.get_product(name, quality)
                   or Product(name=name, quality=quality))
        product.default_duration_sec = timer.duration_sec
        product.default_quantity = timer.quantity
        product.default_type = timer.type
        self.upsert_product(product)

    # ---------------- meta ----------------

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
        self.conn.commit()

    # ---------------- компании ----------------

    def get_account(self, world: str, name: str) -> Account | None:
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE pylower(world) = pylower(?) "
            "AND pylower(name) = pylower(?)",
            (world, name),
        ).fetchone()
        return _row_to_account(row) if row else None

    def upsert_account(self, account: Account) -> int:
        """Записва компанията; ако вече я има, **добавя** сградите към старите."""
        existing = self.get_account(account.world, account.name)
        if existing is None:
            if not account.created_at:
                account.created_at = time_now()
            columns = ", ".join(_ACCOUNT_FIELDS)
            placeholders = ", ".join("?" * len(_ACCOUNT_FIELDS))
            cur = self.conn.execute(
                "INSERT INTO accounts (" + columns + ") VALUES (" + placeholders + ")",
                [getattr(account, f) for f in _ACCOUNT_FIELDS])
            self.conn.commit()
            account.id = int(cur.lastrowid)
            return account.id

        for building in account.building_list:
            existing.add_building(building)
        if account.owner.strip():
            existing.owner = account.owner.strip()
        if account.note.strip() and account.note.strip() not in existing.note:
            existing.note = "; ".join(p for p in (existing.note, account.note.strip()) if p)
        self.update_account(existing)
        account.id = existing.id
        return existing.id

    def update_account(self, account: Account) -> None:
        if account.id is None:
            raise ValueError("Компанията няма id.")
        assignments = ", ".join(f + " = ?" for f in _ACCOUNT_FIELDS)
        self.conn.execute(
            "UPDATE accounts SET " + assignments + " WHERE id = ?",
            [getattr(account, f) for f in _ACCOUNT_FIELDS] + [account.id])
        self.conn.commit()

    def list_accounts(self, world: str | None = None) -> list[Account]:
        if world is None:
            rows = self.conn.execute(
                "SELECT * FROM accounts ORDER BY world, pylower(name)").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM accounts WHERE pylower(world) = pylower(?) "
                "ORDER BY pylower(name)", (world,)).fetchall()
        return [_row_to_account(r) for r in rows]

    def delete_account(self, account_id: int) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()

    def list_worlds(self) -> list[str]:
        """Всички светове, в които има компании или таймери."""
        rows = self.conn.execute(
            "SELECT world FROM accounts WHERE world != '' "
            "UNION SELECT world FROM timers WHERE world != ''").fetchall()
        return sorted({r["world"] for r in rows}, key=str.lower)

    # ---------------- история ----------------

    def list_history(self, limit: int = 1000) -> list[HistoryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM history ORDER BY finished_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_history(r) for r in rows]

    def clear_history(self) -> None:
        self.conn.execute("DELETE FROM history")
        self.conn.commit()


def _row_to_timer(row: sqlite3.Row) -> Timer:
    return Timer(
        id=int(row["id"]),
        product=row["product"],
        quality=row["quality"],
        type=row["type"],
        quantity=float(row["quantity"]),
        line=row["line"],
        world=row["world"],
        building=row["building"],
        start_at=float(row["start_at"]),
        end_at=float(row["end_at"]),
        duration_sec=int(row["duration_sec"]),
        status=row["status"],
        repeat_enabled=int(row["repeat_enabled"]),
        cycles_planned=int(row["cycles_planned"]),
        cycle_no=int(row["cycle_no"]),
        prewarn_sec=int(row["prewarn_sec"]),
        notified_at=row["notified_at"],
        prewarned_at=row["prewarned_at"],
        reminded_at=row["reminded_at"],
        missed=int(row["missed"]),
        note=row["note"],
        created_at=float(row["created_at"] or 0),
    )


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=int(row["id"]),
        world=row["world"],
        name=row["name"],
        owner=row["owner"],
        buildings=row["buildings"],
        note=row["note"],
        created_at=float(row["created_at"] or 0),
    )


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(
        id=int(row["id"]),
        name=row["name"],
        quality=row["quality"],
        category=row["category"],
        building=row["building"],
        research=row["research"],
        default_type=row["default_type"],
        default_duration_sec=int(row["default_duration_sec"]),
        default_quantity=float(row["default_quantity"]),
        unit_cost=float(row["unit_cost"]),
        unit_price=float(row["unit_price"]),
        note=row["note"],
    )


def _row_to_history(row: sqlite3.Row) -> HistoryEntry:
    return HistoryEntry(
        id=int(row["id"]),
        product=row["product"],
        quality=row["quality"],
        type=row["type"],
        quantity=float(row["quantity"]),
        line=row["line"],
        world=row["world"],
        start_at=float(row["start_at"]),
        end_at=float(row["end_at"]),
        duration_sec=int(row["duration_sec"]),
        finished_at=float(row["finished_at"]),
        cycle_no=int(row["cycle_no"]),
        profit=float(row["profit"]),
        note=row["note"],
    )
