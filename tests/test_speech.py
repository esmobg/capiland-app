"""Тестове за говора през екранния четец (с фалшиви NVDA, JAWS и UIA)."""

import unittest

from kapiland import speech
from kapiland.speech import (
    MODE_ALWAYS,
    MODE_AUTO,
    MODE_NEVER,
    AnnouncementQueue,
    JawsBackend,
    NvdaBackend,
    Speaker,
)


class FakeBackend:
    def __init__(self, name, available=True, succeeds=True, raises=False):
        self.name = name
        self._available = available
        self._succeeds = succeeds
        self._raises = raises
        self.spoken = []
        self.cancelled = 0

    def available(self):
        if self._raises:
            raise RuntimeError("счупен")
        return self._available

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return self._succeeds

    def cancel(self):
        self.cancelled += 1


def speaker(backends, mode=MODE_AUTO, locked=False, reader=True):
    return Speaker(backends, mode=mode, is_locked=lambda: locked,
                   reader_active=lambda: reader)


class SpeakerChoiceTest(unittest.TestCase):
    def test_first_available_backend_speaks(self):
        nvda = FakeBackend("nvda")
        jaws = FakeBackend("jaws")
        self.assertEqual(speaker([nvda, jaws]).speak("Готово: Бензин"), "nvda")
        self.assertEqual(nvda.spoken, [("Готово: Бензин", False)])
        self.assertEqual(jaws.spoken, [])

    def test_falls_through_to_jaws_when_nvda_is_not_running(self):
        nvda = FakeBackend("nvda", available=False)
        jaws = FakeBackend("jaws")
        self.assertEqual(speaker([nvda, jaws]).speak("текст"), "jaws")

    def test_falls_through_when_a_backend_fails_to_speak(self):
        nvda = FakeBackend("nvda", succeeds=False)
        uia = FakeBackend("uia")
        self.assertEqual(speaker([nvda, uia]).speak("текст"), "uia")

    def test_broken_backend_does_not_stop_the_others(self):
        broken = FakeBackend("nvda", raises=True)
        jaws = FakeBackend("jaws")
        self.assertEqual(speaker([broken, jaws]).speak("текст"), "jaws")

    def test_nothing_available_returns_none(self):
        self.assertIsNone(speaker([FakeBackend("nvda", available=False)]).speak("х"))

    def test_remembers_what_it_said(self):
        s = speaker([FakeBackend("nvda")])
        s.speak("Готово: Легла")
        self.assertEqual(s.last_backend, "nvda")
        self.assertEqual(s.last_text, "Готово: Легла")

    def test_interrupt_is_passed_on(self):
        nvda = FakeBackend("nvda")
        speaker([nvda]).speak("спешно", interrupt=True)
        self.assertEqual(nvda.spoken, [("спешно", True)])

    def test_empty_text_is_not_spoken(self):
        nvda = FakeBackend("nvda")
        self.assertIsNone(speaker([nvda]).speak("   "))
        self.assertEqual(nvda.spoken, [])


class SpeakerModesTest(unittest.TestCase):
    def test_auto_is_silent_without_a_screen_reader(self):
        nvda = FakeBackend("nvda")
        self.assertIsNone(speaker([nvda], MODE_AUTO, reader=False).speak("х"))
        self.assertEqual(nvda.spoken, [])

    def test_always_speaks_even_without_the_flag(self):
        nvda = FakeBackend("nvda")
        self.assertEqual(speaker([nvda], MODE_ALWAYS, reader=False).speak("х"), "nvda")

    def test_never_is_always_silent(self):
        nvda = FakeBackend("nvda")
        self.assertIsNone(speaker([nvda], MODE_NEVER).speak("х"))

    def test_locked_windows_is_never_spoken_to(self):
        """Препоръка на NV Access: без говор на заключен екран."""
        nvda = FakeBackend("nvda")
        self.assertIsNone(speaker([nvda], MODE_ALWAYS, locked=True).speak("тайна"))
        self.assertEqual(nvda.spoken, [])

    def test_lock_check_failure_means_silence(self):
        nvda = FakeBackend("nvda")
        s = Speaker([nvda], mode=MODE_ALWAYS,
                    is_locked=lambda: (_ for _ in ()).throw(OSError()),
                    reader_active=lambda: True)
        self.assertIsNone(s.speak("х"))

    def test_cancel_reaches_every_backend(self):
        a, b = FakeBackend("nvda"), FakeBackend("jaws")
        speaker([a, b]).cancel()
        self.assertEqual((a.cancelled, b.cancelled), (1, 1))


class FakeNvdaLib:
    """Имитира nvdaControllerClient.dll."""

    class _Func:
        def __init__(self, owner, name, result=0):
            self.owner, self.name, self.result = owner, name, result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            self.owner.calls.append((self.name,) + args)
            return self.result

    def __init__(self, running=True):
        self.calls = []
        self.nvdaController_testIfRunning = self._Func(
            self, "test", 0 if running else 1717)
        self.nvdaController_speakText = self._Func(self, "speak")
        self.nvdaController_brailleMessage = self._Func(self, "braille")
        self.nvdaController_cancelSpeech = self._Func(self, "cancel")


class NvdaBackendTest(unittest.TestCase):
    def test_speaks_and_brailles(self):
        lib = FakeNvdaLib()
        backend = NvdaBackend(dll_path="fake.dll", loader=lambda _p: lib)
        self.assertTrue(backend.available())
        self.assertTrue(backend.speak("Готово: Бензин"))
        self.assertIn(("speak", "Готово: Бензин"), lib.calls)
        self.assertIn(("braille", "Готово: Бензин"), lib.calls)

    def test_interrupt_cancels_first(self):
        lib = FakeNvdaLib()
        backend = NvdaBackend(dll_path="fake.dll", loader=lambda _p: lib)
        backend.speak("х", interrupt=True)
        names = [c[0] for c in lib.calls]
        self.assertLess(names.index("cancel"), names.index("speak"))

    def test_not_running(self):
        backend = NvdaBackend(dll_path="fake.dll",
                              loader=lambda _p: FakeNvdaLib(running=False))
        self.assertFalse(backend.available())

    def test_missing_dll_is_unavailable_not_an_error(self):
        def loader(_path):
            raise OSError("няма файл")

        backend = NvdaBackend(dll_path="nyama.dll", loader=loader)
        self.assertFalse(backend.available())
        self.assertFalse(backend.speak("х"))

    def test_real_dll_is_shipped(self):
        path = speech.vendor_path("nvda", "x64", "nvdaControllerClient.dll")
        self.assertTrue(path.exists(), path)
        self.assertTrue(speech.vendor_path("nvda", "license.txt").exists())

    @unittest.skipUnless(speech.IS_WINDOWS, "само за Windows")
    def test_real_dll_loads(self):
        backend = NvdaBackend()
        self.assertIsNotNone(backend._library())
        backend.available()  # не хвърля, дори NVDA да не работи


class FakeJaws:
    def __init__(self, fail=False):
        self.said = []
        self.stopped = 0
        self.fail = fail

    def SayString(self, text, flush):
        if self.fail:
            raise OSError("RPC")
        self.said.append((text, flush))
        return True

    def StopSpeech(self):
        self.stopped += 1


class JawsBackendTest(unittest.TestCase):
    def test_speaks_through_com(self):
        api = FakeJaws()
        backend = JawsBackend(factory=lambda: api, is_running=lambda: True)
        self.assertTrue(backend.available())
        self.assertTrue(backend.speak("Готово", interrupt=True))
        self.assertEqual(api.said, [("Готово", True)])

    def test_unavailable_when_jaws_is_not_running(self):
        backend = JawsBackend(factory=FakeJaws, is_running=lambda: False)
        self.assertFalse(backend.available())

    def test_com_error_on_create_is_unavailable(self):
        def factory():
            raise OSError("Class not registered")

        backend = JawsBackend(factory=factory, is_running=lambda: True)
        self.assertFalse(backend.available())

    def test_restarted_jaws_is_reconnected(self):
        objects = [FakeJaws(fail=True), FakeJaws()]
        backend = JawsBackend(factory=lambda: objects.pop(0), is_running=lambda: True)
        self.assertFalse(backend.speak("първи опит"))
        self.assertTrue(backend.speak("втори опит"))


class SystemChecksTest(unittest.TestCase):
    """Истинските системни проверки не бива да гърмят."""

    def test_calls_return_plain_values(self):
        self.assertIsInstance(speech.screen_reader_flag(), bool)
        self.assertIsInstance(speech.running_readers(), set)
        self.assertIsInstance(speech.session_locked(), bool)


class AnnouncementQueueTest(unittest.TestCase):
    def test_waits_for_the_delay(self):
        q = AnnouncementQueue(delay=1.5)
        q.add("Готово: Бензин", now=100.0)
        self.assertFalse(q.ready(100.5))
        self.assertTrue(q.ready(101.6))

    def test_joins_close_messages_into_one_sentence(self):
        q = AnnouncementQueue(delay=1.5)
        q.add("Готово: Бензин", now=100.0)
        q.add("Готово: Легла.", now=100.4)
        self.assertEqual(q.pop(), "Готово: Бензин. Готово: Легла.")
        self.assertEqual(len(q), 0)

    def test_duplicates_are_dropped(self):
        q = AnnouncementQueue()
        q.add("х", 1.0)
        q.add("х", 1.1)
        self.assertEqual(len(q), 1)

    def test_empty_queue(self):
        q = AnnouncementQueue()
        self.assertFalse(q.ready(1e9))
        self.assertEqual(q.pop(), "")


if __name__ == "__main__":
    unittest.main()
