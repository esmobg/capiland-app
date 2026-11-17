"""Проверка от край до край: пренос на таймерите между два компютъра с CSV.

Пуска истинското приложение два пъти с отделни данни — „компютър А“ и
„компютър Б“ — и минава по пътя на потребителя през Windows UI Automation
(същото, от което четат NVDA и JAWS), с истинските диалози на Windows:

Компютър А (с компания и два работещи таймера):
  1. Каталог → „Изнеси в CSV“ → файл на „флашката“.
Компютър Б (нова инсталация, без таймери):
  2. Списъкът „Таймери“ е празен.
  3. Файл → „Внеси от CSV от друг компютър…“ → същият файл.
  4. Таймерите са в списъка, със същия краен час като на А; светът е във
     филтъра; компанията е в „Компании“; съобщението казва какво е внесено.
  5. Втори внос на същия файл не удвоява нищо.
  6. Стар файл само с каталог: съобщението казва, че в него няма таймери.

Употреба:  python tools/transfer_check.py
Докато работи (около минута), не пиши на клавиатурата.
Изход 0 = всичко работи.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lists_check import (  # noqa: E402
    TITLE, check, find_dialog, results, status_text, wait_window)

EXPORT_TITLE = "Изнасяне на каталога, таймерите и компаниите"
IMPORT_TITLE = "Внасяне на каталог, таймери и компании"
MENU_IMPORT = "Внеси от CSV от друг компютър…"
MENU_EXPORT = "Изнеси всичко в CSV за друг компютър…"
WORLD = "Холандска единица"


def seed(db_path: str) -> list[float]:
    """Данните на „компютър А“. Връща крайните часове на таймерите."""
    from kapiland.db import Database
    from kapiland.models import Account, Product, Timer
    from kapiland.timeutil import now

    db = Database(db_path)
    n = now()
    db.upsert_product(Product(name="Джинси", category="Мода", default_duration_sec=5 * 3600,
                              unit_price=12.5))
    db.upsert_account(Account(world=WORLD, name="Делта", owner="Иван",
                              buildings="Текстилни фабрики"))
    ends = [n + 5 * 3600 + 17, n + 26 * 3600]
    db.add_timer(Timer(product="Джинси", quantity=1500, line="Делта", world=WORLD,
                       building="Текстилни фабрики", start_at=n, end_at=ends[0],
                       duration_sec=5 * 3600 + 17, repeat_enabled=1, note="за магазина"))
    db.add_timer(Timer(type="research", world="Немска единица", start_at=n,
                       end_at=ends[1], duration_sec=26 * 3600))
    db.close()
    return ends


def query(db_path: str, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return [tuple(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


class App:
    """Едно пускане на приложението с отделна папка за данни."""

    def __init__(self, label: str, seeded: bool = False) -> None:
        self.label = label
        self.workdir = tempfile.mkdtemp(prefix="kapilands-transfer-")
        self.db_path = os.path.join(self.workdir, "kapilands.db")
        self.ends = seed(self.db_path) if seeded else []
        env = dict(os.environ, KAPILANDS_DATA_DIR=self.workdir, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--db",
                                      self.db_path, "--allow-multiple"], env=env)
        self.window = wait_window(TITLE, timeout=30)
        if self.window is None:
            raise RuntimeError("прозорецът не се появи")
        self.window.SetActive()
        time.sleep(1.5)

    def in_front(self) -> bool:
        try:
            return auto.GetForegroundControl().ProcessId == self.proc.pid
        except Exception:
            return False

    def keys(self, keys: str, wait: float = 0.8, **options) -> None:
        """Клавиши само към това приложение — никога към чужд прозорец отпред."""
        if not self.in_front():
            try:
                self.window.SetActive()
            except Exception:
                pass
            time.sleep(0.4)
        if not self.in_front():
            raise RuntimeError("отпред е друг прозорец — клавишите не са пратени; "
                               "пусни проверката пак и не пипай клавиатурата")
        auto.SendKeys(keys, waitTime=wait, **options)

    def page(self, number: int) -> None:
        self.keys("{Ctrl}%d" % number, 1.2)

    def list_rows(self, name: str) -> list[str]:
        listbox = self.window.ListControl(searchDepth=6, SubName=name)
        if not listbox.Exists(5, 0.3):
            return []
        rows = []
        for item in listbox.GetChildren():
            if item.ControlTypeName not in ("ListItemControl", "DataItemControl"):
                continue
            # Името на реда е първата колона; останалите са негови деца.
            cells = [item.Name or ""] + [cell.Name or "" for cell in item.GetChildren()]
            rows.append("; ".join(dict.fromkeys(c for c in cells if c)))
        return rows

    def world_filter_has(self, world: str) -> bool:
        """Разгъва филтъра „Свят“ и търси света в него."""
        combo = self.window.ComboBoxControl(searchDepth=6, SubName="Свят")
        if not combo.Exists(3, 0.2):
            return False
        combo.GetExpandCollapsePattern().Expand()
        time.sleep(0.5)
        found = combo.ListItemControl(searchDepth=3, Name=world).Exists(2, 0.2)
        combo.GetExpandCollapsePattern().Collapse()
        return found

    def fill_file_dialog(self, title: str, path: Path) -> bool:
        dialog = find_dialog(self.window, title)
        if not check(dialog is not None, f"{self.label}: отвори се диалогът „{title}“"):
            return False
        box = dialog.EditControl(searchDepth=8, AutomationId="1001")   # „Запиши като“
        saving = box.Exists(2, 0.2)
        if saving:
            # Диалогът за запис взима името само от написаното с клавиши; зададено
            # през UI Automation, то се вижда в полето, но файлът отива в папката
            # по подразбиране със старото име.
            box.SetFocus()
            self.keys("{Ctrl}a", 0.2)
            self.keys(str(path), 0.4, interval=0.01)
        else:
            box = dialog.EditControl(searchDepth=8, AutomationId="1148")  # „Отвори“
            box.GetValuePattern().SetValue(str(path))
        if box.GetValuePattern().Value != str(path):
            # По-добре без файл, отколкото файл на грешно място.
            self.keys("{Esc}", 1)
            return check(False, f"{self.label}: пътят не влезе в полето за име на файл")
        time.sleep(0.4)
        box.SetFocus()
        self.keys("{Enter}", 1.5)  # както човек потвърждава диалога на Windows
        return check(not dialog.Exists(1, 0.2), f"{self.label}: диалогът се затвори")

    def export_with_button(self, path: Path) -> str:
        self.page(3)
        button = self.window.ButtonControl(searchDepth=6, Name="Изнеси в CSV")
        if not check(button.Exists(5, 0.3), f"{self.label}: в „Каталог“ има бутон „Изнеси в CSV“"):
            return ""
        button.GetInvokePattern().Invoke()
        self.fill_file_dialog(EXPORT_TITLE, path)
        return status_text(self.window)

    def menu_item(self, name: str):
        """Отваря „Файл“ и връща командата с това име (менюто остава отворено)."""
        self.window.SetActive()
        file_menu = self.window.MenuItemControl(searchDepth=3, Name="Файл")
        if not file_menu.Exists(3, 0.2):
            return None
        file_menu.GetExpandCollapsePattern().Expand()
        time.sleep(0.6)
        item = auto.MenuItemControl(searchDepth=4, Name=name)
        return item if item.Exists(3, 0.2) else None

    def import_with_menu(self, path: Path) -> str:
        item = self.menu_item(MENU_IMPORT)
        if not check(item is not None, f"{self.label}: в меню „Файл“ има „{MENU_IMPORT}“"):
            self.keys("{Esc}{Esc}")
            return ""
        item.GetInvokePattern().Invoke()
        self.fill_file_dialog(IMPORT_TITLE, path)
        return status_text(self.window)

    def close(self) -> None:
        try:
            self.keys("{Alt}{F4}", 1)
        except Exception:
            self.proc.terminate()  # без клавиши, ако отпред е чужд прозорец
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    usb = Path(tempfile.mkdtemp(prefix="kapilands-usb-"))
    csv_path = usb / "katalog.csv"
    old_csv = usb / "star-katalog.csv"
    old_csv.write_text("name;quality;category\nХляб;;Агрокултура\n", encoding="utf-8-sig")

    print("Компютър А", flush=True)
    a = App("компютър А", seeded=True)
    try:
        check(len(a.list_rows("Таймери")) == 2, "компютър А: в списъка има 2 таймера")
        item = a.menu_item(MENU_EXPORT)
        check(item is not None, f"компютър А: в меню „Файл“ има „{MENU_EXPORT}“")
        a.keys("{Esc}{Esc}", 0.5)
        said = a.export_with_button(csv_path)
        check("2 таймера и 1 компания" in said, f"компютър А: съобщението е „{said}“")
        text = csv_path.read_text(encoding="utf-8-sig") if csv_path.exists() else ""
        check(text.count(";timer;") == 2 and ";account;" in text,
              "компютър А: във файла има 2 таймера и компанията")
        ends = a.ends
    finally:
        a.close()

    print("Компютър Б", flush=True)
    b = App("компютър Б")
    try:
        check(b.list_rows("Таймери") == [], "компютър Б: нова инсталация — списъкът с таймери е празен")

        said = b.import_with_menu(csv_path)
        check("2 таймера и 1 компания" in said and "раздел „Таймери“" in said,
              f"компютър Б: съобщението е „{said}“")
        b.page(1)
        rows = b.list_rows("Таймери")
        check(len(rows) == 2, f"компютър Б: в списъка с таймери вече има {len(rows)} реда")
        jeans = next((row for row in rows if "Джинси" in row), "")
        check("Делта" in jeans and WORLD in jeans,
              f"компютър Б: редът в списъка е „{jeans}“")
        stored = query(b.db_path, "SELECT product, world, line, quantity, end_at, duration_sec, "
                                  "repeat_enabled, note FROM timers WHERE status = 'running' "
                                  "ORDER BY end_at")
        check(len(stored) == 2 and stored[0][:4] == ("Джинси", WORLD, "Делта", 1500.0),
              "компютър Б: продукт, свят, компания и количество са пренесени")
        check(len(stored) == 2 and abs(stored[0][4] - ends[0]) < 0.01
              and abs(stored[1][4] - ends[1]) < 0.01,
              "компютър Б: крайните часове са същите като на компютър А")
        check(len(stored) == 2 and stored[0][5:] == (5 * 3600 + 17, 1, "за магазина"),
              "компютър Б: времетраене, повторение и бележка са пренесени")
        check(query(b.db_path, "SELECT owner, buildings FROM accounts WHERE name = 'Делта'")
              == [("Иван", "Текстилни фабрики")],
              "компютър Б: компанията е пренесена със собственик и сгради")
        check(b.world_filter_has(WORLD), f"компютър Б: „{WORLD}“ е във филтъра „Свят“")
        b.page(2)
        check(any("Делта" in row for row in b.list_rows("Компании")),
              "компютър Б: компанията се вижда в раздел „Компании“")

        said = b.import_with_menu(csv_path)
        check("2 таймера вече ги имаше" in said, f"компютър Б: втори внос — „{said}“")
        check(len(query(b.db_path, "SELECT id FROM timers")) == 2,
              "компютър Б: вторият внос не удвои таймерите")

        said = b.import_with_menu(old_csv)
        check("няма таймери" in said and "по-стара версия" in said,
              f"компютър Б: стар файл — „{said}“")
    finally:
        b.close()

    failed = [text for ok, text in results if not ok]
    print(f"\n{len(results) - len(failed)} от {len(results)} проверки минаха.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
