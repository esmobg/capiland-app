"""Kapilands Таймер — стартиране на приложението.

Работа:
    python main.py                 обикновено стартиране
    python main.py --db път.db     друга база (например за проба)
    python main.py --reset-window  забравя запомнените размери на прозореца
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kapiland import config  # noqa: E402
from kapiland.ui.app import KapilandsApp  # noqa: E402

_MUTEX_NAME = "Global\\KapilandsTimerSingleInstance"
_ERROR_ALREADY_EXISTS = 183


def _already_running() -> bool:
    """Пази от две едновременно пуснати копия (двойни известия)."""
    if sys.platform != "win32":
        return False
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return False
        return ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS
    except (AttributeError, OSError):
        return False


def _enable_dpi_awareness() -> None:
    """Ясен текст на екрани с мащабиране (важно за четимостта)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kapilands-timer", description=config.APP_TITLE)
    parser.add_argument("--db", default=None,
                        help="път до базата данни (по подразбиране в %%APPDATA%%)")
    parser.add_argument("--reset-window", action="store_true",
                        help="забравя запомнените размери на прозореца")
    parser.add_argument("--allow-multiple", action="store_true",
                        help="позволява второ копие на приложението")
    args = parser.parse_args(argv)

    if not args.allow_multiple and _already_running():
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Kapilands Таймер вече работи.\n"
                "Потърсете прозореца в лентата на задачите.",
                config.APP_TITLE, 0x40)
        except (AttributeError, OSError):
            print("Приложението вече работи.")
        return 0

    _enable_dpi_awareness()

    if args.reset_window:
        settings = config.Settings()
        settings.set("window_geometry", "")
        settings.save()

    try:
        app = KapilandsApp(args.db)
    except Exception:  # pragma: no cover - показваме грешката, вместо да изчезнем
        _fatal(traceback.format_exc())
        return 1

    app.run()
    return 0


def _fatal(details: str) -> None:
    message = "Приложението не можа да стартира.\n\n" + details[-1500:]
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, config.APP_TITLE, 0x10)
            return
        except (AttributeError, OSError):
            pass
    sys.stderr.write(message + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
