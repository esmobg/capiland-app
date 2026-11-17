"""Проверка на инсталатора: съветникът, инсталиране, стартиране, деинсталиране.

Минава през всички страници на съветника с Enter и на всяка проверява през
UI Automation, че бутоните, отметките и полетата имат име (това чете
екранният четец). Инсталира във временна папка, пуска приложението с
временни данни, деинсталира тихо и проверява, че не остава нищо — нито
файлове, нито запис в „Приложения“.

Употреба:  python tools/installer_check.py [dist\\Kapilands-Taymer-2.2-Setup.exe]
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "{6E558729-A64F-4E92-8E54-CAF34CB4C37E}_is1"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID
NAMED = {"ButtonControl", "CheckBoxControl", "RadioButtonControl", "EditControl", "ComboBoxControl"}


def registry_entry() -> dict | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            values = {}
            for name in ("DisplayName", "DisplayVersion", "InstallLocation", "UninstallString"):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
            return values
    except OSError:
        return None


def stop_processes_under(folder: Path) -> None:
    """Спира всеки процес, стартиран от папката (иначе файлът остава заключен)."""
    script = ("Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:KL_DIR) } "
              "| Stop-Process -Force")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                   env=dict(os.environ, KL_DIR=str(folder)), capture_output=True, timeout=30)


def audit(window) -> tuple[list[str], list[str]]:
    named, missing = [], []

    def walk(control, depth=0):
        if depth > 12:
            return
        for child in control.GetChildren():
            try:
                role, name = child.ControlTypeName, (child.Name or "").strip()
                visible = not child.IsOffscreen
            except Exception:
                continue
            if role in NAMED and visible:
                (named if name else missing).append(f"{role}: {name}" if name else f"{role} ({child.ClassName})")
            walk(child, depth + 1)

    walk(window)
    return named, missing


def main() -> int:
    setup = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist" / "Kapilands-Taymer-2.2-Setup.exe").resolve()
    if registry_entry():
        print("Приложението вече е инсталирано — проверката спира, за да не го развали.")
        return 2
    target = Path(tempfile.mkdtemp(prefix="kapilands-install")) / "KapilandsTimer"
    problems: list[str] = []

    proc = subprocess.Popen([str(setup), f"/DIR={target}", "/NOICONS"])
    try:
        wizard = auto.WindowControl(searchDepth=1, SubName="Kapilands")
        if not wizard.Exists(30, 0.5):
            print("Съветникът не се появи.")
            return 2
        for page in range(1, 10):
            wizard.SetActive()
            time.sleep(1.2)
            texts = [c.Name for c in wizard.GetChildren() if c.Name][:3]
            named, missing = audit(wizard)
            print(f"Страница {page}: {len(named)} елемента с име, {len(missing)} без име")
            for item in named:
                print(f"    {item}")
            problems += [f"страница {page}: {m}" for m in missing]
            finish = wizard.ButtonControl(searchDepth=6, SubName="Готово")
            if finish.Exists(0.5, 0.1):
                launch = wizard.CheckBoxControl(searchDepth=6, SubName="Стартирай")
                if launch.Exists(0.5, 0.1):
                    print("    отметка за стартиране:", launch.Name)
                    if launch.GetTogglePattern().ToggleState == 1:
                        launch.Click(simulateMove=False)  # Toggle() на Inno Setup връща грешка
                        time.sleep(0.5)
                finish.Click(simulateMove=False)
                break
            auto.SendKeys("{Enter}", waitTime=0.3)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
        leftover = auto.WindowControl(searchDepth=1, SubName="Kapilands")
        if leftover.Exists(1, 0.2) and "Таймер" not in (leftover.Name or ""):
            leftover.GetWindowPattern().Close()

    exe = target / "Kapilands-Taymer.exe"
    print("\nИнсталирани файлове:")
    for path in sorted(target.rglob("*")):
        if path.is_file():
            print(f"    {path.relative_to(target)}  ({path.stat().st_size // 1024} KB)")
    if not exe.exists():
        problems.append("няма инсталиран Kapilands-Taymer.exe")
    entry = registry_entry()
    print("Запис в „Приложения“:", entry)
    if not entry or entry.get("DisplayVersion") != "2.2":
        problems.append("липсва или е грешен записът за деинсталиране")

    if exe.exists():
        data = tempfile.mkdtemp(prefix="kapilands-install-data")
        env = dict(os.environ, KAPILANDS_DATA_DIR=data)
        app = subprocess.Popen([str(exe), "--allow-multiple"], env=env)
        window = auto.WindowControl(searchDepth=1, SubName="Kapilands Таймер")
        started = window.Exists(30, 0.5)
        print("Инсталираното приложение се стартира:", started)
        if not started:
            problems.append("инсталираното приложение не се стартира")
        # .exe от PyInstaller е два процеса — затваря се прозорецът, не родителят.
        if started:
            window.GetWindowPattern().Close()
        try:
            app.wait(timeout=20)
        except subprocess.TimeoutExpired:
            app.kill()
        stop_processes_under(target)
        time.sleep(2)

    uninstaller = target / "unins000.exe"
    if uninstaller.exists():
        subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
        for _ in range(30):
            if not exe.exists() and registry_entry() is None:
                break
            time.sleep(1)
    left = [str(p) for p in target.rglob("*")] if target.exists() else []
    print("След деинсталиране — останали файлове:", left or "няма",
          "| запис:", registry_entry() or "няма")
    if exe.exists() or registry_entry() is not None:
        problems.append("деинсталирането не изчисти всичко")

    print("\nПРОБЛЕМИ:", problems or "няма")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
