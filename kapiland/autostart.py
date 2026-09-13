"""Стартиране заедно с Windows — пряк път в папката „Автоматично стартиране“.

Прави се само при изрично включване от потребителя в Настройки.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "Kapilands Таймер.lnk"
_CREATE_NO_WINDOW = 0x08000000


def shortcut_path() -> Path:
    startup = Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
    return startup / SHORTCUT_NAME


def launch_target() -> tuple[str, str, str]:
    """(програма, аргументи, работна папка) — за .exe или за изходния код."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)
    project = Path(__file__).resolve().parents[1]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else Path(sys.executable)
    return str(runner), f'"{project / "main.py"}"', str(project)


def is_enabled() -> bool:
    return shortcut_path().exists()


def enable() -> tuple[bool, str]:
    target, arguments, work_dir = launch_target()
    shortcut = shortcut_path()
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:KL_LNK); "
        "$s.TargetPath = $env:KL_TARGET; $s.Arguments = $env:KL_ARGS; "
        "$s.WorkingDirectory = $env:KL_DIR; $s.Description = 'Kapilands Таймер'; $s.Save()"
    )
    env = dict(os.environ, KL_LNK=str(shortcut), KL_TARGET=target,
               KL_ARGS=arguments, KL_DIR=work_dir)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=25, env=env,
            creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Не можах да създам прекия път: {exc}"
    if result.returncode != 0 or not shortcut.exists():
        detail = result.stderr.decode("utf-8", "replace").strip()[:200]
        return False, "Не можах да създам прекия път. " + detail
    return True, "Приложението ще се стартира заедно с Windows."


def disable() -> tuple[bool, str]:
    try:
        shortcut_path().unlink(missing_ok=True)
    except OSError as exc:
        return False, f"Не можах да премахна прекия път: {exc}"
    return True, "Автоматичното стартиране е изключено."
