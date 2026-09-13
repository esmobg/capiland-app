"""Раздел „Компании“ — кой какво прави и кой бездейства."""

from __future__ import annotations

import wx

from .. import catalog, planner
from ..models import Account, TimerStatus
from ..timeutil import format_when, now as time_now
from .common import Form, RowList, confirm, read_only_text, show_error

ALL_WORLDS = "Всички светове"
SHOW_ALL, SHOW_IDLE, SHOW_BUILDING = 0, 1, 2

COLUMNS = [
    ("Компания", 170, wx.LIST_FORMAT_LEFT),
    ("Свят", 140, wx.LIST_FORMAT_LEFT),
    ("Състояние", 230, wx.LIST_FORMAT_LEFT),
    ("Собственик", 110, wx.LIST_FORMAT_LEFT),
    ("Сгради", 230, wx.LIST_FORMAT_LEFT),
    ("Бележка", 200, wx.LIST_FORMAT_LEFT),
]


class AccountDialog(wx.Dialog):
    def __init__(self, parent, db, account: Account | None = None, world: str = "") -> None:
        super().__init__(parent, title="Редактиране на компания" if account else "Нова компания",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.db = db
        self.original = account
        self.result: Account | None = None

        outer = wx.BoxSizer(wx.VERTICAL)
        form = Form(self)
        worlds = list(dict.fromkeys(list(catalog.KNOWN_WORLDS) + db.list_worlds()))
        self.world = form.add("Свят:", wx.ComboBox, choices=worlds)
        self.name = form.add("Име на компанията:", wx.TextCtrl)
        self.owner = form.add("Собственик:", wx.TextCtrl)
        self.buildings = form.add("Сгради, разделени с точка и запетая:", wx.TextCtrl)
        self.add_building = form.add("Добави сграда:", wx.ComboBox,
                                     choices=catalog.building_names(), style=wx.CB_READONLY)
        self.note = form.add("Бележка:", wx.TextCtrl)
        outer.Add(form.sizer, 1, wx.EXPAND | wx.ALL, 12)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, "Запиши")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL, "Отказ"))
        buttons.Realize()
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize(self.FromDIP(wx.Size(460, -1)))

        if account:
            self.world.SetValue(account.world)
            self.name.SetValue(account.name)
            self.owner.SetValue(account.owner)
            self.buildings.SetValue(account.buildings)
            self.note.SetValue(account.note)
        else:
            self.world.SetValue(world)

        self.add_building.Bind(wx.EVT_COMBOBOX, self._on_add_building)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.CentreOnParent()
        wx.CallAfter((self.name if not account else self.world).SetFocus)

    def _on_add_building(self, _event) -> None:
        temp = Account(buildings=self.buildings.GetValue())
        temp.add_building(self.add_building.GetStringSelection())
        self.buildings.SetValue(temp.buildings)

    def _on_ok(self, _event) -> None:
        name = self.name.GetValue().strip()
        if not name:
            show_error(self, "Името на компанията е задължително.", self.name)
            return
        account = self.original or Account()
        account.world = self.world.GetValue().strip()
        account.name = name
        account.owner = self.owner.GetValue().strip()
        account.buildings = "; ".join(Account(buildings=self.buildings.GetValue()).building_list)
        account.note = self.note.GetValue().strip()
        self.result = account
        self.EndModal(wx.ID_OK)


class AccountsPanel(wx.Panel):
    def __init__(self, parent, frame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.db = frame.db
        self._accounts: dict[int, Account] = {}

        sizer = wx.BoxSizer(wx.VERTICAL)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(wx.StaticText(self, label="Свят:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.world_filter = wx.Choice(self, choices=[ALL_WORLDS])
        self.world_filter.SetName("Свят")
        self.world_filter.SetSelection(0)
        filters.Add(self.world_filter, 1, wx.RIGHT, 16)
        filters.Add(wx.StaticText(self, label="Показвай:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.show_filter = wx.Choice(self, choices=["Всички", "Само бездействащите",
                                                    "Със строеж или разширяване"])
        self.show_filter.SetName("Показвай")
        self.show_filter.SetSelection(0)
        filters.Add(self.show_filter, 1)
        sizer.Add(filters, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Компании:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.list = RowList(self, COLUMNS, name="Компании")
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Обобщение:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.summary = read_only_text(self, lines=3)
        self.summary.SetName("Обобщение")
        sizer.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Нов &таймер за компанията", self.new_timer_for_selected),
            ("Нова &компания", self.new_account),
            ("&Редактирай", self.edit_selected),
            ("Изтрий", self.delete_selected),
        ):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            buttons.Add(button, 0, wx.ALL, 4)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)

        self.world_filter.Bind(wx.EVT_CHOICE, lambda _e: self.refresh())
        self.show_filter.Bind(wx.EVT_CHOICE, lambda _e: self.refresh())
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.edit_selected())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def set_worlds(self, worlds: list[str]) -> None:
        current = self.world_filter.GetStringSelection()
        items = [ALL_WORLDS] + worlds
        if self.world_filter.GetItems() != items:
            self.world_filter.Set(items)
            self.world_filter.SetStringSelection(current if current in items else ALL_WORLDS)

    def refresh(self) -> None:
        now = time_now()
        world = self.world_filter.GetStringSelection()
        accounts = self.db.list_accounts(None if world in ("", ALL_WORLDS) else world)
        timers = self.db.list_timers(TimerStatus.RUNNING.value)
        idle_keys = {(a.world.lower(), a.name.lower())
                     for a in planner.idle_accounts(accounts, timers, now)}
        show = self.show_filter.GetSelection()
        rows = []
        self._accounts = {}
        idle_names = []
        for account in accounts:
            own = planner.account_timers(account, timers)
            running = [t for t in own if t.end_at > now]
            ready = [t for t in own if t.end_at <= now]
            is_idle = (account.world.lower(), account.name.lower()) in idle_keys
            building_work = [t for t in running if t.type in ("build", "expand")]
            if show == SHOW_IDLE and not is_idle:
                continue
            if show == SHOW_BUILDING and not building_work:
                continue
            if is_idle:
                idle_names.append(account.name)
            if running:
                status = f"{len(running)} активни, следващо {format_when(running[0].end_at, now)}"
            elif ready:
                status = f"бездейства — {len(ready)} готови за потвърждаване"
            else:
                status = "бездейства"
            self._accounts[account.id] = account
            rows.append((account.id, [account.name, account.world or "—", status,
                                      account.owner or "—", account.buildings or "—",
                                      account.note or ""],
                         "missed" if is_idle else "running"))
        self.list.set_rows(rows)

        total = len(accounts)
        if idle_names:
            listed = ", ".join(idle_names[:12]) + (" и още" if len(idle_names) > 12 else "")
            text = (f"Бездействат {len(idle_names)} от {total} компании. "
                    f"Там може веднага да се пусне нещо: {listed}.")
        elif total:
            text = f"Всички {total} компании работят."
        else:
            text = "Още няма компании. Внеси списък с Ctrl+I или добави компания."
        if not self.summary.HasFocus():
            self.summary.SetValue(text)

    def selected(self) -> Account | None:
        row_id = self.list.selected_id()
        return self._accounts.get(row_id) if row_id is not None else None

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE and not event.HasAnyModifiers():
            self.delete_selected()
            return
        event.Skip()

    def new_timer_for_selected(self) -> None:
        account = self.selected()
        if account is None:
            self.frame.announce("Първо избери компания.", interrupt=True)
            return
        self.frame.show_page(0)
        self.frame.timers.new_timer(world=account.world, company=account.name)

    def new_account(self) -> None:
        world = self.world_filter.GetStringSelection()
        dialog = AccountDialog(self.frame, self.db, world="" if world == ALL_WORLDS else world)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.result is not None:
                self.db.upsert_account(dialog.result)
                self.frame.refresh_all()
                self.list.focus_id(dialog.result.id)
                self.frame.announce(f"Добавена компания {dialog.result.name}.")
        finally:
            dialog.Destroy()
        self.list.SetFocus()

    def edit_selected(self) -> None:
        account = self.selected()
        if account is None:
            self.frame.announce("Първо избери компания.", interrupt=True)
            return
        dialog = AccountDialog(self.frame, self.db, account)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.result is not None:
                self.db.update_account(dialog.result)
                self.frame.refresh_all()
                self.list.focus_id(account.id)
                self.frame.announce("Записано.")
        finally:
            dialog.Destroy()
        self.list.SetFocus()

    def delete_selected(self) -> None:
        account = self.selected()
        if account is None:
            self.frame.announce("Първо избери компания.", interrupt=True)
            return
        if not confirm(self.frame, f"Да изтрия ли компанията „{account.display_name}“?\n"
                                   "Таймерите ѝ остават.", "Изтриване"):
            self.list.SetFocus()
            return
        self.db.delete_account(account.id)
        self.frame.refresh_all()
        self.list.SetFocus()
        self.frame.announce("Изтрито.", interrupt=True)
