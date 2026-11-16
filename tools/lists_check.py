"""Проверка от край до край: списъците „Изследвания“ и „Производство“.

Пуска истинското приложение два пъти с отделни празни данни — „компютър А“ и
„компютър Б“ — и натиска бутоните в раздел „Каталог“ така, както човек би
ги натиснал, през Windows UI Automation (същото, от което четат NVDA и JAWS):

Компютър А:
  1. Нова инсталация — вградените списъци са в каталога (Бензин → Химическа).
  2. „Внеси списък (TXT)“ с файл, в който Бензин е в наука „Медийна“ —
     собствена промяна на играча.
  3. „Внеси списък (TXT)“ с Производство.txt (по избор — ``--production``).
  4. „Изнеси списъци (TXT)“ в папка.
Компютър Б:
  5. Нова инсталация — Бензин пак е „Химическа“ (вграденото).
  6. „Внеси списък (TXT)“ с изнесения Изследвания.txt → Бензин е „Медийна“.

Употреба:  python tools/lists_check.py [--production път\\Производство.txt]
Докато работи (около минута), не пиши на клавиатурата.
Изход 0 = всичко работи.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
TITLE = "Kapilands Таймер"
IMPORT_TITLE = "Внасяне на списък с изследвания или производство"
EXPORT_TITLE = "Папка за Изследвания.txt и Производство.txt"

results: list[tuple[bool, str]] = []


def check(ok: bool, text: str) -> bool:
    results.append((bool(ok), text))
    print(("  ОК    " if ok else "  ГРЕШКА ") + text, flush=True)
    return bool(ok)


def wait_window(name_part: str, timeout: float = 15):
    end = time.time() + timeout
    while time.time() < end:
        for window in auto.GetRootControl().GetChildren():
            try:
                if name_part in (window.Name or ""):
                    return window
            except Exception:
                continue
        time.sleep(0.3)
    return None


def find_dialog(main_window, title: str, timeout: float = 10):
    dialog = main_window.WindowControl(searchDepth=1, Name=title)
    if dialog.Exists(timeout, 0.3):
        return dialog
    return wait_window(title, timeout=3)


def product_row(db_path: str, name: str) -> tuple[str, str] | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT building, research FROM products "
                           "WHERE name = ? AND quality = ''", (name,)).fetchone()
        return tuple(row) if row else None
    finally:
        conn.close()


def status_text(main_window) -> str:
    bar = main_window.StatusBarControl(searchDepth=2)
    if not bar.Exists(2, 0.2):
        return ""
    parts = [bar.Name or ""]
    for child in bar.GetChildren():
        parts.append(child.Name or "")
    return " ".join(p for p in parts if p)


def confirm_dialog(dialog, box) -> None:
    """Enter в полето — както човек потвърждава диалога на Windows."""
    time.sleep(0.4)
    box.SetFocus()
    auto.SendKeys("{Enter}", waitTime=1.5)


class App:
    """Едно пускане на приложението с отделна папка за данни."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.workdir = tempfile.mkdtemp(prefix=f"kapilands-{label}-")
        self.db_path = os.path.join(self.workdir, "kapilands.db")
        env = dict(os.environ, KAPILANDS_DATA_DIR=self.workdir, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--db",
                                      self.db_path, "--allow-multiple"], env=env)
        self.window = wait_window(TITLE, timeout=30)
        if self.window is None:
            raise RuntimeError("прозорецът не се появи")
        self.window.SetActive()
        time.sleep(1.5)

    def catalog(self) -> None:
        self.window.SetActive()
        auto.SendKeys("{Ctrl}3", waitTime=1.2)

    def button(self, name: str):
        return self.window.ButtonControl(searchDepth=6, Name=name)

    def import_file(self, path: Path) -> str:
        self.catalog()
        button = self.button("Внеси списък (TXT)")
        if not check(button.Exists(5, 0.3), f"{self.label}: има бутон „Внеси списък (TXT)“"):
            return ""
        button.GetInvokePattern().Invoke()
        dialog = find_dialog(self.window, IMPORT_TITLE)
        if not check(dialog is not None, f"{self.label}: отвори се диалогът за внос"):
            return ""
        name_box = dialog.EditControl(searchDepth=6, AutomationId="1148")
        name_box.Exists(5, 0.3)
        name_box.GetValuePattern().SetValue(str(path))
        confirm_dialog(dialog, name_box)
        check(not dialog.Exists(1, 0.2), f"{self.label}: диалогът за внос се затвори")
        return status_text(self.window)

    def export_to(self, folder: Path) -> str:
        self.catalog()
        button = self.button("Изнеси списъци (TXT)")
        if not check(button.Exists(5, 0.3), f"{self.label}: има бутон „Изнеси списъци (TXT)“"):
            return ""
        button.GetInvokePattern().Invoke()
        dialog = find_dialog(self.window, EXPORT_TITLE)
        if not check(dialog is not None, f"{self.label}: отвори се диалогът за папка"):
            return ""
        # Модерният избор на папка: поле „Папка:“ (1152) и бутон „Избор на папка“ (1).
        box = dialog.EditControl(searchDepth=8, AutomationId="1152")
        if not box.Exists(3, 0.3):
            box = dialog.EditControl(searchDepth=8, AutomationId="1148")
        box.GetValuePattern().SetValue(str(folder))
        confirm_dialog(dialog, box)
        if dialog.Exists(0.5, 0.2):  # Enter само влезе в папката — „Избор на папка“
            ok = dialog.Control(searchDepth=8, AutomationId="1")
            if ok.Exists(2, 0.2):
                ok.GetPattern(auto.PatternId.InvokePattern).Invoke()
                time.sleep(1.5)
        check(not dialog.Exists(1, 0.2), f"{self.label}: диалогът за папка се затвори")
        return status_text(self.window)

    def has_column(self, title: str) -> bool:
        self.catalog()
        listbox = self.window.ListControl(searchDepth=6, SubName="Продукти")
        if not listbox.Exists(5, 0.3):
            return False
        header = listbox.HeaderItemControl(searchDepth=3, Name=title)
        return header.Exists(2, 0.2)

    def close(self) -> None:
        try:
            self.window.SetActive()
            auto.SendKeys("{Alt}{F4}", waitTime=1)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", default="",
                        help="Производство.txt за внос на компютър А (по избор)")
    args = parser.parse_args()

    files = Path(tempfile.mkdtemp(prefix="kapilands-files-"))
    own = files / "моя_наука.txt"
    own.write_text("изследват се продуктите в\n\nмедийна\nбензин\n", encoding="utf-8")
    transfer = files / "флашка"
    transfer.mkdir()

    print("Компютър А", flush=True)
    a = App("компютър А")
    try:
        check(a.has_column("Наука"), "компютър А: в каталога има колона „Наука“")
        check(product_row(a.db_path, "Бензин") == ("Химически фабрики", "Химическа"),
              "компютър А: нова инсталация — Бензин е в наука Химическа")
        check(product_row(a.db_path, "Реклами") == ("ТВ станция", "Медийна"),
              "компютър А: нова инсталация — Реклами: ТВ станция, Медийна")

        said = a.import_file(own)
        check("Внесени 1 продукт в 1 наука" in said, f"компютър А: съобщението е „{said}“")
        check(product_row(a.db_path, "Бензин")[1] == "Медийна",
              "компютър А: след вноса Бензин е в наука Медийна")

        if args.production:
            said = a.import_file(Path(args.production))
            check("сгради" in said or "сграда" in said, f"компютър А: внос на Производство.txt — „{said}“")
            check(product_row(a.db_path, "Бензин")[0] == "Фабрика",
                  "компютър А: след Производство.txt Бензин е във „Фабрика“")

        said = a.export_to(transfer)
        check("Изнесени" in said, f"компютър А: съобщението е „{said}“")
        exported = sorted(p.name for p in transfer.iterdir())
        check(exported == ["Изследвания.txt", "Производство.txt"],
              f"компютър А: изнесени файлове {exported}")
    finally:
        a.close()

    print("Компютър Б", flush=True)
    b = App("компютър Б")
    try:
        check(product_row(b.db_path, "Бензин")[1] == "Химическа",
              "компютър Б: нова инсталация — Бензин е в наука Химическа (вграденото)")
        said = b.import_file(transfer / "Изследвания.txt")
        check("Внесени" in said and "наук" in said, f"компютър Б: съобщението е „{said}“")
        check(product_row(b.db_path, "Бензин")[1] == "Медийна",
              "компютър Б: промяната от компютър А е пренесена — Бензин е в Медийна")
        if args.production:
            said = b.import_file(transfer / "Производство.txt")
            check(product_row(b.db_path, "Бензин")[0] == "Фабрика",
                  "компютър Б: сградата от компютър А е пренесена — Бензин във „Фабрика“")
    finally:
        b.close()

    failed = [text for ok, text in results if not ok]
    print(f"\n{len(results) - len(failed)} от {len(results)} проверки минаха.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
