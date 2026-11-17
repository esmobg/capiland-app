"""Одит през Windows UI Automation — какво виждат NVDA, JAWS и Narrator.

Пуска приложението с временна база, обхожда дървото на елементите и
проверява, че всеки елемент, до който се стига с клавиатура, има име и
роля. Отваря и диалозите (Ctrl+N, Ctrl+I, F1) и ги затваря с Esc.

Употреба:  python tools/uia_audit.py  [--json отчет.json]
Изход 0 = без проблеми, 1 = има елементи без име.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Роли, които трябва да имат име, ако са достъпни с клавиатура.
NAMED_ROLES = {
    "ButtonControl", "EditControl", "ComboBoxControl", "CheckBoxControl",
    "RadioButtonControl", "ListControl", "TabItemControl", "SpinnerControl",
    "ListItemControl", "MenuItemControl", "DataItemControl", "TreeControl",
}
TITLE = "Kapilands Таймер"


def seed_database(path: str) -> None:
    from kapiland.db import Database
    from kapiland.models import Account, Timer
    from kapiland.timeutil import now

    db = Database(path)
    n = now()
    db.upsert_account(Account(world="Немска двойка", name="Алфа", buildings="Химически фабрики"))
    db.upsert_account(Account(world="Немска двойка", name="Бета"))
    db.add_timer(Timer(product="Бензин", quantity=1000, line="Алфа", world="Немска двойка",
                       building="Химически фабрики", start_at=n - 60, end_at=n - 5,
                       duration_sec=55, notified_at=n))
    db.add_timer(Timer(product="Легла", line="Бета", world="Немска двойка",
                       start_at=n, end_at=n + 7200, duration_sec=7200))
    db.close()


def walk(control, depth=0, out=None, max_depth=25):
    out = [] if out is None else out
    if depth > max_depth:
        return out
    try:
        children = control.GetChildren()
    except Exception:
        return out
    for child in children:
        try:
            info = {
                "role": child.ControlTypeName,
                "name": child.Name or "",
                "focusable": bool(child.IsKeyboardFocusable),
                "offscreen": bool(child.IsOffscreen),
                "enabled": bool(child.IsEnabled),
                "class": child.ClassName,
                "depth": depth,
            }
        except Exception:
            continue
        out.append(info)
        walk(child, depth + 1, out, max_depth)
    return out


def problems_in(elements):
    bad = []
    for element in elements:
        if element["role"] not in NAMED_ROLES:
            continue
        if element["offscreen"] or not element["enabled"]:
            continue
        if element["role"] in ("ListItemControl", "DataItemControl", "MenuItemControl"):
            needs = True
        else:
            needs = element["focusable"]
        if needs and not element["name"].strip():
            bad.append(element)
    return bad


def audit_window(window, label):
    elements = walk(window)
    bad = problems_in(elements)
    named = [e for e in elements if e["role"] in NAMED_ROLES and e["name"].strip()]
    return {"window": label, "elements": elements, "problems": bad,
            "named_count": len(named)}


def wait_window(name_part, timeout=15, class_name=None):
    end = time.time() + timeout
    while time.time() < end:
        for window in auto.GetRootControl().GetChildren():
            try:
                if name_part in (window.Name or "") and (class_name is None or window.ClassName == class_name):
                    return window
            except Exception:
                continue
        time.sleep(0.3)
    return None


class NotInFront(RuntimeError):
    """Отпред е чужд прозорец — клавишите не се пращат, за да не отидат в него."""


def in_front(pid: int) -> bool:
    try:
        return auto.GetForegroundControl().ProcessId == pid
    except Exception:
        return False


def press(pid: int, window, keys: str, wait: float = 0.8) -> None:
    """Праща клавиши само ако отпред е прозорец на проверяваното приложение."""
    if not in_front(pid):
        try:
            window.SetActive()
        except Exception:
            pass
        time.sleep(0.4)
    if not in_front(pid):
        raise NotInFront(keys)
    auto.SendKeys(keys, waitTime=wait)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="kapilands-uia")
    db_path = os.path.join(workdir, "audit.db")
    seed_database(db_path)
    env = dict(os.environ, KAPILANDS_DATA_DIR=workdir, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--db", db_path,
                             "--allow-multiple"], env=env)
    reports = []
    try:
        main_window = wait_window(TITLE, timeout=30)
        if main_window is None:
            print("Прозорецът не се появи.")
            return 2
        main_window.SetActive()
        time.sleep(1.5)
        reports.append(audit_window(main_window, "Главен прозорец — Таймери"))

        for keys, label, title in (("{Ctrl}n", "Диалог „Нов таймер“", "Нов таймер"),
                                   ("{Ctrl}i", "Диалог „Внос на списък“", "Внос на списък"),
                                   ("{F1}", "Помощ", "Клавишни комбинации")):
            press(proc.pid, main_window, keys)
            dialog = main_window.WindowControl(searchDepth=1, Name=title)
            if not dialog.Exists(8, 0.3):
                dialog = wait_window(title, timeout=5)
            if dialog is None or not dialog.Exists(1, 0.2):
                reports.append({"window": label, "elements": [], "problems": [
                    {"role": "Window", "name": "", "class": "не се отвори"}], "named_count": 0})
                continue
            time.sleep(0.8)
            reports.append(audit_window(dialog, label))
            press(proc.pid, dialog, "{Esc}")
            closed = not dialog.Exists(3, 0.3)
            if not closed:
                reports[-1]["problems"].append({"role": "Window", "name": title,
                                                "class": "Esc не затвори диалога"})

        # Диалозите, които се отварят с бутон от раздела си.
        page_dialogs = {"Компании": ("Нова компания", "Нова компания"),
                        "Каталог": ("Нов продукт", "Нов продукт")}
        for index, page in enumerate(("Компании", "Каталог", "История", "Настройки"), start=2):
            press(proc.pid, main_window, "{Ctrl}%d" % index, 1.0)
            reports.append(audit_window(main_window, f"Главен прозорец — {page}"))
            if page not in page_dialogs:
                continue
            button_name, title = page_dialogs[page]
            label = f"Диалог „{title}“"
            button = main_window.ButtonControl(searchDepth=6, Name=button_name)
            if not button.Exists(3, 0.3):
                reports.append({"window": label, "elements": [], "problems": [
                    {"role": "Button", "name": button_name, "class": "няма такъв бутон"}],
                    "named_count": 0})
                continue
            button.SetFocus()
            press(proc.pid, main_window, "{Enter}")   # с клавиатурата, както го прави човек
            dialog = main_window.WindowControl(searchDepth=1, Name=title)
            if not dialog.Exists(8, 0.3):
                reports.append({"window": label, "elements": [], "problems": [
                    {"role": "Window", "name": "", "class": "не се отвори"}], "named_count": 0})
                continue
            time.sleep(0.8)
            reports.append(audit_window(dialog, label))
            press(proc.pid, dialog, "{Esc}")
            if dialog.Exists(3, 0.3):
                reports[-1]["problems"].append({"role": "Window", "name": title,
                                                "class": "Esc не затвори диалога"})

        # Меню „Файл“: командите се виждат едва когато менюто е отворено.
        main_window.SetActive()
        file_menu = main_window.MenuItemControl(searchDepth=3, Name="Файл")
        if file_menu.Exists(3, 0.2):
            file_menu.GetExpandCollapsePattern().Expand()
            time.sleep(0.6)
            popup = auto.MenuControl(searchDepth=3, Name="Файл")
            target = popup if popup.Exists(2, 0.2) else main_window
            report = audit_window(target, "Меню „Файл“")
            names = {e["name"] for e in report["elements"] if e["role"] == "MenuItemControl"}
            for wanted in ("Изнеси всичко в CSV за друг компютър…",
                           "Внеси от CSV от друг компютър…"):
                if wanted not in names:
                    report["problems"].append({"role": "MenuItemControl", "name": wanted,
                                               "class": "липсва в менюто"})
            reports.append(report)
            press(proc.pid, main_window, "{Esc}{Esc}", 0.6)
    except NotInFront as stopped:
        reports.append({"window": "Проверката е прекъсната", "elements": [], "named_count": 0,
                        "problems": [{"role": "Window", "name": "",
                                      "class": f"отпред е друг прозорец — клавишите {stopped} "
                                               "не са пратени; пусни проверката пак"}]})
    finally:
        # Затваряне без клавиши: Alt+F4 не бива да стигне до чужд прозорец.
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    total_problems = 0
    for report in reports:
        problems = report["problems"]
        total_problems += len(problems)
        print(f"{report['window']}: {report['named_count']} елемента с име, "
              f"{len(problems)} проблема")
        for element in problems:
            print(f"    БЕЗ ИМЕ: {element['role']} ({element.get('class', '')})")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ОБЩО ПРОБЛЕМИ:", total_problems)
    return 0 if total_problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
