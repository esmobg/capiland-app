"""Главният прозорец."""

from __future__ import annotations

import wx

from .. import a11y, catalog, config, planner
from ..config import Settings
from ..db import Database
from ..models import TimerStatus
from ..notify import Notifier
from ..scheduler import EVENT_DUE, EVENT_MISSED, Scheduler
from ..speech import JawsBackend, NvdaBackend, Speaker, UiaBackend
from ..timeutil import now as time_now
from .accounts_panel import AccountsPanel
from .catalog_panel import CatalogPanel
from .common import apply_font_scale, palette_for, read_only_text
from .history_panel import HistoryPanel
from .import_dialog import ImportDialog
from .settings_panel import SettingsPanel
from .timers_panel import TimersPanel

TICK_MS = 1000
HOTKEY_STATUS = 0xB001
HOTKEY_SHOW = 0xB002
PAGE_TITLES = ("Таймери", "Компании", "Каталог", "История", "Настройки")


class HelpDialog(wx.Dialog):
    """Клавишите като обикновен текст — стрелките го четат ред по ред."""

    def __init__(self, parent) -> None:
        super().__init__(parent, title="Клавишни комбинации",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Клавиши:"), 0, wx.ALL, 8)
        text = read_only_text(self, lines=16)
        text.SetName("Клавиши")
        text.SetValue("\n".join(f"{keys} — {what}" for keys, what in a11y.KEYBOARD_HELP))
        sizer.Add(text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        close = wx.Button(self, wx.ID_CANCEL, "Затвори")
        close.SetDefault()
        sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(sizer)
        self.SetSize(self.FromDIP(wx.Size(620, 520)))
        self.CentreOnParent()
        wx.CallAfter(text.SetFocus)


class MainFrame(wx.Frame):
    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__(None, title=config.APP_TITLE, size=wx.Size(1180, 760))
        self.db = db
        self.settings = settings
        self.hotkey_status = ""
        self._hotkeys_on = False
        self._last_due = -1

        self.speaker = Speaker(
            [NvdaBackend(), JawsBackend(), UiaBackend(self._foreground_hwnd)],
            mode=str(settings.get("speech_mode", "auto")))
        self.notifier = Notifier(app_name=config.APP_TITLE)
        self.scheduler = Scheduler(db, self.notifier, settings, speaker=self.speaker)

        self._build_menu()
        self.notebook = wx.Notebook(self)
        self.timers = TimersPanel(self.notebook, self)
        self.accounts = AccountsPanel(self.notebook, self)
        self.catalog = CatalogPanel(self.notebook, self)
        self.history = HistoryPanel(self.notebook, self)
        self.settings_page = SettingsPanel(self.notebook, self)
        for page, title in zip((self.timers, self.accounts, self.catalog, self.history,
                                self.settings_page), PAGE_TITLES):
            page.SetName(title)
            page.SetLabel("")  # текстът на прозореца е „panel“ — четецът би го казал
            self.notebook.AddPage(page, title)
        self.CreateStatusBar()
        self.SetMinSize(self.FromDIP(wx.Size(820, 560)))

        palette = palette_for(str(settings.get("theme", "system")))
        for list_ctrl in (self.timers.list, self.accounts.list):
            list_ctrl.palette = palette

        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_page)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_HOTKEY, self._on_hotkey_status, id=HOTKEY_STATUS)
        self.Bind(wx.EVT_HOTKEY, self._on_hotkey_show, id=HOTKEY_SHOW)

        self.apply_settings(hotkeys_changed=True, initial=True)
        self.refresh_all(resort=True)
        self._catch_up()

        self.ticker = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self.ticker)
        self.ticker.Start(TICK_MS)
        wx.CallAfter(self.timers.list.SetFocus)

    # ------------------------------------------------------------ меню

    def _build_menu(self) -> None:
        bar = wx.MenuBar()

        def item(menu, label, handler, help_text=""):
            entry = menu.Append(wx.ID_ANY, label, help_text)
            self.Bind(wx.EVT_MENU, lambda _e: handler(), entry)
            return entry

        file_menu = wx.Menu()
        item(file_menu, "&Внос на списък…\tCtrl+I", self.open_import)
        file_menu.AppendSeparator()
        item(file_menu, "&Изход\tAlt+F4", self.Close)
        bar.Append(file_menu, "&Файл")

        actions = wx.Menu()
        item(actions, "&Нов таймер…\tCtrl+N", lambda: self._on_timers(self.timers.new_timer))
        item(actions, "&Редактирай избрания…", lambda: self._on_timers(self.timers.edit_selected))
        item(actions, "&Готово\tCtrl+D", lambda: self._on_timers(self.timers.complete_selected))
        item(actions, "Потвърди &всички готови\tCtrl+Shift+D",
             lambda: self._on_timers(self.timers.complete_all_due))
        item(actions, "Нов &цикъл\tCtrl+R", lambda: self._on_timers(self.timers.restart_selected))
        actions.AppendSeparator()
        item(actions, "Кажи &подробностите\tF3", lambda: self._on_timers(self.timers.speak_details))
        item(actions, "Кажи какво е &готово и какво следва\tF4", self.speak_summary)
        bar.Append(actions, "&Действия")

        view = wx.Menu()
        for index, title in enumerate(PAGE_TITLES):
            item(view, f"{title}\tCtrl+{index + 1}", lambda i=index: self.show_page(i, focus=True))
        view.AppendSeparator()
        item(view, "Към филтъра по &свят\tCtrl+F", self.focus_world_filter)
        item(view, "&Обнови и подреди по час\tF5", lambda: self.refresh_all(resort=True))
        item(view, "Между списъка и подробностите\tF6", self.cycle_focus)
        view.AppendSeparator()
        item(view, "По-&голям текст\tCtrl+=", lambda: self.bump_font(1))
        item(view, "По-&малък текст\tCtrl+-", lambda: self.bump_font(-1))
        bar.Append(view, "&Изглед")

        help_menu = wx.Menu()
        item(help_menu, "&Клавишни комбинации\tF1", self.show_help)
        bar.Append(help_menu, "По&мощ")
        self.SetMenuBar(bar)

    # ------------------------------------------------------ говор и статус

    def _foreground_hwnd(self) -> int:
        return self.GetHandle() if self.IsActive() else 0

    def announce(self, text: str, interrupt: bool = False) -> str | None:
        """Статус лента + изговаряне през четеца (ако има такъв)."""
        self.SetStatusText(text)
        return self.speaker.speak(text, interrupt=interrupt)

    def speak_summary(self) -> None:
        timers = self.db.list_timers(TimerStatus.RUNNING.value)
        self.announce(planner.spoken_summary(timers, time_now()), interrupt=True)

    def reader_mode(self) -> bool:
        mode = str(self.settings.get("reader_mode", "auto"))
        if mode == "on":
            return True
        if mode == "off":
            return False
        return self.speaker.reader_active()

    # ---------------------------------------------------------- настройки

    def apply_settings(self, hotkeys_changed: bool = False, initial: bool = False) -> None:
        self.speaker.mode = str(self.settings.get("speech_mode", "auto"))
        self.timers.set_countdown(not self.reader_mode())
        apply_font_scale(self, int(self.settings.get("font_scale", 100) or 100))
        if hotkeys_changed:
            self._register_hotkeys(bool(self.settings.get("global_hotkeys", True)))
        if not initial:
            self.refresh_all()

    def _register_hotkeys(self, enabled: bool) -> None:
        if self._hotkeys_on:
            self.UnregisterHotKey(HOTKEY_STATUS)
            self.UnregisterHotKey(HOTKEY_SHOW)
            self._hotkeys_on = False
        if not enabled:
            self.hotkey_status = "Глобалните клавиши са изключени."
            return
        mods = wx.MOD_CONTROL | wx.MOD_ALT
        ok_status = self.RegisterHotKey(HOTKEY_STATUS, mods, ord("K"))
        ok_show = self.RegisterHotKey(HOTKEY_SHOW, mods, ord("J"))
        self._hotkeys_on = ok_status or ok_show
        if ok_status and ok_show:
            self.hotkey_status = "Глобалните клавиши Ctrl+Alt+K и Ctrl+Alt+J работят."
        else:
            taken = [k for k, ok in (("Ctrl+Alt+K", ok_status), ("Ctrl+Alt+J", ok_show)) if not ok]
            self.hotkey_status = (f"{' и '.join(taken)} се ползва от друга програма "
                                  "и не работи тук.")

    def bump_font(self, step: int) -> None:
        scales = list(a11y.FONT_SCALES)
        current = int(self.settings.get("font_scale", 100) or 100)
        index = scales.index(current) if current in scales else 0
        new = scales[max(0, min(len(scales) - 1, index + step))]
        self.settings.set("font_scale", new)
        self.settings.save()
        apply_font_scale(self, new)
        self.announce(f"Размер на текста {new} процента.", interrupt=True)

    # ------------------------------------------------------------ навигация

    def show_page(self, index: int, focus: bool = False) -> None:
        self.notebook.SetSelection(index)
        if focus:
            target = {0: self.timers.list, 1: self.accounts.list, 2: self.catalog.list,
                      3: self.history.log}.get(index, self.settings_page)
            target.SetFocus()

    def _on_timers(self, action) -> None:
        if self.notebook.GetSelection() != 0:
            self.show_page(0)
        action()

    def focus_world_filter(self) -> None:
        page = self.notebook.GetSelection()
        if page == 1:
            self.accounts.world_filter.SetFocus()
        else:
            self.show_page(0)
            self.timers.world_filter.SetFocus()

    def cycle_focus(self) -> None:
        page = self.notebook.GetCurrentPage()
        if page is self.timers:
            order = [self.timers.list, self.timers.details, self.timers.buttons[0]]
        elif page is self.accounts:
            order = [self.accounts.list, self.accounts.summary]
        else:
            return
        focused = wx.Window.FindFocus()
        index = order.index(focused) if focused in order else -1
        order[(index + 1) % len(order)].SetFocus()

    def show_help(self) -> None:
        dialog = HelpDialog(self)
        dialog.ShowModal()
        dialog.Destroy()

    def _on_page(self, event) -> None:
        index = event.GetSelection()
        {1: self.accounts.refresh, 2: self.catalog.refresh, 3: self.history.refresh,
         4: self.settings_page.refresh}.get(index, lambda: None)()
        event.Skip()

    # ---------------------------------------------------------------- внос

    def open_import(self) -> None:
        dialog = ImportDialog(self, self.db, self.settings, speak=lambda t: self.speaker.speak(t))
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.applied:
                counts = dialog.applied
                self.refresh_all(resort=True)
                self.show_page(0, focus=True)
                self.announce(f"Внесени {counts['timers']} таймера и "
                              f"{counts['companies']} компании.", interrupt=True)
        finally:
            dialog.Destroy()

    # ------------------------------------------------------------- обновяване

    def refresh_all(self, resort: bool = False) -> None:
        worlds = self.db.list_worlds()
        self.timers.set_worlds(worlds)
        self.accounts.set_worlds(worlds)
        self.timers.refresh(resort=resort)
        page = self.notebook.GetSelection()
        if page == 1:
            self.accounts.refresh()
        elif page == 2:
            self.catalog.refresh()
        elif page == 3:
            self.history.refresh()
        self._update_title()

    def _update_title(self) -> None:
        due = self.timers.due_count()
        if due != self._last_due:
            self._last_due = due
            self.SetTitle(f"{config.APP_TITLE} — готови: {due}" if due else config.APP_TITLE)

    def _on_tick(self, _event) -> None:
        events = self.scheduler.tick()
        self.timers.refresh()
        if self.notebook.GetSelection() == 1 and events:
            self.accounts.refresh()
        self._update_title()
        if events:
            due = [e for e in events if e.kind in (EVENT_DUE, EVENT_MISSED)]
            title = (f"Готово: {', '.join(planner.describe_spoken(e.timer) for e in due)}"
                     if due else events[0].title)
            self.SetStatusText(title)

    def _catch_up(self) -> None:
        events = self.scheduler.catch_up()
        if events:
            self.SetStatusText(f"Докато приложението беше затворено, станаха готови {len(events)}.")
            self.timers.refresh()

    # ---------------------------------------------------------- глобални клавиши

    def _on_hotkey_status(self, _event) -> None:
        timers = self.db.list_timers(TimerStatus.RUNNING.value)
        text = planner.spoken_summary(timers, time_now())
        self.SetStatusText(text)
        # Прозорецът е във фонов режим: говори през NVDA/JAWS, без да краде фокуса.
        if self.speaker.speak(text, interrupt=True) is None:
            self.notifier.notify_async("Kapilands Таймер", text)

    def _on_hotkey_show(self, _event) -> None:
        if self.IsIconized():
            self.Iconize(False)
        self.Show()
        self.Raise()
        self.show_page(0, focus=True)

    def _on_close(self, event) -> None:
        self.ticker.Stop()
        self._register_hotkeys(False)
        try:
            self.settings.save()
        finally:
            self.db.close()
        event.Skip()


def create_app(db_path: str | None = None) -> tuple[wx.App, MainFrame]:
    settings = Settings()
    theme = str(settings.get("theme", "system"))
    app = wx.App(False)
    if theme != "light" and hasattr(wx.App, "MSWEnableDarkMode"):
        # „Като Windows“ следва системата; „Тъмна“ налага тъмен режим.
        app.MSWEnableDarkMode(1 if theme == "dark" else 0)
    app.SetAppName(config.APP_NAME)
    db = Database(db_path)
    catalog.ensure_seed(db)
    catalog.upgrade_catalog_v2(db)
    catalog.upgrade_catalog_v3(db)
    frame = MainFrame(db, settings)
    return app, frame


def run(db_path: str | None = None) -> None:
    app, frame = create_app(db_path)
    frame.Show()
    app.MainLoop()
