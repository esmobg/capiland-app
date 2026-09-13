"""Говор през екранния четец — NVDA, JAWS или Windows (UI Automation).

Приложението не синтезира собствен глас: пише към четеца, който потребителят
вече ползва, с неговия глас, скорост и брайлов дисплей.

Начини, по реда на пробване:

1. **NVDA** — официалната ``nvdaControllerClient.dll`` (``vendor/nvda``).
   Работи и когато прозорецът е във фонов режим.
2. **JAWS** — COM обектът ``FreedomSci.JawsApi``, който JAWS регистрира сам.
3. **UI Automation** — ``UiaRaiseNotificationEvent``: за Narrator и като
   резерва за всеки четец, когато прозорецът е отпред.

Ако Windows е заключен или е на защитен екран, не се говори нищо — такава е и
препоръката на NV Access, за да не се изричат данни на заключения екран.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Iterable

IS_WINDOWS = sys.platform == "win32"

SPI_GETSCREENREADER = 0x0046
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2

MODE_AUTO = "auto"      # говори, само ако работи екранен четец
MODE_ALWAYS = "always"  # говори винаги, когато има през какво
MODE_NEVER = "never"

READER_PROCESSES = {"nvda.exe": "nvda", "jfw.exe": "jaws", "narrator.exe": "narrator"}


# --------------------------------------------------------------- системни

def screen_reader_flag() -> bool:
    """Флагът, който NVDA, JAWS и Narrator вдигат, докато работят."""
    if not IS_WINDOWS:
        return False
    value = wintypes.BOOL(False)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETSCREENREADER, 0, ctypes.byref(value), 0)
    except (AttributeError, OSError):
        return False
    return bool(ok) and bool(value.value)


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def running_readers() -> set[str]:
    """Кои екранни четци работят в момента: {'nvda', 'jaws', 'narrator'}."""
    if not IS_WINDOWS:
        return set()
    found: set[str] = set()
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return found
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            reader = READER_PROCESSES.get(entry.szExeFile.lower())
            if reader:
                found.add(reader)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def session_locked() -> bool:
    """True, ако Windows е заключен или показва защитен екран (UAC и т.н.)."""
    if not IS_WINDOWS:
        return False
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    desktop = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not desktop:
        return True  # няма достъп до входния работен плот = заключено
    try:
        buffer = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD(0)
        if not user32.GetUserObjectInformationW(
                desktop, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
            return False
        return buffer.value.lower() != "default"
    finally:
        user32.CloseDesktop(desktop)


def vendor_path(*parts: str) -> Path:
    """Път до файл от ``vendor`` — и от изходния код, и от .exe."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[1]
    return root.joinpath("vendor", *parts)


# ------------------------------------------------------------------ NVDA

class NvdaBackend:
    name = "nvda"

    def __init__(self, dll_path: str | os.PathLike | None = None,
                 loader: Callable | None = None) -> None:
        self.dll_path = Path(dll_path) if dll_path else vendor_path(
            "nvda", "x64", "nvdaControllerClient.dll")
        self._loader = loader
        self._lib = None
        self._load_failed = False

    def _library(self):
        if self._lib is not None or self._load_failed:
            return self._lib
        if self._loader is None:
            if not IS_WINDOWS or struct.calcsize("P") != 8 or not self.dll_path.exists():
                self._load_failed = True
                return None
            loader = ctypes.windll.LoadLibrary
        else:
            loader = self._loader
        try:
            lib = loader(str(self.dll_path))
            for func in ("nvdaController_speakText", "nvdaController_brailleMessage"):
                getattr(lib, func).argtypes = [ctypes.c_wchar_p]
                getattr(lib, func).restype = ctypes.c_ulong
            for func in ("nvdaController_testIfRunning", "nvdaController_cancelSpeech"):
                getattr(lib, func).argtypes = []
                getattr(lib, func).restype = ctypes.c_ulong
        except (OSError, AttributeError):
            self._load_failed = True
            return None
        self._lib = lib
        return lib

    def available(self) -> bool:
        lib = self._library()
        if lib is None:
            return False
        try:
            return lib.nvdaController_testIfRunning() == 0
        except OSError:
            return False

    def speak(self, text: str, interrupt: bool = False) -> bool:
        lib = self._library()
        if lib is None:
            return False
        if interrupt:
            lib.nvdaController_cancelSpeech()
        ok = lib.nvdaController_speakText(text) == 0
        lib.nvdaController_brailleMessage(text)
        return ok

    def cancel(self) -> None:
        lib = self._library()
        if lib is not None:
            lib.nvdaController_cancelSpeech()


# ------------------------------------------------------------------ JAWS

class JawsBackend:
    name = "jaws"

    def __init__(self, factory: Callable | None = None,
                 is_running: Callable[[], bool] | None = None) -> None:
        self._factory = factory or self._create_com_object
        self._is_running = is_running or (lambda: "jaws" in running_readers())
        self._api = None

    @staticmethod
    def _create_com_object():
        import comtypes.client  # зарежда се само ако JAWS работи

        return comtypes.client.CreateObject("FreedomSci.JawsApi", dynamic=True)

    def _object(self):
        if self._api is None:
            try:
                self._api = self._factory()
            except Exception:  # COM грешките нямат общ базов клас
                self._api = None
        return self._api

    def available(self) -> bool:
        return bool(self._is_running()) and self._object() is not None

    def speak(self, text: str, interrupt: bool = False) -> bool:
        api = self._object()
        if api is None:
            return False
        try:
            result = api.SayString(text, bool(interrupt))
        except Exception:
            self._api = None  # JAWS е рестартиран — ще се създаде наново
            return False
        return result is None or bool(result)

    def cancel(self) -> None:
        api = self._object()
        if api is not None:
            try:
                api.StopSpeech()
            except Exception:
                pass


# ------------------------------------------------------------------- UIA

class UiaBackend:
    """``UiaRaiseNotificationEvent`` — Narrator, NVDA и JAWS го четат отпред."""

    name = "uia"
    NOTIFICATION_KIND_ACTION_COMPLETED = 2
    NOTIFICATION_PROCESSING_IMPORTANT_ALL = 0

    def __init__(self, hwnd_getter: Callable[[], int] | None = None) -> None:
        self._hwnd_getter = hwnd_getter or (lambda: 0)

    def available(self) -> bool:
        return IS_WINDOWS and bool(self._hwnd_getter())

    def speak(self, text: str, interrupt: bool = False) -> bool:
        hwnd = self._hwnd_getter()
        if not IS_WINDOWS or not hwnd:
            return False
        try:
            uia = ctypes.windll.UIAutomationCore
            oleaut = ctypes.windll.oleaut32
        except OSError:
            return False
        provider = ctypes.c_void_p()
        if uia.UiaHostProviderFromHwnd(wintypes.HWND(hwnd), ctypes.byref(provider)) != 0:
            return False
        oleaut.SysAllocString.restype = ctypes.c_void_p
        message = oleaut.SysAllocString(ctypes.c_wchar_p(text))
        activity = oleaut.SysAllocString(ctypes.c_wchar_p("kapilands"))
        try:
            result = uia.UiaRaiseNotificationEvent(
                provider,
                self.NOTIFICATION_KIND_ACTION_COMPLETED,
                self.NOTIFICATION_PROCESSING_IMPORTANT_ALL,
                ctypes.c_void_p(message),
                ctypes.c_void_p(activity),
            )
        finally:
            oleaut.SysFreeString(ctypes.c_void_p(message))
            oleaut.SysFreeString(ctypes.c_void_p(activity))
            _release_com(provider)
        return result == 0

    def cancel(self) -> None:
        pass


def _release_com(pointer: ctypes.c_void_p) -> None:
    if not pointer or not pointer.value:
        return
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[0][2])
    release(pointer)


# --------------------------------------------------------------- Speaker

class Speaker:
    """Говори през първия наличен начин. Връща името му или None."""

    def __init__(self, backends: Iterable | None = None, mode: str = MODE_AUTO,
                 is_locked: Callable[[], bool] = session_locked,
                 reader_active: Callable[[], bool] | None = None) -> None:
        self.backends = list(backends) if backends is not None else [
            NvdaBackend(), JawsBackend()]
        self.mode = mode
        self._is_locked = is_locked
        self._reader_active = reader_active or (
            lambda: screen_reader_flag() or bool(running_readers()))
        self.last_backend: str | None = None
        self.last_text: str = ""

    def add_backend(self, backend) -> None:
        self.backends.append(backend)

    def reader_active(self) -> bool:
        try:
            return bool(self._reader_active())
        except Exception:
            return False

    def speak(self, text: str, interrupt: bool = False) -> str | None:
        text = (text or "").strip()
        if not text or self.mode == MODE_NEVER:
            return None
        if self.mode == MODE_AUTO and not self.reader_active():
            return None
        try:
            if self._is_locked():
                return None
        except Exception:
            return None
        for backend in self.backends:
            try:
                if backend.available() and backend.speak(text, interrupt):
                    self.last_backend = backend.name
                    self.last_text = text
                    return backend.name
            except Exception:
                continue
        return None

    def cancel(self) -> None:
        for backend in self.backends:
            try:
                backend.cancel()
            except Exception:
                pass


class AnnouncementQueue:
    """Събира съобщения, дошли почти едновременно, в едно изречение."""

    def __init__(self, delay: float = 1.5) -> None:
        self.delay = delay
        self._items: list[str] = []
        self._first_at: float | None = None

    def add(self, text: str, now: float) -> None:
        text = (text or "").strip()
        if not text or text in self._items:
            return
        if not self._items:
            self._first_at = now
        self._items.append(text)

    def ready(self, now: float) -> bool:
        return bool(self._items) and self._first_at is not None and \
            now - self._first_at >= self.delay

    def pop(self) -> str:
        parts = [item.rstrip(". ") for item in self._items]
        self._items = []
        self._first_at = None
        return ". ".join(parts) + "." if parts else ""

    def __len__(self) -> int:
        return len(self._items)
