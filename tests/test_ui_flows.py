"""Тестове през самия интерфейс — както го ползва човек.

Тези тестове вдигат истински прозорци и минават по пътищата, по които
минава потребителят: диалогът за нов таймер, бутоните, каталогът,
настройките, изнасянето в CSV. Ако на машината няма екран, се прескачат.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEMP_APPDATA = tempfile.mkdtemp(prefix="kapilands-uitest")
os.environ["APPDATA"] = _TEMP_APPDATA  # преди да се зареди config

try:
    import tkinter as tk

    _root = tk.Tk()
    _root.destroy()
    HAS_DISPLAY = True
except Exception:  # pragma: no cover - зависи от машината
    HAS_DISPLAY = False

from kapiland import a11y, catalog
from kapiland.models import Timer, TimerStatus
from kapiland.timeutil import HOUR, MINUTE, format_dt, now as time_now


def _app():
    """Ново приложение със собствени настройки и база — без общо състояние."""
    from kapiland.ui.app import KapilandsApp

    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="kapilands-appdata")
    db_file = os.path.join(tempfile.mkdtemp(prefix="kapilands-db"), "test.db")
    app = KapilandsApp(db_file)
    app.settings.set("toast_enabled", False)   # без известия по време на тест
    app.settings.set("sound_enabled", False)
    return app


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class TimerDialogFlowTest(unittest.TestCase):
    """Диалогът за нов таймер — трите начина за въвеждане."""

    def setUp(self):
        self.app = _app()

    def tearDown(self):
        self.app.quit()

    def dialog(self, timer=None):
        from kapiland.ui.timer_dialog import TimerDialog

        return TimerDialog(self.app.root, self.app.style, self.app.db,
                           self.app.settings, timer)

    def test_start_and_duration(self):
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.quantity_var.set("500")
        dlg.line_var.set("Линия 2")
        dlg.mode_var.set("start")
        dlg.start_var.set("12.09.2026 14:30")
        dlg.duration_var.set("3ч 45м")
        dlg._on_mode_change()
        self.assertIn("Край:", dlg.preview_var.get())
        dlg._save()

        timer = dlg.result
        self.assertIsNotNone(timer)
        self.assertEqual(timer.product, "Хляб")
        self.assertEqual(timer.quantity, 500)
        self.assertEqual(timer.line, "Линия 2")
        self.assertEqual(timer.duration_sec, 3 * HOUR + 45 * MINUTE)
        self.assertEqual(format_dt(timer.end_at, "%d.%m.%Y %H:%M"), "12.09.2026 18:15")

    def test_exact_end_time(self):
        dlg = self.dialog()
        dlg.product_var.set("Сирене")
        dlg.mode_var.set("end")
        dlg.start_var.set("12.09.2026 14:30")
        dlg.end_var.set("12.09.2026 18:15")
        dlg._on_mode_change()
        dlg._save()
        self.assertEqual(dlg.result.duration_sec, 3 * HOUR + 45 * MINUTE)

    def test_remaining_time_copied_from_the_game(self):
        dlg = self.dialog()
        dlg.product_var.set("Стомана")
        dlg.mode_var.set("remaining")
        dlg.remaining_var.set("03:42:10")
        dlg._on_mode_change()
        before = time_now()
        dlg._save()
        timer = dlg.result
        self.assertEqual(timer.duration_sec, 3 * HOUR + 42 * MINUTE + 10)
        self.assertAlmostEqual(timer.end_at - before, 13330, delta=5)

    def test_invalid_duration_does_not_save(self):
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.duration_var.set("глупости")
        dlg._save()
        self.assertIsNone(dlg.result)
        self.assertIn("⚠", dlg.preview_var.get())
        self.assertTrue(dlg.winfo_exists())  # диалогът остава отворен
        dlg._cancel()

    def test_escape_cancels_without_saving(self):
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.duration_var.set("1ч")
        dlg._cancel()
        self.assertIsNone(dlg.result)

    def test_preview_shows_throughput_and_profit(self):
        from kapiland.models import Product

        self.app.db.upsert_product(Product(name="Хляб", unit_cost=2, unit_price=5))
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.quantity_var.set("100")
        dlg.duration_var.set("2ч")
        dlg._update_preview()
        preview = dlg.preview_var.get()
        self.assertIn("Производителност", preview)
        self.assertIn("Печалба", preview)
        self.assertIn("300", preview)   # (5-2) * 100
        dlg._cancel()

    def test_selecting_a_product_prefills_remembered_values(self):
        timer = Timer(product="Хляб", quantity=500, duration_sec=4 * HOUR,
                      start_at=time_now(), end_at=time_now() + 4 * HOUR)
        self.app.db.remember_product(timer)
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg._on_product_selected()
        self.assertEqual(dlg.duration_var.get(), "04:00:00")
        self.assertEqual(dlg.quantity_var.get(), "500")
        dlg._cancel()

    def test_quality_is_saved_and_shown(self):
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.quality_var.set("Q3")
        dlg.quantity_var.set("500")
        dlg.duration_var.set("1ч")
        dlg._save()
        self.assertEqual(dlg.result.quality, "Q3")
        self.assertEqual(dlg.result.display_name, "500× Хляб [Q3]")

    def test_prefill_uses_the_matching_quality(self):
        """Едно име в две качества трябва да предлага различно време."""
        for quality, seconds in (("Q1", HOUR), ("Q5", 4 * HOUR)):
            self.app.db.remember_product(
                Timer(product="Хляб", quality=quality, quantity=100,
                      duration_sec=seconds, start_at=time_now(),
                      end_at=time_now() + seconds))
        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.quality_var.set("Q5")
        dlg._on_product_selected()
        self.assertEqual(dlg.duration_var.get(), "04:00:00")
        dlg._cancel()

        dlg = self.dialog()
        dlg.product_var.set("Хляб")
        dlg.quality_var.set("Q1")
        dlg._on_product_selected()
        self.assertEqual(dlg.duration_var.get(), "01:00:00")
        dlg._cancel()

    def test_known_qualities_are_offered(self):
        from kapiland.models import Product

        self.app.db.upsert_product(Product(name="Хляб", quality="Q7"))
        dlg = self.dialog()
        self.assertIn("Q7", dlg._known_qualities())
        dlg._cancel()

    def test_editing_keeps_the_id_and_rearms_the_notification(self):
        timer = Timer(product="Хляб", start_at=time_now() - HOUR,
                      end_at=time_now() - 1, duration_sec=HOUR,
                      notified_at=time_now(), missed=1)
        self.app.db.add_timer(timer)
        dlg = self.dialog(timer)
        dlg.duration_var.set("2ч")
        dlg.mode_var.set("start")
        dlg._on_mode_change()
        dlg._save()
        self.assertEqual(dlg.result.id, timer.id)
        self.assertIsNone(dlg.result.notified_at)
        self.assertEqual(dlg.result.missed, 0)


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class TimersViewButtonsTest(unittest.TestCase):
    """Бутоните на главния екран."""

    def setUp(self):
        self.app = _app()
        self.view = self.app.timers_view

    def tearDown(self):
        self.app.quit()

    def add(self, **kwargs) -> Timer:
        now = time_now()
        data = dict(product="Хляб", quantity=500, line="Линия 1",
                    start_at=now - 10, end_at=now + HOUR, duration_sec=HOUR)
        data.update(kwargs)
        timer = Timer(**data)
        self.app.db.add_timer(timer)
        self.view.refresh(full=True)
        return timer

    def select(self, timer: Timer) -> None:
        self.view.tree.selection_set(str(timer.id))

    def test_table_shows_the_timer(self):
        timer = self.add()
        self.assertIn(str(timer.id), self.view.tree.get_children())
        values = self.view.tree.item(str(timer.id))["values"]
        self.assertIn("Хляб", values)
        self.assertIn("върви", values[0])

    def test_due_timer_is_marked_in_text_not_only_in_colour(self):
        timer = self.add(end_at=time_now() - 5)
        self.view.refresh(full=True)
        row = self.view.tree.item(str(timer.id))
        self.assertIn("ГОТОВО", row["values"][0])
        self.assertEqual(list(row["tags"]), ["due"])

    def test_quality_has_its_own_column(self):
        timer = self.add(quality="Q3")
        values = self.view.tree.item(str(timer.id))["values"]
        self.assertIn("Q3", values)

    def test_row_without_quality_shows_a_dash(self):
        timer = self.add(quality="")
        values = self.view.tree.item(str(timer.id))["values"]
        self.assertEqual(values[2], "—")

    def test_new_cycle_keeps_the_quality(self):
        timer = self.add(quality="Q3")
        self.select(timer)
        self.view.restart_selected()
        active = self.app.db.list_timers(TimerStatus.RUNNING.value)
        self.assertTrue(all(t.quality == "Q3" for t in active))

    def test_incremental_refresh_also_flips_the_row_to_done(self):
        """Тикът обновява клетките без преначертаване — състоянието пак се сменя."""
        timer = self.add(end_at=time_now() + 1)
        self.assertIn("върви", self.view.tree.item(str(timer.id))["values"][0])
        self.app.db.set_timer_fields(timer.id, end_at=time_now() - 1)
        self.view.refresh(full=False)
        row = self.view.tree.item(str(timer.id))
        self.assertIn("ГОТОВО", row["values"][0])
        self.assertEqual(list(row["tags"]), ["due"])

    def test_incremental_refresh_picks_up_a_new_timer(self):
        self.add(product="Хляб")
        self.add(product="Сирене")
        self.view.refresh(full=False)
        self.assertEqual(len(self.view.tree.get_children()), 2)

    def test_buttons_without_selection_only_warn(self):
        self.view.tree.selection_remove(*self.view.tree.selection())
        for action in (self.view.edit_timer, self.view.complete_selected,
                       self.view.restart_selected, self.view.cancel_selected,
                       self.view.delete_selected):
            action()
            self.assertIn("изберете", self.app.status_var.get().lower())

    def test_complete_moves_to_history(self):
        timer = self.add(end_at=time_now() - 5)
        self.select(timer)
        self.view.complete_selected()
        self.assertEqual(self.app.db.get_timer(timer.id).status,
                         TimerStatus.DONE.value)
        self.assertEqual(len(self.app.db.list_history()), 1)
        self.assertNotIn(str(timer.id), self.view.tree.get_children())

    def test_complete_starts_the_next_cycle(self):
        timer = self.add(end_at=time_now() - 5, repeat_enabled=1, cycles_planned=3)
        self.select(timer)
        self.view.complete_selected()
        active = self.app.db.list_timers(TimerStatus.RUNNING.value)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].cycle_no, 2)
        self.assertIn("цикъл 2/3", self.app.status_var.get())

    def test_complete_all_due(self):
        self.add(product="Хляб", end_at=time_now() - 5)
        self.add(product="Сирене", end_at=time_now() - 3)
        self.add(product="Стомана", end_at=time_now() + HOUR)  # още върви
        self.view.complete_all_due()
        self.assertEqual(len(self.app.db.list_history()), 2)
        self.assertEqual(len(self.app.db.list_timers(TimerStatus.RUNNING.value)), 1)

    def test_restart_creates_a_new_running_timer(self):
        timer = self.add()
        self.select(timer)
        self.view.restart_selected()
        active = self.app.db.list_timers(TimerStatus.RUNNING.value)
        self.assertEqual(len(active), 2)
        self.assertIn("Нов цикъл", self.app.status_var.get())

    def test_cancel_stops_the_timer(self):
        timer = self.add()
        self.select(timer)
        self.view.cancel_selected()
        self.assertEqual(self.app.db.get_timer(timer.id).status,
                         TimerStatus.CANCELLED.value)

    def test_delete_asks_first(self):
        from kapiland.ui import timers_view

        timer = self.add()
        self.select(timer)
        original = timers_view.messagebox.askyesno
        try:
            timers_view.messagebox.askyesno = lambda *a, **k: False
            self.view.delete_selected()
            self.assertIsNotNone(self.app.db.get_timer(timer.id))

            timers_view.messagebox.askyesno = lambda *a, **k: True
            self.view.delete_selected()
            self.assertIsNone(self.app.db.get_timer(timer.id))
        finally:
            timers_view.messagebox.askyesno = original

    def test_summary_reports_free_lines_and_next_due(self):
        self.add(line="Линия 1", end_at=time_now() + 600)
        self.view.refresh(full=True)
        summary = self.view.summary_var.get()
        self.assertIn("Следващ готов", summary)
        self.assertIn("Свободни линии", summary)
        self.assertIn("Линия 2", summary)

    def test_details_panel_describes_the_selection_in_words(self):
        timer = self.add(end_at=time_now() + 2 * HOUR)
        self.select(timer)
        self.view._update_details()
        details = self.view.details_var.get()
        self.assertIn("500× Хляб", details)
        self.assertIn("часа", details)     # изписано с думи, не само 02:00:00
        self.assertIn("Статус", details)

    def test_sorting_by_column_does_not_break(self):
        self.add(product="Хляб", end_at=time_now() + HOUR)
        self.add(product="Сирене", end_at=time_now() + 2 * HOUR)
        for key, *_rest in timers_columns():
            self.view._sort_by(key)
            self.assertEqual(len(self.view.tree.get_children()), 2)


def timers_columns():
    from kapiland.ui.timers_view import COLUMNS

    return COLUMNS


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class CatalogViewTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.view = self.app.catalog_view

    def tearDown(self):
        self.app.quit()

    def test_seed_products_are_listed(self):
        self.view.refresh()
        self.assertGreater(len(self.view.tree.get_children()), 10)

    def test_product_dialog_saves(self):
        from kapiland.ui.catalog_view import ProductDialog

        dlg = ProductDialog(self.app.root, self.app.style, None)
        dlg.name_var.set("Тестов продукт")
        dlg.duration_var.set("2ч 30м")
        dlg.quantity_var.set("100")
        dlg.cost_var.set("1,5")     # десетична запетая
        dlg.price_var.set("4.5")
        dlg._save()
        self.assertIsNotNone(dlg.result)
        self.app.db.upsert_product(dlg.result)

        stored = self.app.db.get_product("Тестов продукт")
        self.assertEqual(stored.default_duration_sec, 2 * HOUR + 30 * MINUTE)
        self.assertAlmostEqual(stored.unit_cost, 1.5)
        self.assertAlmostEqual(stored.unit_price, 4.5)

    def test_product_dialog_rejects_empty_name(self):
        from kapiland.ui.catalog_view import ProductDialog

        dlg = ProductDialog(self.app.root, self.app.style, None)
        dlg.name_var.set("   ")
        dlg._save()
        self.assertIsNone(dlg.result)
        self.assertIn("⚠", dlg.error_var.get())
        dlg._cancel()

    def test_profit_per_hour_column_and_hint(self):
        from kapiland.models import Product

        self.app.db.upsert_product(Product(
            name="Доходен", default_duration_sec=HOUR, default_quantity=100,
            unit_cost=1, unit_price=6))
        self.view.refresh()
        self.assertIn("Доходен", self.view.hint_var.get())
        self.assertIn("500", self.view.hint_var.get())   # (6-1)*100 за час

    def test_csv_export_and_import_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "katalog.csv"
        count = catalog.export_csv(self.app.db, path)
        self.assertGreater(count, 0)
        self.assertTrue(path.exists())

        # Изтриваме всичко и връщаме от файла.
        for product in self.app.db.list_products():
            self.app.db.delete_product(product.id)
        self.assertEqual(self.app.db.list_products(), [])

        imported = catalog.import_csv(self.app.db, path)
        self.assertEqual(imported, count)
        self.assertEqual(len(self.app.db.list_products()), count)

    def test_csv_import_accepts_comma_separated_file(self):
        path = Path(tempfile.mkdtemp()) / "zapetai.csv"
        path.write_text(
            "name,category,default_duration_sec,unit_price\n"
            "Ръчен продукт,Храни,7200,9.5\n", encoding="utf-8-sig")
        catalog.import_csv(self.app.db, path)
        stored = self.app.db.get_product("Ръчен продукт")
        self.assertEqual(stored.default_duration_sec, 7200)
        self.assertAlmostEqual(stored.unit_price, 9.5)


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class HistoryViewTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.view = self.app.history_view

    def tearDown(self):
        self.app.quit()

    def _finish_a_cycle(self, product="Хляб", profit=300.0):
        now = time_now()
        timer = Timer(product=product, quantity=100, start_at=now - HOUR,
                      end_at=now, duration_sec=HOUR)
        self.app.db.add_timer(timer)
        self.app.db.complete_timer(timer.id, now, profit)

    def test_empty_history_explains_itself(self):
        self.view.refresh()
        self.assertIn("няма завършени", self.view.total_var.get().lower())

    def test_finished_cycles_and_summary(self):
        self._finish_a_cycle()
        self._finish_a_cycle()
        self._finish_a_cycle(product="Стомана", profit=100.0)
        self.view.refresh()
        self.assertEqual(len(self.view.log.get_children()), 3)
        self.assertEqual(len(self.view.summary.get_children()), 2)
        total = self.view.total_var.get()
        self.assertIn("3 завършени", total)
        self.assertIn("Хляб", total)   # най-доходен

    def test_export_writes_a_readable_file(self):
        import csv as csv_module
        from kapiland.ui import history_view

        self._finish_a_cycle()
        path = Path(tempfile.mkdtemp()) / "istoriya.csv"
        original = history_view.filedialog.asksaveasfilename
        try:
            history_view.filedialog.asksaveasfilename = lambda *a, **k: str(path)
            self.view.export()
        finally:
            history_view.filedialog.asksaveasfilename = original

        self.assertTrue(path.exists())
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv_module.reader(handle, delimiter=";"))
        self.assertEqual(rows[0][1], "Продукт")
        self.assertEqual(rows[1][1], "Хляб")

    def test_clear_asks_first(self):
        from kapiland.ui import history_view

        self._finish_a_cycle()
        original = history_view.messagebox.askyesno
        try:
            history_view.messagebox.askyesno = lambda *a, **k: False
            self.view.clear()
            self.assertEqual(len(self.app.db.list_history()), 1)

            history_view.messagebox.askyesno = lambda *a, **k: True
            self.view.clear()
            self.assertEqual(self.app.db.list_history(), [])
        finally:
            history_view.messagebox.askyesno = original


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class SettingsViewTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.view = self.app.settings_view

    def tearDown(self):
        self.app.quit()

    def test_saving_settings_persists_them(self):
        self.view.prewarn_var.set("10")
        self.view.reminder_var.set("3")
        self.view.lines_var.set("8")
        self.view.collision_var.set("7")
        self.view._save()
        self.assertEqual(self.app.settings.get("prewarn_minutes"), 10)
        self.assertEqual(self.app.settings.get("repeat_reminder_minutes"), 3)
        self.assertEqual(self.app.settings.get("default_lines"), 8)
        self.assertEqual(self.app.scheduler.soon_seconds(), 600)

    def test_bad_numbers_fall_back_instead_of_crashing(self):
        self.view.lines_var.set("глупост")
        self.view.prewarn_var.set("")
        self.view._save()
        self.assertEqual(self.app.settings.get("default_lines"), 4)
        self.assertEqual(self.app.settings.get("prewarn_minutes"), 0)

    def test_changing_theme_applies_everywhere(self):
        for name, data in a11y.THEMES.items():
            self.view.theme_var.set(data["label"])
            self.app.root.update_idletasks()
            self.assertEqual(self.app.theme_name, name)
            self.assertEqual(self.app.style.colors["bg"], data["bg"])
            self.assertEqual(self.app.settings.get("theme"), name)

    def test_text_scales_to_200_percent(self):
        self.view.scale_var.set("200%")
        self.app.root.update_idletasks()
        self.assertEqual(self.app.style.font_scale, 200)
        self.assertEqual(self.app.style.base_font.cget("size"),
                         a11y.scaled_font_size(200))
        self.assertGreaterEqual(self.app.style.row_height(), 48)
        self.assertEqual(self.app.settings.get("font_scale"), 200)

    def test_keyboard_shortcut_changes_the_scale(self):
        start = self.app.style.font_scale
        self.app._bump_scale(1)
        self.assertGreater(self.app.style.font_scale, start)
        self.app._bump_scale(-1)
        self.assertEqual(self.app.style.font_scale, start)

    def test_autostart_shortcut_path_points_to_startup_folder(self):
        path = self.view._shortcut_path()
        self.assertIn("Startup", str(path))
        target, arguments = self.view._launch_target()
        self.assertTrue(target)
        self.assertTrue(Path(target).exists())


@unittest.skipUnless(HAS_DISPLAY, "няма графична среда")
class AppShellTest(unittest.TestCase):
    """Прозорецът като цяло: раздели, тик, наваксване, запазване."""

    def setUp(self):
        self.app = _app()

    def tearDown(self):
        try:
            self.app.quit()
        except Exception:
            pass

    def test_all_tabs_render(self):
        for index in range(4):
            self.app.notebook.select(index)
            self.app.root.update()
        self.assertEqual(len(self.app.notebook.tabs()), 4)

    def test_keyboard_help_opens_and_closes(self):
        before = len(self.app.root.winfo_children())
        self.app.show_keyboard_help()
        self.app.root.update()
        windows = [w for w in self.app.root.winfo_children()
                   if isinstance(w, tk.Toplevel)]
        self.assertTrue(windows)
        windows[-1].destroy()
        self.app.root.update()
        self.assertEqual(len(self.app.root.winfo_children()), before)

    def test_tick_marks_a_timer_due_and_updates_the_status_bar(self):
        now = time_now()
        self.app.db.add_timer(Timer(product="Хляб", quantity=500, line="Линия 1",
                                    start_at=now - HOUR, end_at=now - 1,
                                    duration_sec=HOUR))
        events = self.app.scheduler.tick()
        self.assertEqual([e.kind for e in events], ["due"])
        self.app.timers_view.refresh(full=True)
        summary = self.app.timers_view.summary_var.get()
        self.assertIn("ГОТОВИ (1)", summary)
        self.assertIn("Хляб", summary)

    def test_fallback_notification_window_appears(self):
        """Ако Windows известията не тръгнат, потребителят пак вижда прозорец."""
        self.app.notifier.fallback("Готово: Хляб", "Пусни следваща продукция.")
        self.app.root.update()
        windows = [w for w in self.app.root.winfo_children()
                   if isinstance(w, tk.Toplevel)]
        self.assertTrue(windows, "няма резервен прозорец за известие")
        windows[-1].destroy()

    def test_settings_and_data_survive_a_restart(self):
        from kapiland.ui.app import KapilandsApp

        db_path = self.app.db.path
        now = time_now()
        self.app.db.add_timer(Timer(product="Хляб", quantity=500,
                                    start_at=now, end_at=now + HOUR,
                                    duration_sec=HOUR))
        self.app.settings.set("default_lines", 9)
        self.app.settings.save()
        self.app.quit()

        again = KapilandsApp(db_path)
        try:
            self.assertEqual(again.settings.get("default_lines"), 9)
            self.assertEqual(len(again.db.list_timers(TimerStatus.RUNNING.value)), 1)
            self.assertEqual(len(again.timers_view.tree.get_children()), 1)
        finally:
            again.quit()
        self.app = again

    def test_startup_reports_timers_that_expired_while_closed(self):
        from kapiland.ui.app import KapilandsApp

        db_path = self.app.db.path
        now = time_now()
        self.app.db.add_timer(Timer(product="Наука", start_at=now - 2 * HOUR,
                                    end_at=now - HOUR, duration_sec=HOUR,
                                    type="research"))
        self.app.quit()

        again = KapilandsApp(db_path)
        try:
            again.settings.set("toast_enabled", False)
            status = again.status_var.get()
            self.assertIn("изтекоха", status)
            self.assertIn("Наука", status)
        finally:
            again.quit()
        self.app = again


if __name__ == "__main__":
    unittest.main()
