"""Известяване: Windows toast + звуков сигнал.

Три варианта за toast, пробват се по ред:

1. ``winotify`` (ако е инсталиран с ``pip install winotify``);
2. вграден PowerShell скрипт — не изисква нищо допълнително;
3. резервна функция, подадена от интерфейса (прозорец в приложението).

Приложението работи и без външни библиотеки.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from . import config

# Скриване на конзолния прозорец при стартиране на PowerShell.
_CREATE_NO_WINDOW = 0x08000000

_PS_SCRIPT = r"""
param(
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$Message,
    [string]$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
)
try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime]
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $nodes = $template.GetElementsByTagName('text')
    [void]$nodes.Item(0).AppendChild($template.CreateTextNode($Title))
    [void]$nodes.Item(1).AppendChild($template.CreateTextNode($Message))
    $toast = New-Object Windows.UI.Notifications.ToastNotification $template
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
"""


def _script_path() -> Path:
    """Записва PowerShell скрипта при първо ползване (с BOM заради кирилицата)."""
    path = config.data_dir() / "toast.ps1"
    try:
        if not path.exists() or path.read_text(encoding="utf-8-sig") != _PS_SCRIPT:
            path.write_text(_PS_SCRIPT, encoding="utf-8-sig")
    except OSError:
        pass
    return path


class Notifier:
    """Изпраща известия; помни кой начин работи, за да не пробва всеки път."""

    def __init__(self, app_name: str = config.APP_TITLE,
                 fallback=None, enabled: bool = True) -> None:
        self.app_name = app_name
        self.fallback = fallback
        self.enabled = enabled
        self._backend: str | None = None
        self.last_error: str = ""

    # -------------------------------------------------- публичен интерфейс

    def notify(self, title: str, message: str, urgent: bool = False) -> str:
        """Показва известие. Връща името на използвания начин."""
        if not self.enabled:
            return "off"
        if sys.platform != "win32":
            return self._use_fallback(title, message)

        # Работилият последно начин се пробва пръв, но останалите остават резерва.
        order = ["winotify", "powershell"]
        if self._backend in order:
            order.remove(self._backend)
            order.insert(0, self._backend)

        for backend in order:
            if backend == "winotify" and self._toast_winotify(title, message, urgent):
                self._backend = "winotify"
                return "winotify"
            if backend == "powershell" and self._toast_powershell(title, message):
                self._backend = "powershell"
                return "powershell"
        self._backend = None
        return self._use_fallback(title, message)

    def notify_async(self, title: str, message: str, urgent: bool = False) -> None:
        """Известие в отделна нишка, за да не забива интерфейсът."""
        threading.Thread(
            target=self.notify, args=(title, message, urgent), daemon=True
        ).start()

    # -------------------------------------------------- отделните варианти

    def _toast_winotify(self, title: str, message: str, urgent: bool) -> bool:
        try:
            from winotify import Notification, audio  # type: ignore
        except Exception:
            return False
        try:
            toast = Notification(app_id=self.app_name, title=title, msg=message)
            toast.set_audio(audio.LoopingAlarm2 if urgent else audio.Default, loop=False)
            toast.show()
            return True
        except Exception as exc:  # pragma: no cover - зависи от средата
            self.last_error = f"winotify: {exc}"
            return False

    def _toast_powershell(self, title: str, message: str) -> bool:
        script = _script_path()
        if not script.exists():
            return False
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Title", title, "-Message", message],
                capture_output=True,
                timeout=20,
                creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"powershell: {exc}"
            return False
        if result.returncode != 0:
            self.last_error = "powershell: " + result.stderr.decode(
                "utf-8", "replace").strip()[:300]
            return False
        return True

    def _use_fallback(self, title: str, message: str) -> str:
        if self.fallback is not None:
            try:
                self.fallback(title, message)
                return "fallback"
            except Exception as exc:  # pragma: no cover
                self.last_error = f"fallback: {exc}"
        return "none"


# ------------------------------------------------------------------ звук


def play_sound(sound_file: str = "", enabled: bool = True) -> bool:
    """Звуков сигнал. Празен ``sound_file`` = системният звук на Windows."""
    if not enabled or sys.platform != "win32":
        return False
    try:
        import winsound
    except ImportError:
        return False

    if sound_file and os.path.isfile(sound_file):
        try:
            winsound.PlaySound(
                sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC
            )
            return True
        except RuntimeError:
            pass
    try:
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
        return True
    except RuntimeError:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            return True
        except RuntimeError:
            return False


def play_sound_async(sound_file: str = "", enabled: bool = True) -> None:
    threading.Thread(
        target=play_sound, args=(sound_file, enabled), daemon=True
    ).start()
