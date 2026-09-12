"""Раздел „Настройки“ — известия, достъпност и автоматично стартиране."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import a11y
from ..notify import play_sound

_CREATE_NO_WINDOW = 0x08000000
SHORTCUT_NAME = "Kapilands Таймер.lnk"


class SettingsView(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.settings = app.settings
        self._build()

    # ------------------------------------------------------------- градеж

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        pad = {"padx": 10, "pady": 5}

        # ---------------- известия ----------------
        notify_box = ttk.Labelframe(self, text="Известия", padding=12)
        notify_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        notify_box.columnconfigure(1, weight=1)

        self.toast_var = tk.BooleanVar(value=bool(self.settings.get("toast_enabled", True)))
        ttk.Checkbutton(notify_box, text="Показвай известие на Windows",
                        variable=self.toast_var, command=self._save).grid(
            row=0, column=0, columnspan=2, sticky="w", **pad)

        self.sound_var = tk.BooleanVar(value=bool(self.settings.get("sound_enabled", True)))
        ttk.Checkbutton(notify_box, text="Пускай звуков сигнал",
                        variable=self.sound_var, command=self._save).grid(
            row=1, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(notify_box, text="Собствен звук (.wav):").grid(
            row=2, column=0, sticky="w", **pad)
        sound_row = ttk.Frame(notify_box)
        sound_row.grid(row=2, column=1, sticky="ew", **pad)
        sound_row.columnconfigure(0, weight=1)
        self.sound_file_var = tk.StringVar(value=str(self.settings.get("sound_file", "")))
        ttk.Entry(sound_row, textvariable=self.sound_file_var).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(sound_row, text="Избери…", command=self._pick_sound).grid(
            row=0, column=1, padx=(8, 0))
        ttk.Button(sound_row, text="Пробвай", command=self._test_sound).grid(
            row=0, column=2, padx=(8, 0))

        ttk.Label(notify_box, text="Предупреди ме N минути\nпреди края (0 = не):",
                  justify="left").grid(row=3, column=0, sticky="w", **pad)
        self.prewarn_var = tk.StringVar(value=str(self.settings.get("prewarn_minutes", 0)))
        ttk.Spinbox(notify_box, from_=0, to=1440, textvariable=self.prewarn_var,
                    command=self._save).grid(row=3, column=1, sticky="ew", **pad)

        ttk.Label(notify_box, text="Повтаряй известието на\nN минути (0 = не):",
                  justify="left").grid(row=4, column=0, sticky="w", **pad)
        self.reminder_var = tk.StringVar(
            value=str(self.settings.get("repeat_reminder_minutes", 5)))
        ttk.Spinbox(notify_box, from_=0, to=240, textvariable=self.reminder_var,
                    command=self._save).grid(row=4, column=1, sticky="ew", **pad)

        ttk.Button(notify_box, text="Пробно известие",
                   command=self._test_notification).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad)

        # ---------------- достъпност ----------------
        access = ttk.Labelframe(self, text="Достъпност (WCAG 2.1 AA)", padding=12)
        access.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        access.columnconfigure(1, weight=1)

        ttk.Label(access, text="Цветова тема:").grid(row=0, column=0, sticky="w", **pad)
        self.theme_var = tk.StringVar(
            value=a11y.theme(self.app.theme_name)["label"])
        ttk.Combobox(
            access, textvariable=self.theme_var, state="readonly",
            values=[t["label"] for t in a11y.THEMES.values()],
        ).grid(row=0, column=1, sticky="ew", **pad)
        self.theme_var.trace_add("write", lambda *_a: self._apply_theme())

        ttk.Label(access, text="Размер на текста:").grid(row=1, column=0, sticky="w", **pad)
        self.scale_var = tk.StringVar(value=f"{self.app.style.font_scale}%")
        ttk.Combobox(
            access, textvariable=self.scale_var, state="readonly",
            values=[f"{s}%" for s in a11y.FONT_SCALES],
        ).grid(row=1, column=1, sticky="ew", **pad)
        self.scale_var.trace_add("write", lambda *_a: self._apply_scale())

        ttk.Label(
            access,
            text="Всички цветове са проверени за контраст ≥ 4.5:1 за текст и "
                 "≥ 3:1 за елементи. Състоянията се показват с текст и знак, "
                 "не само с цвят. Нищо не мига.",
            style="Muted.TLabel", wraplength=380, justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", **pad)

        ttk.Button(access, text="Клавишни комбинации (F1)",
                   command=self.app.show_keyboard_help).grid(
            row=3, column=0, columnspan=2, sticky="w", **pad)

        # ---------------- производство ----------------
        work = ttk.Labelframe(self, text="Производство", padding=12)
        work.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        work.columnconfigure(1, weight=1)

        ttk.Label(work, text="Брой линии / фабрики:").grid(
            row=0, column=0, sticky="w", **pad)
        self.lines_var = tk.StringVar(value=str(self.settings.get("default_lines", 4)))
        ttk.Spinbox(work, from_=1, to=50, textvariable=self.lines_var,
                    command=self._save).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(work, text="„Струпване“ при разлика\nпод N минути:",
                  justify="left").grid(row=1, column=0, sticky="w", **pad)
        self.collision_var = tk.StringVar(
            value=str(self.settings.get("collision_window_minutes", 5)))
        ttk.Spinbox(work, from_=0, to=120, textvariable=self.collision_var,
                    command=self._save).grid(row=1, column=1, sticky="ew", **pad)

        ttk.Label(work, text="Време за подготовка\nпреди края (мин.):",
                  justify="left").grid(row=2, column=0, sticky="w", **pad)
        self.prep_var = tk.StringVar(value=str(self.settings.get("prep_lead_minutes", 0)))
        ttk.Spinbox(work, from_=0, to=120, textvariable=self.prep_var,
                    command=self._save).grid(row=2, column=1, sticky="ew", **pad)

        # ---------------- система ----------------
        system = ttk.Labelframe(self, text="Система", padding=12)
        system.grid(row=1, column=1, sticky="nsew", pady=(0, 10))
        system.columnconfigure(0, weight=1)

        self.autostart_var = tk.BooleanVar(value=self._shortcut_path().exists())
        ttk.Checkbutton(
            system, text="Стартирай приложението заедно с Windows",
            variable=self.autostart_var, command=self._toggle_autostart,
        ).grid(row=0, column=0, sticky="w", **pad)

        ttk.Label(system, text=f"Данните се пазят в:\n{self.app.db.path}",
                  style="Muted.TLabel", wraplength=380, justify="left").grid(
            row=1, column=0, sticky="w", **pad)
        ttk.Button(system, text="Отвори папката с данните",
                   command=self._open_data_folder).grid(row=2, column=0, sticky="w", **pad)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel",
                  wraplength=900, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10)

    # ------------------------------------------------------------ действия

    def refresh(self) -> None:
        self.autostart_var.set(self._shortcut_path().exists())
        self.scale_var.set(f"{self.app.style.font_scale}%")
        self.theme_var.set(a11y.theme(self.app.theme_name)["label"])

    def _save(self) -> None:
        self.settings.set("toast_enabled", bool(self.toast_var.get()))
        self.settings.set("sound_enabled", bool(self.sound_var.get()))
        self.settings.set("sound_file", self.sound_file_var.get().strip())
        self.settings.set("prewarn_minutes", _as_int(self.prewarn_var.get()))
        self.settings.set("repeat_reminder_minutes", _as_int(self.reminder_var.get()))
        self.settings.set("default_lines", max(1, _as_int(self.lines_var.get(), 4)))
        self.settings.set("collision_window_minutes", _as_int(self.collision_var.get(), 5))
        self.settings.set("prep_lead_minutes", _as_int(self.prep_var.get()))
        self.settings.save()
        self.app.set_status("Настройките са записани.")

    def _apply_theme(self) -> None:
        label = self.theme_var.get()
        for name, data in a11y.THEMES.items():
            if data["label"] == label:
                self.app.set_theme(name)
                break

    def _apply_scale(self) -> None:
        text = self.scale_var.get().replace("%", "").strip()
        self.app.set_font_scale(_as_int(text, 100))

    def _pick_sound(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Избор на звук",
            filetypes=[("Звуков файл", "*.wav"), ("Всички файлове", "*.*")])
        if path:
            self.sound_file_var.set(path)
            self._save()

    def _test_sound(self) -> None:
        played = play_sound(self.sound_file_var.get().strip(), True)
        self.status_var.set("Звукът е пуснат." if played
                            else "Не успях да пусна звука — провери файла.")

    def _test_notification(self) -> None:
        self._save()
        backend = self.app.notifier.notify(
            "Пробно известие", "Така ще изглежда, когато нещо стане готово.")
        names = {"powershell": "Windows (PowerShell)", "winotify": "Windows (winotify)",
                 "fallback": "прозорец в приложението", "off": "изключено",
                 "none": "неуспешно"}
        self.status_var.set(f"Начин на известяване: {names.get(backend, backend)}."
                            + (f" Грешка: {self.app.notifier.last_error}"
                               if self.app.notifier.last_error else ""))

    # --------------------------------------------------------- автостарт

    def _shortcut_path(self) -> Path:
        startup = Path(os.path.expandvars(
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
        return startup / SHORTCUT_NAME

    def _launch_target(self) -> tuple[str, str]:
        """Връща (програма, аргументи) според това дали сме .exe или скрипт."""
        if getattr(sys, "frozen", False):
            return sys.executable, ""
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        runner = str(pythonw if pythonw.exists() else sys.executable)
        main_py = Path(__file__).resolve().parents[2] / "main.py"
        return runner, f'"{main_py}"'

    def _toggle_autostart(self) -> None:
        shortcut = self._shortcut_path()
        if not self.autostart_var.get():
            try:
                shortcut.unlink(missing_ok=True)
                self.status_var.set("Автоматичното стартиране е изключено.")
            except OSError as exc:
                self.status_var.set(f"Не можах да премахна прекия път: {exc}")
            return

        target, arguments = self._launch_target()
        work_dir = str(Path(target).parent if getattr(sys, "frozen", False)
                       else Path(__file__).resolve().parents[2])
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:KL_LNK); "
            "$s.TargetPath = $env:KL_TARGET; "
            "$s.Arguments = $env:KL_ARGS; "
            "$s.WorkingDirectory = $env:KL_DIR; "
            "$s.Description = 'Kapilands Таймер'; "
            "$s.Save()"
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
            self.autostart_var.set(False)
            self.status_var.set(f"Не можах да създам прекия път: {exc}")
            return
        if result.returncode != 0 or not shortcut.exists():
            self.autostart_var.set(False)
            self.status_var.set(
                "Не можах да създам прекия път. "
                + result.stderr.decode("utf-8", "replace").strip()[:200])
            return
        self.status_var.set(f"Готово — пряк път в „Автоматично стартиране“: {shortcut}")

    def _open_data_folder(self) -> None:
        folder = str(Path(self.app.db.path).parent)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            messagebox.showinfo("Папка с данните", folder, parent=self.app.root)


def _as_int(text: str, default: int = 0) -> int:
    try:
        return int(float(str(text).strip().replace(",", ".") or default))
    except ValueError:
        return default
