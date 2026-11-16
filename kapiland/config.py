"""Пътища до данните и потребителски настройки."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "KapilandsTimer"
APP_TITLE = "Kapilands Таймер"
APP_VERSION = "2.1.0"


def data_dir() -> Path:
    r"""Папката с базата и настройките (%APPDATA%\KapilandsTimer).

    ``KAPILANDS_DATA_DIR`` я пренасочва — за тестове и проверки, без да се
    пипа APPDATA (там Python държи и инсталираните библиотеки).
    """
    override = os.environ.get("KAPILANDS_DATA_DIR")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "kapilands.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


DEFAULTS: dict = {
    "sound_enabled": True,
    "sound_file": "",              # празно = системен звук на Windows
    "toast_enabled": True,
    "prewarn_minutes": 0,          # 0 = без предварително предупреждение
    "repeat_reminder_minutes": 5,  # 0 = без повтаряне на известието
    "date_format": "%d.%m.%Y %H:%M",
    "default_lines": 4,
    "collision_window_minutes": 5,
    "prep_lead_minutes": 0,        # време за подготовка преди края
    "window_geometry": "",
    "last_type": "production",
    # достъпност
    "theme": "system",         # system | light | dark
    "font_scale": 100,         # 100 – 200 %
    "speech_mode": "auto",     # auto | always | never — говор през четеца
    "reader_mode": "auto",     # auto | on | off — списък без тиктакащи секунди
    "global_hotkeys": True,    # Ctrl+Alt+K и Ctrl+Alt+J от всеки прозорец
    "toast_when_speaking": False,  # и Windows известие, когато четецът е говорил
    "default_world": "",
}


class Settings:
    """Настройки в JSON файл; непознати ключове се игнорират."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self._path = Path(path) if path else settings_path()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> "Settings":
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULTS:
                    self._data[key] = value
        return self

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def __getitem__(self, key: str):
        return self.get(key)

    def __setitem__(self, key: str, value) -> None:
        self.set(key, value)

    def as_dict(self) -> dict:
        return dict(self._data)
