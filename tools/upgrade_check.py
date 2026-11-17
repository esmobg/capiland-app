"""Проверка на обновяване: стар инсталатор → нов инсталатор върху него.

Какво прави:

1. Инсталира старата версия тихо във временна папка.
2. Копира данни от 2.0 във временна папка с данни (по подразбиране — копие на
   ``%APPDATA%\\KapilandsTimer``; оригиналът само се чете и накрая се
   проверява по SHA256, че не е пипнат). В копието на настройките звукът,
   известията, говорът и глобалните клавиши са изключени — иначе старите
   таймери ще зазвънят.
3. Пуска старото приложение веднъж и го затваря — както би го ползвал клиентът.
4. Пуска новия инсталатор тихо **без** ``/DIR`` — трябва сам да намери
   старата папка и да я обнови.
5. Пуска новото приложение с същите данни, отива в „Каталог“ (Ctrl+3) и
   проверява колоната „Наука“; после втори път, за да види, че
   допълването на каталога е еднократно.
6. Сравнява базата преди и след: таймери, компании, история, цени и
   времена — нищо не се губи; новите продукти и науки са добавени.
7. Деинсталира и проверява, че не остава нищо.

Употреба:
    python tools/upgrade_check.py --old път\\Kapilands-Taymer-2.0-Setup.exe
        [--new dist\\Kapilands-Taymer-2.2-Setup.exe] [--data папка-с-данни]
Докато работи (около минута), не пиши на клавиатурата.
Изход 0 = обновяването е чисто.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from installer_check import registry_entry, stop_processes_under  # noqa: E402

TITLE = "Kapilands Таймер"
QUIET = {"sound_enabled": False, "toast_enabled": False, "speech_mode": "never",
         "global_hotkeys": False}
TIMER_KEYS = ("id", "product", "quality", "type", "quantity", "line", "world", "building",
              "start_at", "end_at", "duration_sec", "status", "repeat_enabled",
              "cycles_planned", "cycle_no", "note")
PRODUCT_KEEP = ("default_type", "default_duration_sec", "default_quantity",
                "unit_cost", "unit_price", "note")

results: list[tuple[bool, str]] = []


def check(ok: bool, text: str) -> bool:
    results.append((bool(ok), text))
    print(("  ОК      " if ok else "  ГРЕШКА  ") + text, flush=True)
    return bool(ok)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        def rows(table: str) -> list[dict]:
            return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
        return {
            "timers": rows("timers"),
            "accounts": rows("accounts"),
            "history": rows("history"),
            "products": rows("products"),
            "meta": dict(conn.execute("SELECT key, value FROM meta").fetchall()),
            "product_columns": [r[1] for r in conn.execute("PRAGMA table_info(products)")],
        }
    finally:
        conn.close()


def silent(setup: Path, *extra: str) -> int:
    return subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                           "/NOICONS", *extra], timeout=300).returncode


def run_app(exe: Path, data: Path, label: str, look_at_catalog: bool = False) -> None:
    env = dict(os.environ, KAPILANDS_DATA_DIR=str(data))
    app = subprocess.Popen([str(exe), "--allow-multiple"], env=env)
    window = auto.WindowControl(searchDepth=1, SubName=TITLE)
    started = check(window.Exists(40, 0.5), f"{label}: приложението се стартира")
    try:
        if started:
            time.sleep(3)
            if look_at_catalog:
                window.SetActive()
                auto.SendKeys("{Ctrl}3", waitTime=1.5)
                listbox = window.ListControl(searchDepth=6, SubName="Продукти")
                header = listbox.HeaderItemControl(searchDepth=3, Name="Наука")
                check(listbox.Exists(5, 0.3) and header.Exists(3, 0.2),
                      f"{label}: в „Каталог“ има колона „Наука“")
            window.GetWindowPattern().Close()  # .exe от PyInstaller е два процеса
            time.sleep(1)
            # При изтекли таймери може да има въпрос при затваряне — Enter го потвърждава.
            if window.Exists(1, 0.2):
                auto.SendKeys("{Enter}", waitTime=1)
    finally:
        try:
            app.wait(timeout=20)
        except subprocess.TimeoutExpired:
            app.kill()
        stop_processes_under(exe.parent)
        time.sleep(2)


def compare(before: dict, after: dict) -> None:
    check(after["meta"].get("schema_version") == "3",
          f"базата е надградена до версия 3 (беше {before['meta'].get('schema_version')})")
    check("research" in after["product_columns"], "в продуктите има колона за наука")
    check(after["meta"].get("catalog_v3") == "1", "каталогът е допълнен (catalog_v3)")

    def pick(rows, keys):
        return [{k: r[k] for k in keys} for r in rows]

    check(pick(after["timers"], TIMER_KEYS) == pick(before["timers"], TIMER_KEYS),
          f"таймерите са същите ({len(before['timers'])})")
    check(after["accounts"] == before["accounts"],
          f"компаниите са същите ({len(before['accounts'])})")
    check(after["history"] == before["history"],
          f"историята е същата ({len(before['history'])})")

    old = {(p["name"].lower(), p["quality"].lower()): p for p in before["products"]}
    new = {(p["name"].lower(), p["quality"].lower()): p for p in after["products"]}
    missing = [k for k in old if k not in new]
    check(not missing, f"нито един стар продукт не е изчезнал ({len(old)})"
          + (f" — липсват {missing[:5]}" if missing else ""))
    changed = []
    for key, p in old.items():
        q = new.get(key)
        if q is None:
            continue
        if any(p[f] != q[f] for f in PRODUCT_KEEP):
            changed.append(p["name"])
        for f in ("category", "building"):
            if p[f].strip() and p[f] != q[f]:
                changed.append(f"{p['name']} ({f})")
    check(not changed, "времена, цени, бележки, попълнени категории и сгради не са пипнати"
          + (f" — променени: {changed[:5]}" if changed else ""))
    added = len(new) - len(old)
    check(added > 0, f"добавени нови продукти от списъците: {added}")
    with_research = sum(1 for p in after["products"] if p.get("research"))
    check(with_research > 90, f"продукти с наука: {with_research}")
    bensin = new.get(("бензин", ""))
    check(bensin is not None and bensin["research"] == "Химическа",
          "Бензин е в наука „Химическа“")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", required=True, help="инсталатор на старата версия")
    parser.add_argument("--new", default=str(ROOT / "dist" / "Kapilands-Taymer-2.2-Setup.exe"))
    parser.add_argument("--data", default=str(Path(os.environ["APPDATA"]) / "KapilandsTimer"),
                        help="папка с данни от старата версия (само се чете)")
    args = parser.parse_args()
    old_setup, new_setup = Path(args.old).resolve(), Path(args.new).resolve()
    source = Path(args.data)

    if registry_entry():
        print("Приложението вече е инсталирано — проверката спира, за да не го развали.")
        return 2

    originals = {p.name: sha256(p) for p in source.iterdir() if p.is_file()} if source.exists() else {}
    work = Path(tempfile.mkdtemp(prefix="kapilands-upgrade-"))
    target = work / "KapilandsTimer"
    data = work / "data"
    data.mkdir()
    for name in ("kapilands.db", "settings.json"):
        if (source / name).exists():
            shutil.copy2(source / name, data / name)
    settings_path = data / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    settings.update(QUIET)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Данни: копие от {source} ({len(originals)} файла)\n")

    try:
        print("Стара версия", flush=True)
        check(silent(old_setup, f"/DIR={target}") == 0, f"{old_setup.name}: тихо инсталиране")
        entry = registry_entry() or {}
        old_version = entry.get("DisplayVersion")
        check(bool(old_version), f"в „Приложения“: {entry.get('DisplayName')}")
        exe = target / "Kapilands-Taymer.exe"
        run_app(exe, data, f"версия {old_version}")
        before = snapshot(data / "kapilands.db")
        print(f"  база преди: {len(before['timers'])} таймера, {len(before['accounts'])} компании, "
              f"{len(before['products'])} продукта, схема {before['meta'].get('schema_version')}")

        print("\nОбновяване", flush=True)
        check(silent(new_setup) == 0, f"{new_setup.name}: тихо инсталиране върху старата")
        entry = registry_entry() or {}
        new_version = entry.get("DisplayVersion")
        check(new_version not in (None, old_version), f"в „Приложения“: {entry.get('DisplayName')}")
        location = Path(entry.get("InstallLocation", "")).resolve()
        check(location == target.resolve(), f"обновено на същото място ({location})")
        built = ROOT / "dist" / "Kapilands-Taymer.exe"
        if built.exists():
            check(sha256(exe) == sha256(built), "инсталираният .exe е новият от dist")
        check(len(list(target.glob("unins*.exe"))) == 1, "един деинсталатор, не два")

        print("\nНова версия", flush=True)
        run_app(exe, data, f"версия {new_version}", look_at_catalog=True)
        after = snapshot(data / "kapilands.db")
        compare(before, after)
        kept = json.loads(settings_path.read_text(encoding="utf-8"))
        lost = [k for k, v in settings.items() if kept.get(k) != v]
        check(not lost, "настройките са запазени" + (f" — променени: {lost}" if lost else ""))

        run_app(exe, data, f"версия {new_version}, второ пускане")
        again = snapshot(data / "kapilands.db")
        check(len(again["products"]) == len(after["products"]),
              "второ пускане не добавя нищо повторно")
    finally:
        print("\nДеинсталиране", flush=True)
        stop_processes_under(target)
        uninstaller = target / "unins000.exe"
        if uninstaller.exists():
            subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                           timeout=120)
            for _ in range(30):
                if not (target / "Kapilands-Taymer.exe").exists() and registry_entry() is None:
                    break
                time.sleep(1)
        check(registry_entry() is None and not (target / "Kapilands-Taymer.exe").exists(),
              "деинсталирано, без запис в „Приложения“")
        check((data / "kapilands.db").exists(), "данните остават след деинсталиране")
        now = {p.name: sha256(p) for p in source.iterdir() if p.is_file()} if source.exists() else {}
        check(now == originals, f"оригиналните ти данни в {source} не са пипнати")

    failed = [t for ok, t in results if not ok]
    print(f"\n{len(results) - len(failed)} от {len(results)} проверки минаха.")
    print(f"Работна папка: {work}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
