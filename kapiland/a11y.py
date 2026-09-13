"""Достъпност (WCAG 2.1 ниво AA).

Тук са цветовите палитри, изчисляването на контраст и текстовите
означения на статусите. Правилата, които този модул налага:

* 1.4.3 Контраст — обикновен текст ≥ 4.5:1, едър текст и елементи на
  интерфейса ≥ 3:1 (проверява се с тестовете в ``tests/test_a11y.py``).
* 1.4.1 Използване на цвят — всеки статус носи и текст, и знак, не само цвят.
* 1.4.4 Преоразмеряване на текста — мащаб от 100% до 200%.
* 2.4.7 Видим фокус — отделен, контрастен цвят за фокусирания елемент.
* 2.3.1 Мигане — статусите не мигат; използва се статичен контраст.
"""

from __future__ import annotations

# --- Изчисляване на контраст (WCAG 2.1, дефиниция за relative luminance) ---


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Невалиден цвят: {color!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(color: str) -> float:
    channels = []
    for raw in hex_to_rgb(color):
        c = raw / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """Съотношение на контраста между два цвята (1.0 – 21.0)."""
    l1 = relative_luminance(foreground)
    l2 = relative_luminance(background)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


AA_TEXT = 4.5        # обикновен текст
AA_LARGE = 3.0       # едър текст (≥ 18.66px получер или ≥ 24px)
AA_NON_TEXT = 3.0    # елементи на интерфейса и графика
AAA_TEXT = 7.0


def meets_aa(foreground: str, background: str, large: bool = False) -> bool:
    return contrast_ratio(foreground, background) >= (AA_LARGE if large else AA_TEXT)


# --- Палитри ---------------------------------------------------------------

THEMES: dict[str, dict] = {
    "light": {
        "label": "Светла",
        "bg": "#FFFFFF",
        "surface": "#F1F3F5",
        "border": "#6C757D",
        "fg": "#16191C",
        "fg_muted": "#565E66",
        "accent": "#0B5FA5",
        "accent_fg": "#FFFFFF",
        "focus": "#0B5FA5",
        "selection_bg": "#0B5FA5",
        "selection_fg": "#FFFFFF",
        "rows": {
            "running":  {"bg": "#E3F1E0", "fg": "#14401A"},
            "soon":     {"bg": "#FFF1CC", "fg": "#5A3D00"},
            "due":      {"bg": "#FBE0DE", "fg": "#7A1710"},
            "missed":   {"bg": "#E6DFF5", "fg": "#3A2570"},
            "paused":   {"bg": "#E9ECEF", "fg": "#343A40"},
        },
    },
    "dark": {
        "label": "Тъмна",
        "bg": "#14171A",
        "surface": "#1E2226",
        "border": "#8A939C",
        "fg": "#F2F4F6",
        "fg_muted": "#B8C0C8",
        "accent": "#79B8FF",
        "accent_fg": "#14171A",
        "focus": "#FFC857",
        "selection_bg": "#2F5C8A",
        "selection_fg": "#FFFFFF",
        "rows": {
            "running":  {"bg": "#1C3320", "fg": "#B7E4BC"},
            "soon":     {"bg": "#3A2F12", "fg": "#FFD97A"},
            "due":      {"bg": "#41201D", "fg": "#FFB3AC"},
            "missed":   {"bg": "#2B2450", "fg": "#CFC2FF"},
            "paused":   {"bg": "#26292D", "fg": "#C9CFD5"},
        },
    },
    "contrast": {
        "label": "Висок контраст",
        "bg": "#000000",
        "surface": "#000000",
        "border": "#FFFFFF",
        "fg": "#FFFFFF",
        "fg_muted": "#E8E8E8",
        "accent": "#FFFF00",
        "accent_fg": "#000000",
        "focus": "#FFFF00",
        "selection_bg": "#FFFF00",
        "selection_fg": "#000000",
        "rows": {
            "running":  {"bg": "#000000", "fg": "#6EFF6E"},
            "soon":     {"bg": "#000000", "fg": "#FFFF00"},
            "due":      {"bg": "#000000", "fg": "#FF8A80"},
            "missed":   {"bg": "#000000", "fg": "#D0A8FF"},
            "paused":   {"bg": "#000000", "fg": "#FFFFFF"},
        },
    },
}

DEFAULT_THEME = "light"


def theme(name: str | None = None) -> dict:
    return THEMES.get(name or DEFAULT_THEME, THEMES[DEFAULT_THEME])


# --- Статуси: текст + знак, никога само цвят (WCAG 1.4.1) ------------------

STATE_LABELS: dict[str, tuple[str, str]] = {
    # ключ: (знак, текст)
    "running": ("▶", "върви"),
    "soon":    ("!", "скоро"),
    "due":     ("✔", "ГОТОВО"),
    "missed":  ("!!", "пропуснато"),
    "paused":  ("||", "спряно"),
}


def state_text(state: str) -> str:
    """Текстово означение за екранни четци и за колоната „Статус“."""
    sign, word = STATE_LABELS.get(state, ("", state))
    return f"{sign} {word}".strip()


# --- Мащабиране на текста (WCAG 1.4.4) -------------------------------------

FONT_SCALES = (100, 125, 150, 175, 200)
BASE_FONT_SIZE = 10
MIN_TARGET_PX = 24  # минимален размер на бутон (WCAG 2.5.8)


def scaled_font_size(scale_percent: int, base: int = BASE_FONT_SIZE) -> int:
    """Размер на шрифта за даден мащаб; никога под 8pt."""
    return max(8, int(round(base * scale_percent / 100.0)))


def scaled_row_height(scale_percent: int, base: int = 24) -> int:
    return max(MIN_TARGET_PX, int(round(base * scale_percent / 100.0)))


# --- Клавишни комбинации (WCAG 2.1.1 — всичко достъпно с клавиатура) -------

KEYBOARD_HELP: tuple[tuple[str, str], ...] = (
    ("Ctrl+N", "Нов таймер"),
    ("Enter", "Редактиране на избрания таймер"),
    ("Ctrl+D", "Отбелязване като готово"),
    ("Ctrl+Shift+D", "Потвърждаване на всички готови"),
    ("Ctrl+R", "Пускане на нов цикъл"),
    ("Delete", "Изтриване на избрания таймер"),
    ("F3", "Изговаряне на подробностите за избрания"),
    ("F4", "Изговаряне на готовото и следващото"),
    ("Ctrl+I", "Внос на списък"),
    ("Ctrl+F", "Към филтъра по свят"),
    ("Ctrl+1 до Ctrl+5", "Раздели: Таймери, Компании, Каталог, История, Настройки"),
    ("Ctrl+Tab", "Следващ раздел"),
    ("Стрелки, Home, End", "Движение в списъка"),
    ("F5", "Обновяване и подреждане по час"),
    ("F6", "Между списъка, подробностите и бутоните"),
    ("F1", "Помощ за клавиатурата"),
    ("Ctrl+плюс, Ctrl+минус", "По-голям и по-малък текст"),
    ("Ctrl+Alt+K от всеки прозорец", "Изговаряне на готовото, без да напускаш играта"),
    ("Ctrl+Alt+J от всеки прозорец", "Показване на приложението"),
    ("Esc", "Затваряне на диалог без запис"),
)
