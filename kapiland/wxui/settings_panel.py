"""Раздел „Настройки“."""

from __future__ import annotations

import os
from pathlib import Path

import wx

from .. import a11y, autostart, catalog
from ..notify import play_sound
from .common import Form, read_only_text

SPEECH = [("auto", "Автоматично — когато работи екранен четец"),
          ("always", "Винаги, когато има през какво"), ("never", "Никога")]
READER = [("auto", "Автоматично"), ("on", "Включен — без обратно броене в списъка"),
          ("off", "Изключен — с колона „Остава“")]
THEMES = [("system", "Като Windows"), ("light", "Светла"), ("dark", "Тъмна")]


class SettingsPanel(wx.Panel):
    def __init__(self, parent, frame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.settings = frame.settings
        self._loading = True

        scroll = wx.BoxSizer(wx.VERTICAL)

        speech_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Екранен четец")
        form = Form(speech_box.GetStaticBox())
        self.speech = form.add("Говор през четеца:", wx.Choice, choices=[t for _k, t in SPEECH])
        self.reader = form.add("Режим за четец:", wx.Choice, choices=[t for _k, t in READER])
        box = speech_box.GetStaticBox()
        self.hotkeys = form.add_full(wx.CheckBox(
            box, label="Глобални клавиши Ctrl+Alt+K (кажи статуса) и Ctrl+Alt+J (покажи прозореца)"))
        self.toast_speaking = form.add_full(wx.CheckBox(
            box, label="Показвай Windows известие и когато четецът вече е казал съобщението"))
        speech_box.Add(form.sizer, 0, wx.EXPAND | wx.ALL, 8)
        self.test_speech = wx.Button(box, label="Пробен говор")
        speech_box.Add(self.test_speech, 0, wx.ALL, 8)
        scroll.Add(speech_box, 0, wx.EXPAND | wx.ALL, 8)

        notify_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Известия")
        box = notify_box.GetStaticBox()
        form = Form(box)
        self.toast = form.add_full(wx.CheckBox(box, label="Показвай Windows известие"))
        self.sound = form.add_full(wx.CheckBox(box, label="Пускай звуков сигнал"))
        self.sound_file = form.add("Собствен звук, файл .wav:", wx.TextCtrl)
        self.prewarn = form.add("Предупреди ме толкова минути преди края (0 = не):", wx.SpinCtrl,
                                min=0, max=1440)
        self.reminder = form.add("Повтаряй известието на толкова минути (0 = не):", wx.SpinCtrl,
                                 min=0, max=240)
        notify_box.Add(form.sizer, 0, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.pick_sound = wx.Button(box, label="Избери звук…")
        self.try_sound = wx.Button(box, label="Пробвай звука")
        self.test_toast = wx.Button(box, label="Пробно известие")
        for button in (self.pick_sound, self.try_sound, self.test_toast):
            row.Add(button, 0, wx.RIGHT, 8)
        notify_box.Add(row, 0, wx.ALL, 8)
        scroll.Add(notify_box, 0, wx.EXPAND | wx.ALL, 8)

        view_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Изглед и работа")
        box = view_box.GetStaticBox()
        form = Form(box)
        worlds = list(catalog.KNOWN_WORLDS)
        self.default_world = form.add("Свят по подразбиране:", wx.ComboBox, choices=worlds)
        self.font = form.add("Размер на текста:", wx.Choice,
                             choices=[f"{s}%" for s in a11y.FONT_SCALES])
        self.theme = form.add("Тема (важи след рестарт):", wx.Choice, choices=[t for _k, t in THEMES])
        self.autostart = form.add_full(wx.CheckBox(box, label="Стартирай заедно с Windows"))
        view_box.Add(form.sizer, 0, wx.EXPAND | wx.ALL, 8)
        scroll.Add(view_box, 0, wx.EXPAND | wx.ALL, 8)

        scroll.Add(wx.StaticText(self, label="Състояние:"), 0, wx.LEFT | wx.RIGHT, 16)
        self.status = read_only_text(self, lines=3)
        self.status.SetName("Състояние")
        scroll.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.open_data = wx.Button(self, label="Отвори папката с данните")
        scroll.Add(self.open_data, 0, wx.LEFT | wx.BOTTOM, 16)
        self.SetSizer(scroll)

        self._load()
        for control in (self.speech, self.reader, self.font, self.theme):
            control.Bind(wx.EVT_CHOICE, lambda _e: self._save())
        for control in (self.hotkeys, self.toast_speaking, self.toast, self.sound):
            control.Bind(wx.EVT_CHECKBOX, lambda _e: self._save())
        for control in (self.prewarn, self.reminder):
            control.Bind(wx.EVT_SPINCTRL, lambda _e: self._save())
        self.sound_file.Bind(wx.EVT_KILL_FOCUS, self._on_text_done)
        self.default_world.Bind(wx.EVT_KILL_FOCUS, self._on_text_done)
        self.default_world.Bind(wx.EVT_COMBOBOX, lambda _e: self._save())
        self.autostart.Bind(wx.EVT_CHECKBOX, lambda _e: self._toggle_autostart())
        self.test_speech.Bind(wx.EVT_BUTTON, lambda _e: self._test_speech())
        self.pick_sound.Bind(wx.EVT_BUTTON, lambda _e: self._pick_sound())
        self.try_sound.Bind(wx.EVT_BUTTON, lambda _e: self._try_sound())
        self.test_toast.Bind(wx.EVT_BUTTON, lambda _e: self._test_toast())
        self.open_data.Bind(wx.EVT_BUTTON, lambda _e: self._open_data())

    # ------------------------------------------------------------ зареждане

    @staticmethod
    def _index(options, key) -> int:
        keys = [k for k, _t in options]
        return keys.index(key) if key in keys else 0

    def _load(self) -> None:
        s = self.settings
        self.speech.SetSelection(self._index(SPEECH, s.get("speech_mode")))
        self.reader.SetSelection(self._index(READER, s.get("reader_mode")))
        self.hotkeys.SetValue(bool(s.get("global_hotkeys")))
        self.toast_speaking.SetValue(bool(s.get("toast_when_speaking")))
        self.toast.SetValue(bool(s.get("toast_enabled")))
        self.sound.SetValue(bool(s.get("sound_enabled")))
        self.sound_file.SetValue(str(s.get("sound_file") or ""))
        self.prewarn.SetValue(int(s.get("prewarn_minutes") or 0))
        self.reminder.SetValue(int(s.get("repeat_reminder_minutes") or 0))
        self.default_world.SetValue(str(s.get("default_world") or ""))
        scale = int(s.get("font_scale") or 100)
        self.font.SetSelection(a11y.FONT_SCALES.index(scale) if scale in a11y.FONT_SCALES else 0)
        self.theme.SetSelection(self._index(THEMES, s.get("theme")))
        self.autostart.SetValue(autostart.is_enabled())
        self.status.SetValue(f"Данните се пазят в: {self.frame.db.path}")
        self._loading = False

    def refresh(self) -> None:
        self._loading = True
        self._load()
        reader = self.frame.speaker.reader_active()
        self.status.SetValue(
            f"Екранен четец: {'работи' if reader else 'не е открит'}. "
            f"{self.frame.hotkey_status} Данните се пазят в: {self.frame.db.path}")

    # --------------------------------------------------------------- запис

    def _on_text_done(self, event) -> None:
        self._save()
        event.Skip()

    def _save(self) -> None:
        if self._loading:
            return
        s = self.settings
        old_hotkeys = bool(s.get("global_hotkeys"))
        s.set("speech_mode", SPEECH[self.speech.GetSelection()][0])
        s.set("reader_mode", READER[self.reader.GetSelection()][0])
        s.set("global_hotkeys", self.hotkeys.GetValue())
        s.set("toast_when_speaking", self.toast_speaking.GetValue())
        s.set("toast_enabled", self.toast.GetValue())
        s.set("sound_enabled", self.sound.GetValue())
        s.set("sound_file", self.sound_file.GetValue().strip())
        s.set("prewarn_minutes", self.prewarn.GetValue())
        s.set("repeat_reminder_minutes", self.reminder.GetValue())
        s.set("default_world", self.default_world.GetValue().strip())
        s.set("font_scale", a11y.FONT_SCALES[max(0, self.font.GetSelection())])
        s.set("theme", THEMES[self.theme.GetSelection()][0])
        s.save()
        self.frame.apply_settings(hotkeys_changed=old_hotkeys != self.hotkeys.GetValue())

    # ------------------------------------------------------------ действия

    def _toggle_autostart(self) -> None:
        ok, text = autostart.enable() if self.autostart.GetValue() else autostart.disable()
        if not ok:
            self.autostart.SetValue(autostart.is_enabled())
        self.status.SetValue(text)
        self.frame.announce(text, interrupt=True)

    def _test_speech(self) -> None:
        backend = self.frame.speaker.speak(
            "Пробен говор от Kapilands Таймер. Така ще звучи, когато нещо е готово.",
            interrupt=True)
        names = {"nvda": "през NVDA", "jaws": "през JAWS", "uia": "през Windows UI Automation"}
        text = (f"Говорът работи {names.get(backend, backend)}." if backend else
                "Не открих екранен четец, през който да говоря. Ако ползваш такъв, "
                "избери „Винаги“ и опитай пак.")
        self.status.SetValue(text)

    def _pick_sound(self) -> None:
        with wx.FileDialog(self.frame, "Избор на звук", wildcard="Звуков файл (*.wav)|*.wav",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.sound_file.SetValue(dialog.GetPath())
                self._save()

    def _try_sound(self) -> None:
        played = play_sound(self.sound_file.GetValue().strip(), True)
        self.status.SetValue("Звукът е пуснат." if played else "Не успях да пусна звука.")

    def _test_toast(self) -> None:
        backend = self.frame.notifier.notify("Пробно известие",
                                             "Така ще изглежда, когато нещо стане готово.")
        self.status.SetValue(f"Известие: {backend}.")

    def _open_data(self) -> None:
        folder = str(Path(self.frame.db.path).parent)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            self.status.SetValue(folder)
