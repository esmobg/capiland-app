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
