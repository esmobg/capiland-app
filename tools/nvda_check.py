"""Проверка с истински NVDA — беззвучно, с отделни настройки.

Какво прави:

1. Създава временна папка с настройки на NVDA: синтезатор „silence“ (без
   звук), без приветствие, без проверка за обновления. Настройките на
   потребителя не се пипат.
2. Пуска инсталирания NVDA с тези настройки и лог на ниво „вход/изход“ —
   там NVDA записва всичко, което би изговорил („Speaking [...]“).
3. Пуска приложението с временна база и натиска клавиши както човек:
   списък, F3, F4, Ctrl+N, Ctrl+I, Ctrl+2, изчаква таймер да стане готов,
   после Ctrl+Alt+K **от друг прозорец**, накрая Ctrl+3 (Каталог) и Enter
   върху продукт — колоната и полето „Наука“.
4. Спира NVDA и приложението и проверява лога.

Употреба:  python tools/nvda_check.py [--report отчет.txt]
           python tools/nvda_check.py --voice gergana
              — със звук, през българския глас „Гергана“ (BACL SpeechLab 2.0,
                32-битов SAPI 5) и проверка, че NVDA го е заредил.
Докато работи (~2 минути), не пиши на клавиатурата.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kapiland.speech import NvdaBackend  # noqa: E402

NVDA_PATHS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "NVDA" / "nvda.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVDA" / "nvda.exe",
]
TITLE = "Kapilands Таймер"
NVDA_INI = """[general]
\tlanguage = bg
\tshowWelcomeDialogAtStartup = False
\taskToExit = False
\tplayStartAndExitSounds = False
[speech]
\tsynth = silence
[update]
\tautoCheck = False
\tstartupNotification = False
\taskedAllowUsageStats = True
\tallowUsageStats = False
[presentation]
\treportNotifications = True
"""
# Гласове за --voice: (синтезатор на NVDA, Id на гласа в SAPI).
VOICES = {
    "gergana": ("sapi5_32",
                r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\Gergana"),
}


def nvda_ini(voice: str = "") -> str:
    """Настройките за проверката — беззвучно или с избрания глас."""
    if not voice:
        return NVDA_INI
    synth, token = VOICES[voice]
    return NVDA_INI.replace(
        "\tsynth = silence\n",
        f"\tsynth = {synth}\n\t[[{synth}]]\n\t\tvoice = {token}\n")


HELPER = r"""
import tkinter as tk
root = tk.Tk()
root.title("Друг прозорец за проверка")
tk.Label(root, text="Друг прозорец").pack(padx=40, pady=30)
root.after(60000, root.destroy)
root.mainloop()
"""


def start_nvda(nvda: Path, arguments: str) -> None:
    os.startfile(str(nvda), "open", arguments)  # type: ignore[attr-defined]


def find_nvda() -> Path:
    for path in NVDA_PATHS:
        if path.exists():
            return path
    raise SystemExit("NVDA не е инсталиран.")


def seed(db_path: str, ready_in: int) -> None:
    from kapiland.db import Database
    from kapiland.models import Account, Timer
    from kapiland.timeutil import now

    db = Database(db_path)
    n = now()
    db.upsert_account(Account(world="Немска двойка", name="Алфа", buildings="Химически фабрики"))
    db.upsert_account(Account(world="Немска двойка", name="Бета"))
    db.add_timer(Timer(product="Бензин", quantity=1000, line="Алфа", world="Немска двойка",
                       building="Химически фабрики", start_at=n - 3600, end_at=n + ready_in,
                       duration_sec=3600 + ready_in))
    db.add_timer(Timer(product="Легла", line="Бета", world="Немска двойка",
                       start_at=n, end_at=n + 7200, duration_sec=7200))
    db.add_timer(Timer(type="research", world="Английска единица",
                       start_at=n, end_at=n + 3 * 3600, duration_sec=3 * 3600))
    db.close()


def spoken_lines(log_path: Path) -> list[tuple[float, str]]:
    """Всички изговорени фрази от лога на NVDA, с часа им."""
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = []
    for match in re.finditer(r"\((\d\d):(\d\d):(\d\d)\.(\d+)\).*?\n(?:Speaking|Speech) (\[.*?\])\s*$",
                             text, re.MULTILINE | re.DOTALL):
        stamp = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        raw = match.group(5)
        # Командите не са изговорен текст: LangChangeCommand ('bg'),
        # CancellableSpeech (still valid) и подобни.
        cleaned = re.sub(r"\w+(?:Command|Speech)\s*\([^)]*\)", "", raw)
        try:
            items = ast.literal_eval(cleaned)
            words = [str(i) for i in items if isinstance(i, str)]
        except (ValueError, SyntaxError):
            words = re.findall(r"'([^']*)'", cleaned)
        phrase = " ".join(w.strip() for w in words if w.strip())
        if phrase:
            result.append((stamp, phrase))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="")
    parser.add_argument("--exe", default="", help="проверка на компилирания .exe")
    parser.add_argument("--voice", default="", choices=["", *VOICES],
                        help="със звук през този глас вместо беззвучно")
    args = parser.parse_args()

    nvda = find_nvda()
    work = Path(tempfile.mkdtemp(prefix="kapilands-nvda"))
    config_dir = work / "nvda-config"
    config_dir.mkdir()
    (config_dir / "nvda.ini").write_text(nvda_ini(args.voice), encoding="utf-8")
    log_path = work / "nvda.log"
    data_dir = work / "app"
    data_dir.mkdir()
    db_path = str(data_dir / "check.db")
    seed(db_path, ready_in=45)

    marks: dict[str, int] = {}
    app = helper = None
    controller = NvdaBackend()

    print(f"Пускам NVDA с глас {args.voice}…" if args.voice else "Пускам NVDA беззвучно…")
    # Инсталираният NVDA е с uiAccess: CreateProcess връща грешка 740, затова
    # се пуска през обвивката на Windows (ShellExecute), както при двоен клик.
    start_nvda(nvda, f'-c "{config_dir}" --log-file="{log_path}" '
                     f'--log-level=12 --disable-addons -r')
    try:
        for _ in range(60):
            if controller.available():
                break
            time.sleep(0.5)
        else:
            print("NVDA не тръгна.")
            return 2
        time.sleep(4)

        print("Пускам приложението…")
        env = dict(os.environ, KAPILANDS_DATA_DIR=str(data_dir), PYTHONIOENCODING="utf-8")
        command = ([str(Path(args.exe).resolve())] if args.exe
                   else [sys.executable, str(ROOT / "main.py")])
        app = subprocess.Popen(command + ["--db", db_path, "--allow-multiple"], env=env)
        window = auto.WindowControl(searchDepth=1, SubName=TITLE)
        if not window.Exists(40, 0.5):
            print("Прозорецът не се появи.")
            return 2
        window.SetActive()
        time.sleep(4)

        def mark(name: str) -> None:
            marks[name] = len(spoken_lines(log_path))

        def press(keys: str, wait: float = 2.0) -> None:
            auto.SendKeys(keys, waitTime=0.1)
            time.sleep(wait)

        mark("list")
        press("{Down}")
        press("{Up}")
        mark("f3")
        press("{F3}", 3)
        mark("f4")
        press("{F4}", 4)
        mark("new")
        press("{Ctrl}n", 3)
        press("{Tab}")
        press("{Esc}", 2)
        mark("import")
        press("{Ctrl}i", 3)
        press("{Esc}", 2)
        mark("accounts")
        press("{Ctrl}2", 3)
        press("{Ctrl}1", 2)
        mark("ready")
        print("Чакам таймерът да стане готов…")
        time.sleep(42)
        mark("hotkey")
        helper = subprocess.Popen([sys.executable, "-c", HELPER])
        other = auto.WindowControl(searchDepth=1, Name="Друг прозорец за проверка")
        if other.Exists(15, 0.3):
            other.SetActive()
            time.sleep(2)
        press("{Ctrl}{Alt}k", 4)
        mark("end")

        # Каталог: колона „Наука“ в реда и полето „Наука:“ в диалога (v2.1).
        window.SetActive()
        time.sleep(2)
        mark("catalog")
        press("{Ctrl}3", 3)
        press("{Down}")
        press("{Up}")
        mark("product")
        press("{Enter}", 3)
        for _ in range(4):  # Име → Качество → Категория → Сграда → Наука
            press("{Tab}", 1.5)
        press("{Esc}", 2)
        mark("catalog_end")
    finally:
        for proc in (helper,):
            if proc is not None and proc.poll() is None:
                proc.kill()
        if app is not None and app.poll() is None:
            try:
                window = auto.WindowControl(searchDepth=1, SubName=TITLE)
                if window.Exists(2, 0.2):
                    window.SetActive()
                    auto.SendKeys("{Alt}{F4}")
                app.wait(timeout=10)
            except Exception:
                app.kill()
        time.sleep(1)
        start_nvda(nvda, "-q")
        time.sleep(3)

    lines = spoken_lines(log_path)
    phrases = [p for _t, p in lines]

    def between(start: str, end: str) -> str:
        return " | ".join(phrases[marks.get(start, 0):marks.get(end, len(phrases))])

    expectations = [
        ("Списък — ред с продукта и колоните", "list", "f3", ["Бензин", "Легла", "Компания:"]),
        ("F3 — подробности с цяло изречение", "f3", "f4", ["остават", "Алфа"]),
        ("F4 — какво следва", "f4", "new", ["Следващо"]),
        ("Ctrl+N — диалогът и полетата", "new", "import", ["Нов таймер", "Свят"]),
        ("Ctrl+I — диалог за внос", "import", "accounts", ["Внос на списък"]),
        ("Ctrl+2 — раздел Компании", "accounts", "ready", ["Компании"]),
        ("Готово — изговорено само", "ready", "hotkey", ["Готово", "Бензин"]),
        ("Ctrl+Alt+K от друг прозорец", "hotkey", "end", ["Готово", "Следващо"]),
        ("Ctrl+3 — Каталог, редът казва и науката", "catalog", "product", ["Продукти", "Наука:"]),
        ("Enter — продукт, полето „Наука:“", "product", "catalog_end",
         ["Редактиране на продукт", "Наука:"]),
    ]
    report = [f"NVDA: {nvda}", f"Лог: {log_path}", ""]
    f3_parts = phrases[marks.get("f3", 0):marks.get("f4", 0)]
    f3_repeats = sum(1 for p in f3_parts if "Производство, Химически фабрики" in p)
    failed = 0
    for label, start, end, needles in expectations:
        heard = between(start, end)
        ok = all(any(n.lower() in part.lower() for part in heard.split(" | ")) for n in needles)
        failed += 0 if ok else 1
        report.append(f"[{'OK' if ok else 'ЛИПСВА'}] {label}")
        report.append(f"      чу: {heard[:400] or '(нищо)'}")
    if args.voice:
        synth, _token = VOICES[args.voice]
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        loaded = f"Loaded synthDriver {synth}" in log
        failed += 0 if loaded else 1
        report.append(f"[{'OK' if loaded else 'НЕ СЕ ЗАРЕДИ'}] NVDA зареди синтезатора {synth} "
                      f"(глас {args.voice})")
        for line in log.splitlines():
            if "synthDriver" in line or ("sapi5" in line.lower() and "ERROR" in line):
                report.append(f"      лог: {line.strip()[:200]}")
    once = f3_repeats == 1
    failed += 0 if once else 1
    report.append(f"[{'OK' if once else 'ПОВТАРЯ СЕ'}] F3 се чува точно веднъж (чу се {f3_repeats} пъти)")
    report.append("")
    report.append("ВСИЧКО, КОЕТО NVDA ИЗГОВОРИ:")
    report.extend(f"  {p}" for p in phrases)
    text = "\n".join(report)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
