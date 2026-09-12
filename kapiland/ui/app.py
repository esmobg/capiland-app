"""Главният прозорец."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import a11y, catalog, config
from ..db import Database
from ..config import Settings
from ..notify import Notifier
from ..scheduler import EVENT_DUE, EVENT_MISSED, Scheduler
from ..timeutil import format_dt, now as time_now
from .catalog_view import CatalogView
from .history_view import HistoryView
from .settings_view import SettingsView
from .style import AppStyle
from .timers_view import TimersView

TICK_MS = 1000


class KapilandsApp:
    """Свързва базата, планировчика и разделите на интерфейса."""

    def __init__(self, db_path: str | None = None) -> None:
        self.settings = Settings()
        self.db = Database(db_path)
        catalog.ensure_seed(self.db)

        self.root = tk.Tk()
        self.root.title(config.APP_TITLE)
        self.root.minsize(900, 560)
        geometry = str(self.settings.get("window_geometry", ""))
        if geometry:
            try:
                self.root.geometry(geometry)
            except tk.TclError:
                pass
        else:
            self.root.geometry("1120x720")

        self.theme_name = str(self.settings.get("theme", a11y.DEFAULT_THEME))
        self.style = AppStyle(self.root, self.theme_name,
                              int(self.settings.get("font_scale", 100) or 100))

        self.notifier = Notifier(
            app_name=config.APP_TITLE,
            fallback=self._fallback_notification,
            enabled=True,
        )
        self.scheduler = Scheduler(self.db, self.notifier, self.settings)

        self._build()
        self._bind_keys()

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.refresh_all()
        self._catch_up()
        self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------- градеж

    def _build(self) -> None:
        container = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Kapilands Таймер", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w")
        self.clock_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.clock_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e")

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.timers_view = TimersView(self.notebook, self)
        self.catalog_view = CatalogView(self.notebook, self)
        self.history_view = HistoryView(self.notebook, self)
        self.settings_view = SettingsView(self.notebook, self)

        self.notebook.add(self.timers_view, text="Таймери", underline=0)
        self.notebook.add(self.catalog_view, text="Каталог", underline=0)
        self.notebook.add(self.history_view, text="История", underline=0)
        self.notebook.add(self.settings_view, text="Настройки", underline=0)
        self.notebook.enable_traversal()  # Alt+буква и Ctrl+Tab
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_change())

        status = ttk.Frame(self.root)
        status.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Готово за работа. Натиснете Ctrl+N "
                                             "за нов таймер, F1 за помощ.")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel",
                  anchor="w").pack(fill="x")

    def _bind_keys(self) -> None:
        root = self.root
        root.bind_all("<Control-n>", lambda _e: self.timers_view.new_timer())
        root.bind_all("<Control-N>", lambda _e: self.timers_view.new_timer())
        root.bind_all("<Control-d>", lambda _e: self.timers_view.complete_selected())
        root.bind_all("<Control-D>", lambda _e: self.timers_view.complete_selected())
        root.bind_all("<Control-Shift-D>",
                      lambda _e: self.timers_view.complete_all_due())
        root.bind_all("<Control-r>", lambda _e: self.timers_view.restart_selected())
        root.bind_all("<Control-R>", lambda _e: self.timers_view.restart_selected())
        root.bind_all("<F1>", lambda _e: self.show_keyboard_help())
        root.bind_all("<F5>", lambda _e: self.refresh_all())
        root.bind_all("<F6>", self._cycle_focus)
        root.bind_all("<Control-plus>", lambda _e: self._bump_scale(1))
        root.bind_all("<Control-equal>", lambda _e: self._bump_scale(1))
        root.bind_all("<Control-KP_Add>", lambda _e: self._bump_scale(1))
        root.bind_all("<Control-minus>", lambda _e: self._bump_scale(-1))
        root.bind_all("<Control-KP_Subtract>", lambda _e: self._bump_scale(-1))

    # ------------------------------------------------------------ действия

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def refresh_all(self) -> None:
        self.timers_view.refresh(full=True)
        self.catalog_view.refresh()
        self.history_view.refresh()

    def _on_tab_change(self) -> None:
        try:
            current = self.notebook.index(self.notebook.select())
        except tk.TclError:
            return
        if current == 1:
            self.catalog_view.refresh()
        elif current == 2:
            self.history_view.refresh()
        elif current == 3:
            self.settings_view.refresh()

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        self.style.set_theme(name)
        self.settings.set("theme", name)
        self.settings.save()
        for view in (self.timers_view, self.catalog_view, self.history_view):
            for tree in _find_trees(view):
                self.style.tag_tree(tree)
        self.timers_view.refresh(full=True)
        self.set_status(f"Тема: {a11y.theme(name)['label']}.")

    def set_font_scale(self, percent: int) -> None:
        self.style.set_scale(percent)
        self.settings.set("font_scale", self.style.font_scale)
        self.settings.save()
        self.set_status(f"Размер на текста: {self.style.font_scale}%.")

    def _bump_scale(self, step: int) -> None:
        value = self.style.bump_scale(step)
        self.settings.set("font_scale", value)
        self.settings.save()
        self.settings_view.refresh()
        self.set_status(f"Размер на текста: {value}%.")

    def _cycle_focus(self, _event=None) -> str:
        """F6 — прескачане между таблицата и лентата с бутони."""
        widget = self.root.focus_get()
        if widget is self.timers_view.tree:
            self.timers_view.btn_new.focus_set()
        else:
            self.timers_view.tree.focus_set()
        return "break"

    # -------------------------------------------------------------- тик

    def _tick(self) -> None:
        try:
            events = self.scheduler.tick()
            # refresh сам преначертава таблицата, ако редовете са се променили;
            # иначе само обновява клетките - без това при много таймери
            # всяко събитие спираше интерфейса за части от секундата.
            self.timers_view.refresh(full=False)
            if events:
                due = [e for e in events if e.kind in (EVENT_DUE, EVENT_MISSED)]
                if due:
                    names = ", ".join(e.timer.display_name for e in due)
                    self.set_status(f"✔ ГОТОВО: {names} — пусни следващите.")
                    self.root.bell()
                else:
                    self.set_status(events[0].title)
            self.clock_var.set(format_dt(time_now(), "%d.%m.%Y %H:%M:%S"))
        finally:
            self.root.after(TICK_MS, self._tick)

    def _catch_up(self) -> None:
        events = self.scheduler.catch_up()
        if not events:
            return
        names = ", ".join(e.timer.display_name for e in events[:5])
        more = f" и още {len(events) - 5}" if len(events) > 5 else ""
        self.set_status(
            f"!! Докато приложението не работеше, изтекоха {len(events)}: "
            f"{names}{more}. Потвърди ги с „Готово“.")
        self.timers_view.refresh(full=True)

    # --------------------------------------------------------- помощ и край

    def _fallback_notification(self, title: str, message: str) -> None:
        """Ако Windows известията не са налични — прозорец в приложението."""
        self.root.after(0, lambda: _show_alert(self, title, message))

    def show_keyboard_help(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Клавишни комбинации")
        window.transient(self.root)
        window.configure(background=self.style.colors["bg"])
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Всичко в приложението се управлява и само с клавиатура",
                  style="Heading.TLabel").grid(row=0, column=0, columnspan=2,
                                               sticky="w", pady=(0, 10))
        for index, (keys, description) in enumerate(a11y.KEYBOARD_HELP, start=1):
            ttk.Label(body, text=keys, font=self.style.bold_font).grid(
                row=index, column=0, sticky="w", padx=(0, 16), pady=3)
            ttk.Label(body, text=description).grid(row=index, column=1,
                                                   sticky="w", pady=3)
        ttk.Button(body, text="Затвори", style="Accent.TButton",
                   command=window.destroy).grid(
            row=len(a11y.KEYBOARD_HELP) + 1, column=0, columnspan=2,
            sticky="e", pady=(14, 0))
        window.bind("<Escape>", lambda _e: window.destroy())
        window.update_idletasks()
        window.grab_set()
        window.focus_set()

    def quit(self) -> None:
        try:
            self.settings.set("window_geometry", self.root.geometry())
            self.settings.save()
        except tk.TclError:
            pass
        self.db.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _show_alert(app: KapilandsApp, title: str, message: str) -> None:
    window = tk.Toplevel(app.root)
    window.title(title)
    window.transient(app.root)
    window.attributes("-topmost", True)
    window.configure(background=app.style.colors["bg"])
    body = ttk.Frame(window, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=title, style="Heading.TLabel", wraplength=420,
              justify="left").pack(anchor="w")
    ttk.Label(body, text=message, wraplength=420, justify="left").pack(
        anchor="w", pady=(8, 14))
    ttk.Button(body, text="Разбрах", style="Accent.TButton",
               command=window.destroy).pack(anchor="e")
    window.bind("<Escape>", lambda _e: window.destroy())
    window.update_idletasks()
    window.focus_set()


def _find_trees(widget) -> list:
    """Всички Treeview елементи в даден раздел."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Treeview):
            found.append(child)
        found.extend(_find_trees(child))
    return found
