"""Тестове през wx интерфейса — пътищата, по които минава потребителят.

Вдигат истински прозорци; ако няма графична среда или wxPython, се прескачат.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("KAPILANDS_DATA_DIR", tempfile.mkdtemp(prefix="kapilands-wxtest"))

try:
    import wx

    _APP = wx.App(False)
    HAS_WX = True
except Exception:  # pragma: no cover - зависи от машината
    HAS_WX = False

from kapiland.models import Account, Timer, TimerStatus
from kapiland.timeutil import now as time_now

HOUR = 3600
SAMPLE = (Path(__file__).parent / "fixtures" / "sample_list.txt").read_text(encoding="utf-8")


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.mode = "auto"

    def speak(self, text, interrupt=False):
        self.said.append(text)
        return "nvda"

    def reader_active(self):
        return True

    def cancel(self):
        pass


def make_frame():
    from kapiland import catalog
    from kapiland.config import Settings
    from kapiland.db import Database
    from kapiland.wxui import common
    from kapiland.wxui.app import MainFrame

    os.environ["KAPILANDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kapilands-wx")
    db = Database(os.path.join(os.environ["KAPILANDS_DATA_DIR"], "t.db"))
    catalog.upgrade_catalog_v2(db)
    catalog.upgrade_catalog_v3(db)
    settings = Settings()
    settings.set("toast_enabled", False)
    settings.set("sound_enabled", False)
    settings.set("global_hotkeys", False)  # не пречи на истинския потребител
    frame = MainFrame(db, settings)
    frame.ticker.Stop()
    frame.speaker = FakeSpeaker()
    frame.scheduler.speaker = frame.speaker
    common._test_messages = []
    return frame


@unittest.skipUnless(HAS_WX, "няма wxPython или графична среда")
class WxTestCase(unittest.TestCase):
    def setUp(self):
        from kapiland.wxui import common

        self.messages = []
        self._orig_box = wx.MessageBox
        wx.MessageBox = lambda text, *a, **k: (self.messages.append(text), wx.YES)[1]
        common.wx.MessageBox = wx.MessageBox
        self.frame = make_frame()

    def tearDown(self):
        wx.MessageBox = self._orig_box
        try:
            self.frame.ticker.Stop()
            self.frame.db.close()
            self.frame.Destroy()
        except Exception:
            pass
        wx.Yield()

    def add(self, **kwargs) -> Timer:
        n = time_now()
        data = dict(product="Бензин", quantity=1000, line="Алфа", world="Немска двойка",
                    start_at=n - 60, end_at=n + HOUR, duration_sec=HOUR + 60)
        data.update(kwargs)
        timer = Timer(**data)
        self.frame.db.add_timer(timer)
        return timer


class RowListTest(WxTestCase):
    def test_focus_stays_on_the_same_timer_when_another_is_added(self):
        first = self.add(product="Бензин", end_at=time_now() + 2 * HOUR)
        second = self.add(product="Газ", end_at=time_now() + 3 * HOUR)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        panel.list.focus_id(second.id)
        self.add(product="Ток", end_at=time_now() + 10)  # идва преди тях
        panel.refresh()
        self.assertEqual(panel.list.selected_id(), second.id)
        self.assertIsNotNone(first.id)

    def test_rows_do_not_move_while_navigating(self):
        a = self.add(product="А", end_at=time_now() + HOUR)
        b = self.add(product="Б", end_at=time_now() + 2 * HOUR)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        # Сменяме часа, така че „Б“ да стане по-ранен — без F5 редът не се мени.
        self.frame.db.set_timer_fields(b.id, end_at=time_now() + 60)
        panel.refresh()
        self.assertEqual(panel.list.ids(), [a.id, b.id])
        panel.refresh(resort=True)
        self.assertEqual(panel.list.ids(), [b.id, a.id])

    def test_state_change_updates_only_that_cell(self):
        timer = self.add(end_at=time_now() + HOUR)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        self.assertFalse(panel.list.GetItemText(0, 0).startswith("ГОТОВО"))
        self.frame.db.set_timer_fields(timer.id, end_at=time_now() - 1)
        redrawn = panel.list.set_rows([])  # празно = смяна на набора
        self.assertTrue(redrawn)
        panel.refresh()
        self.assertTrue(panel.list.GetItemText(0, 0).startswith("ГОТОВО от"))

    def test_when_column_has_no_seconds(self):
        self.add(end_at=time_now() + 5 * HOUR)
        self.frame.refresh_all(resort=True)
        text = self.frame.timers.list.GetItemText(0, 0)
        self.assertRegex(text, r"^\S.* \d\d:\d\d$")


class TimersPanelTest(WxTestCase):
    def test_details_are_a_whole_sentence(self):
        self.add(product="Бензин", building="Химически фабрики", end_at=time_now() + 2 * HOUR + 30)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        panel.list.focus_id(panel.list.ids()[0])
        panel.update_details()
        text = panel.details.GetValue()
        for part in ("1000× Бензин", "Алфа", "Немска двойка", "Химически фабрики", "остават"):
            self.assertIn(part, text)

    def test_f3_speaks_the_details(self):
        self.add()
        self.frame.refresh_all(resort=True)
        self.frame.timers.list.focus_id(self.frame.timers.list.ids()[0])
        self.frame.timers.speak_details()
        self.assertIn("Бензин", self.frame.speaker.said[-1])

    def test_f4_speaks_the_summary(self):
        self.add(end_at=time_now() - 5)
        self.add(product="Легла", line="Бета", end_at=time_now() + HOUR)
        self.frame.refresh_all(resort=True)
        self.frame.speak_summary()
        said = self.frame.speaker.said[-1]
        self.assertTrue(said.startswith("Готово: 1000× Бензин"))
        self.assertIn("Следващо: 1000× Легла, Бета", said)
        self.assertEqual(self.frame.GetStatusBar().GetStatusText(), said)

    def test_world_filter(self):
        self.add(world="Немска двойка")
        self.add(world="Холандска единица", product="Джинси")
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        self.assertEqual(panel.list.GetItemCount(), 2)
        panel.world_filter.SetStringSelection("Холандска единица")
        panel.refresh(resort=True)
        self.assertEqual(panel.list.GetItemCount(), 1)
        self.assertEqual(panel.list.GetItemText(0, 1), "Джинси")

    def test_only_due_filter(self):
        self.add(end_at=time_now() - 5)
        self.add(product="Легла", end_at=time_now() + HOUR)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        panel.show_filter.SetSelection(1)
        panel.refresh(resort=True)
        self.assertEqual(panel.list.GetItemCount(), 1)

    def test_complete_starts_next_cycle_and_is_announced(self):
        self.add(end_at=time_now() - 5, repeat_enabled=1, cycles_planned=3)
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        panel.list.focus_id(panel.list.ids()[0])
        panel.complete_selected()
        running = self.frame.db.list_timers(TimerStatus.RUNNING.value)
        self.assertEqual([t.cycle_no for t in running], [2])
        self.assertIn("Пуснат е цикъл 2", self.frame.speaker.said[-1])

    def test_nothing_selected_is_spoken_not_silent(self):
        self.frame.refresh_all(resort=True)
        self.frame.timers.complete_selected()
        self.assertIn("Първо избери", self.frame.speaker.said[-1])

    def test_delete_asks_first(self):
        timer = self.add()
        self.frame.refresh_all(resort=True)
        panel = self.frame.timers
        panel.list.focus_id(timer.id)
        wx.MessageBox = lambda *a, **k: wx.NO
        from kapiland.wxui import common
        common.wx.MessageBox = wx.MessageBox
        panel.delete_selected()
        self.assertIsNotNone(self.frame.db.get_timer(timer.id))

    def test_countdown_column_only_without_a_reader(self):
        panel = self.frame.timers
        panel.set_countdown(True)
        self.assertEqual(panel.list.GetColumnCount(), 8)
        panel.set_countdown(False)
        self.assertEqual(panel.list.GetColumnCount(), 7)

    def test_title_counts_ready_items(self):
        self.add(end_at=time_now() - 5)
        self.frame.refresh_all(resort=True)
        self.assertEqual(self.frame.GetTitle(), "Kapilands Таймер — готови: 1")


class TimerDialogTest(WxTestCase):
    def dialog(self, **kwargs):
        from kapiland.wxui.timer_dialog import TimerDialog

        return TimerDialog(self.frame, self.frame.db, self.frame.settings, **kwargs)

    def test_ready_at_in_bulgarian(self):
        dlg = self.dialog(world="Немска двойка", company="Алфа")
        try:
            dlg.product.SetValue("Бензин")
            dlg.end.SetValue("17 декември 18 ч")
            start, end, duration = dlg._compute()
            from kapiland.timeutil import format_dt
            self.assertEqual(format_dt(end, "%d.%m %H:%M"), "17.12 18:00")
            dlg._update_preview()
            self.assertIn("17 декември", dlg.preview.GetValue())
        finally:
            dlg.Destroy()

    def test_prefilled_world_and_company(self):
        self.frame.db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        dlg = self.dialog(world="Немска двойка", company="Алфа")
        try:
            self.assertEqual(dlg.world.GetValue(), "Немска двойка")
            self.assertEqual(dlg.company.GetValue(), "Алфа")
            self.assertIn("Алфа", dlg.company.GetItems())
        finally:
            dlg.Destroy()

    def test_bad_time_shows_a_message_and_keeps_the_dialog(self):
        dlg = self.dialog()
        try:
            dlg.end.SetValue("някога")
            dlg._on_ok(None)
            self.assertIsNone(dlg.result)
            self.assertTrue(any("времето" in m for m in self.messages))
        finally:
            dlg.Destroy()

    def edit(self, timer: Timer):
        dlg = self.dialog(timer=self.frame.db.get_timer(timer.id))
        dlg.EndModal = lambda code: None
        return dlg

    def test_editing_the_note_keeps_start_end_and_duration(self):
        """Преди: поправка на бележката правеше 8-часов таймер едночасов."""
        n = time_now()
        timer = self.add(start_at=n - 7 * HOUR, end_at=n + HOUR + 42, duration_sec=8 * HOUR + 42,
                         repeat_enabled=1)
        dlg = self.edit(timer)
        try:
            dlg.note.SetValue("само бележка")
            dlg._on_ok(None)
            result = dlg.result
            self.assertEqual(result.note, "само бележка")
            self.assertEqual(result.duration_sec, 8 * HOUR + 42)
            self.assertEqual(result.start_at, timer.start_at)
            self.assertEqual(result.end_at, timer.end_at)  # и секундите остават
        finally:
            dlg.Destroy()

    def test_moving_the_end_keeps_the_start(self):
        from kapiland.timeutil import format_dt

        n = time_now()
        timer = self.add(start_at=n - 2 * HOUR, end_at=n + HOUR, duration_sec=3 * HOUR)
        dlg = self.edit(timer)
        try:
            dlg.end.SetValue(format_dt(n + 5 * HOUR, "%d.%m.%Y %H:%M"))
            dlg._on_ok(None)
            result = dlg.result
            self.assertEqual(result.start_at, timer.start_at)
            self.assertAlmostEqual(result.duration_sec, 7 * HOUR, delta=60)
        finally:
            dlg.Destroy()

    def test_ready_is_not_announced_again_after_fixing_a_note(self):
        from kapiland.timeutil import format_dt

        n = time_now()
        timer = self.add(start_at=n - 2 * HOUR, end_at=n - HOUR, duration_sec=HOUR)
        self.frame.db.set_timer_fields(timer.id, notified_at=n - HOUR)
        dlg = self.edit(timer)
        try:
            dlg.note.SetValue("бележка")
            dlg._on_ok(None)
            self.assertEqual(dlg.result.notified_at, n - HOUR)
        finally:
            dlg.Destroy()
        dlg = self.edit(timer)
        try:
            dlg.end.SetValue(format_dt(n + 3 * HOUR, "%d.%m.%Y %H:%M"))
            dlg._on_ok(None)
            self.assertIsNone(dlg.result.notified_at)  # нов час — ново известие
        finally:
            dlg.Destroy()

    def test_typed_product_name_brings_the_remembered_values(self):
        from kapiland.models import Product
        from kapiland.wxui.timer_dialog import MODE_DURATION

        self.frame.db.upsert_product(Product(name="Бензин", default_duration_sec=8 * HOUR,
                                             default_quantity=1000,
                                             building="Химически фабрики"))
        dlg = self.dialog()
        try:
            dlg.mode.SetSelection(MODE_DURATION)
            dlg._on_mode()
            dlg.product.SetValue("бензин")       # написано, не избрано от списъка
            dlg._on_product_blur(wx.FocusEvent(wx.wxEVT_KILL_FOCUS))
            self.assertEqual(dlg.duration.GetValue(), "08:00:00")
            self.assertEqual(dlg.quantity.GetValue(), "1000")
            self.assertEqual(dlg.building.GetValue(), "Химически фабрики")
        finally:
            dlg.Destroy()

    def test_hidden_fields_follow_the_mode(self):
        from kapiland.wxui.timer_dialog import MODE_DURATION, MODE_END

        dlg = self.dialog()
        try:
            dlg.mode.SetSelection(MODE_END)
            dlg._on_mode()
            self.assertTrue(dlg.end.IsShown())
            self.assertFalse(dlg.duration.IsShown())
            dlg.mode.SetSelection(MODE_DURATION)
            dlg._on_mode()
            self.assertFalse(dlg.end.IsShown())
            self.assertTrue(dlg.duration.IsShown())
        finally:
            dlg.Destroy()


class ImportDialogTest(WxTestCase):
    def test_parse_and_apply_through_the_dialog(self):
        from kapiland.wxui.import_dialog import ImportDialog

        spoken = []
        dlg = ImportDialog(self.frame, self.frame.db, self.frame.settings, speak=spoken.append)
        try:
            dlg.text.SetValue(SAMPLE)
            dlg.world.SetValue("Българска единица")
            dlg._parse()
            self.assertEqual(dlg.list.GetItemCount(), len(dlg.result.entries))
            self.assertTrue(spoken and spoken[-1].startswith("Разпознати"))
            checked = [dlg.list.IsItemChecked(i) for i in range(dlg.list.GetItemCount())]
            self.assertEqual(checked, [e.selected for e in dlg.result.entries])
            self.assertNotIn("731944", dlg.unrecognized.GetValue() + dlg.summary.GetValue())

            dlg.EndModal = lambda code: None
            dlg._on_ok(None)
            self.assertEqual(dlg.applied["timers"], len(dlg.result.selected_entries))
            self.assertEqual(self.frame.settings.get("default_world"), "Българска единица")
        finally:
            dlg.Destroy()

    def test_unchecking_all_blocks_the_import(self):
        from kapiland.wxui.import_dialog import ImportDialog

        dlg = ImportDialog(self.frame, self.frame.db, self.frame.settings, speak=lambda t: None)
        try:
            dlg.text.SetValue(SAMPLE)
            dlg._parse()
            dlg._check_all(False)
            dlg._on_ok(None)
            self.assertIsNone(dlg.applied)
            self.assertTrue(any("отметнат" in m for m in self.messages))
        finally:
            dlg.Destroy()


class CsvTransferTest(WxTestCase):
    """„Изнеси в CSV“ на единия компютър, „Внеси от CSV“ на другия."""

    def export_from_other_computer(self) -> str:
        from kapiland import transfer
        from kapiland.db import Database

        other = Database(":memory:")
        try:
            n = time_now()
            other.upsert_account(Account(world="Холандска единица", name="Делта",
                                         buildings="Текстилни фабрики"))
            other.add_timer(Timer(product="Джинси", quantity=1500, line="Делта",
                                  world="Холандска единица", start_at=n,
                                  end_at=n + 5 * HOUR, duration_sec=5 * HOUR))
            other.add_timer(Timer(product="Кожа", line="Делта", world="Холандска единица",
                                  start_at=n - 2 * HOUR, end_at=n - HOUR, duration_sec=HOUR))
            path = os.path.join(tempfile.mkdtemp(prefix="kapilands-csv"), "katalog.csv")
            transfer.export_file(other, path)
            return path
        finally:
            other.close()

    def test_imported_timers_show_up_in_the_timers_list(self):
        path = self.export_from_other_computer()
        frame = self.frame
        frame.refresh_all(resort=True)
        self.assertEqual(frame.timers.list.GetItemCount(), 0)
        frame.show_page(2)

        frame.catalog.import_csv_from(path)

        timers = frame.timers
        self.assertEqual(timers.list.GetItemCount(), 2)
        self.assertEqual([timers.list.GetItemText(i, 1) for i in range(2)], ["Кожа", "Джинси"])
        self.assertTrue(timers.list.GetItemText(0, 0).startswith("ПРОПУСНАТО от"))
        self.assertIn("Холандска единица", timers.world_filter.GetItems())
        self.assertEqual(frame.GetTitle(), "Kapilands Таймер — готови: 1")
        said = frame.speaker.said[-1]
        self.assertIn("2 таймера и 1 компания", said)
        self.assertIn("раздел „Таймери“", said)
        self.assertEqual(frame.GetStatusBar().GetStatusText(), said)

    def test_importing_the_same_file_again_adds_nothing(self):
        path = self.export_from_other_computer()
        self.frame.catalog.import_csv_from(path)
        self.frame.catalog.import_csv_from(path)
        self.assertEqual(self.frame.timers.list.GetItemCount(), 2)
        self.assertIn("2 таймера вече ги имаше", self.frame.speaker.said[-1])

    def test_old_file_without_timers_is_explained(self):
        path = os.path.join(tempfile.mkdtemp(prefix="kapilands-csv"), "old.csv")
        Path(path).write_text("name;quality;category\nХляб;;Агрокултура\n", encoding="utf-8-sig")
        self.frame.catalog.import_csv_from(path)
        self.assertEqual(self.frame.timers.list.GetItemCount(), 0)
        self.assertIn("няма таймери", self.frame.speaker.said[-1])

    def test_wrong_file_is_a_message_not_a_silent_zero(self):
        path = os.path.join(tempfile.mkdtemp(prefix="kapilands-csv"), "istoriya.csv")
        Path(path).write_text("Потвърдено;Продукт\n01.01.2026;Хляб\n", encoding="utf-8-sig")
        before = len(self.frame.speaker.said)
        self.frame.catalog.import_csv_from(path)
        self.assertTrue(any("Не можах да прочета файла" in m for m in self.messages))
        self.assertEqual(len(self.frame.speaker.said), before)

    def test_export_says_what_is_in_the_file(self):
        self.add()
        self.frame.db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        path = os.path.join(tempfile.mkdtemp(prefix="kapilands-csv"), "katalog.csv")
        self.frame.catalog.export_csv_to(path)
        self.assertIn("1 таймер и 1 компания", self.frame.speaker.said[-1])
        self.assertIn("#timers", Path(path).read_text(encoding="utf-8-sig"))

    def test_file_menu_offers_the_transfer(self):
        menu = self.frame.GetMenuBar().GetMenu(0)
        labels = [item.GetItemLabelText() for item in menu.GetMenuItems()]
        self.assertIn("Изнеси всичко в CSV за друг компютър…", labels)
        self.assertIn("Внеси от CSV от друг компютър…", labels)


class AccountsPanelTest(WxTestCase):
    def test_idle_filter_and_summary(self):
        db = self.frame.db
        db.upsert_account(Account(world="Немска двойка", name="Алфа"))
        db.upsert_account(Account(world="Немска двойка", name="Бета"))
        self.add(line="Алфа")
        panel = self.frame.accounts
        panel.refresh()
        self.assertEqual(panel.list.GetItemCount(), 2)
        self.assertIn("Бездействат 1 от 2", panel.summary.GetValue())
        panel.show_filter.SetSelection(1)
        panel.refresh()
        self.assertEqual(panel.list.GetItemCount(), 1)
        self.assertEqual(panel.list.GetItemText(0, 0), "Бета")


class TextSizeTest(WxTestCase):
    """WCAG 1.4.4: при по-голям текст растат и диалозите, и колоните."""

    def big(self) -> float:
        from kapiland.wxui.common import apply_font_scale

        normal = self.frame.timers.list.GetFont().GetFractionalPointSize()
        apply_font_scale(self.frame, 200)
        return normal * 2

    def test_every_dialog_follows_the_text_size(self):
        from kapiland.wxui.accounts_panel import AccountDialog
        from kapiland.wxui.app import HelpDialog
        from kapiland.wxui.catalog_panel import ProductDialog
        from kapiland.wxui.import_dialog import ImportDialog
        from kapiland.wxui.timer_dialog import TimerDialog

        expected = self.big()
        frame = self.frame
        dialogs = [
            TimerDialog(frame, frame.db, frame.settings),
            ProductDialog(frame, None),
            AccountDialog(frame, frame.db),
            ImportDialog(frame, frame.db, frame.settings, speak=lambda t: None),
            HelpDialog(frame),
        ]
        def everything_in(window):
            for child in window.GetChildren():
                yield child
                yield from everything_in(child)

        try:
            for dialog in dialogs:
                wx.Yield()
                controls = list(everything_in(dialog))
                self.assertGreater(len(controls), 2, dialog.GetTitle())
                for child in controls:
                    self.assertAlmostEqual(
                        child.GetFont().GetFractionalPointSize(), expected, delta=0.5,
                        msg=f"{dialog.GetTitle()}: {child.GetName()}")
        finally:
            for dialog in dialogs:
                dialog.Destroy()

    def test_big_dialogs_stay_on_the_screen_with_their_buttons(self):
        """При 200% диалогът не излиза от екрана; „Запиши“ е извън превъртаното."""
        from kapiland.wxui.accounts_panel import AccountDialog
        from kapiland.wxui.catalog_panel import ProductDialog
        from kapiland.wxui.common import display_area
        from kapiland.wxui.import_dialog import ImportDialog
        from kapiland.wxui.timer_dialog import TimerDialog

        self.big()
        frame = self.frame
        screen = display_area(frame)
        dialogs = [
            TimerDialog(frame, frame.db, frame.settings),
            ProductDialog(frame, None),
            AccountDialog(frame, frame.db),
            ImportDialog(frame, frame.db, frame.settings, speak=lambda t: None),
        ]
        try:
            for dialog in dialogs:
                title = dialog.GetTitle()
                size = dialog.GetSize()
                self.assertLessEqual(size.width, screen.width, title)
                self.assertLessEqual(size.height, screen.height, title)
                ok = dialog.FindWindow(wx.ID_OK)
                self.assertIs(ok.GetParent(), dialog, title)
                # Малък екран: прозорецът се свива, бутонът остава видим в него.
                dialog.SetSize(wx.Size(size.width, min(size.height, 320)))
                dialog.Layout()
                bottom = ok.GetPosition().y + ok.GetSize().height
                self.assertLessEqual(bottom, dialog.GetClientSize().height, title)
                area = ok.GetPrevSibling()
                self.assertIsInstance(area, wx.ScrolledWindow, title)
                self.assertGreater(area.GetVirtualSize().height, area.GetClientSize().height, title)
        finally:
            for dialog in dialogs:
                dialog.Destroy()

    def test_dialogs_keep_their_usual_size_at_normal_text(self):
        from kapiland.wxui.import_dialog import ImportDialog
        from kapiland.wxui.timer_dialog import TimerDialog

        frame = self.frame
        timer = TimerDialog(frame, frame.db, frame.settings)
        importing = ImportDialog(frame, frame.db, frame.settings, speak=lambda t: None)
        try:
            self.assertEqual(timer.GetSize().width, timer.FromDIP(520))
            self.assertEqual(importing.GetSize(), importing.FromDIP(wx.Size(1000, 780)))
        finally:
            timer.Destroy()
            importing.Destroy()

    def test_columns_grow_with_the_text(self):
        timers = self.frame.timers.list
        before = [timers.GetColumnWidth(i) for i in range(timers.GetColumnCount())]
        self.big()
        after = [timers.GetColumnWidth(i) for i in range(timers.GetColumnCount())]
        self.assertEqual(after, [w * 2 for w in before])
        needed = timers.GetTextExtent("ПРОПУСНАТО от вчера 17:00").GetWidth()
        self.assertGreater(after[0], needed)

    def test_countdown_column_is_scaled_too(self):
        self.big()
        panel = self.frame.timers
        panel.set_countdown(True)
        self.assertEqual(panel.list.GetColumnWidth(7), panel.list.FromDIP(95 * 2))
        panel.set_countdown(False)
        self.assertEqual(panel.list.GetColumnCount(), 7)

    def test_details_field_is_tall_enough_for_its_lines(self):
        self.big()
        details = self.frame.timers.details
        self.assertGreaterEqual(details.GetMinSize().GetHeight(), 3 * details.GetCharHeight())


class SettingsPanelTest(WxTestCase):
    def test_changes_are_saved_and_applied(self):
        page = self.frame.settings_page
        page.speech.SetSelection(2)   # никога
        page.reader.SetSelection(2)   # изключен -> колона „Остава“
        page._save()
        self.assertEqual(self.frame.settings.get("speech_mode"), "never")
        self.assertEqual(self.frame.speaker.mode, "never")
        self.assertEqual(self.frame.timers.list.GetColumnCount(), 8)


if __name__ == "__main__":
    unittest.main()
