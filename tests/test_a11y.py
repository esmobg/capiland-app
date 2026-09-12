"""Тестове за достъпността — доказват контраста по WCAG 2.1 AA."""

import unittest

from kapiland import a11y
from kapiland.models import (
    STATE_DUE,
    STATE_MISSED,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_SOON,
)


class ContrastMathTest(unittest.TestCase):
    """Проверка на самата формула спрямо известни стойности."""

    def test_black_on_white_is_maximum(self):
        self.assertAlmostEqual(a11y.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)

    def test_same_color_is_one(self):
        self.assertAlmostEqual(a11y.contrast_ratio("#4A7B2C", "#4A7B2C"), 1.0, places=6)

    def test_order_does_not_matter(self):
        self.assertAlmostEqual(a11y.contrast_ratio("#123456", "#EEEEEE"),
                               a11y.contrast_ratio("#EEEEEE", "#123456"))

    def test_short_hex(self):
        self.assertAlmostEqual(a11y.contrast_ratio("#000", "#FFF"), 21.0, places=2)

    def test_invalid_color(self):
        for bad in ("", "#12", "#GGGGGG", "синьо"):
            with self.assertRaises(ValueError):
                a11y.hex_to_rgb(bad)


class ThemeContrastTest(unittest.TestCase):
    """Всяка тема трябва да покрива AA във всяка комбинация, която се рисува."""

    def assert_ratio(self, fg, bg, minimum, label):
        ratio = a11y.contrast_ratio(fg, bg)
        self.assertGreaterEqual(
            ratio, minimum,
            f"{label}: {fg} върху {bg} дава {ratio:.2f}:1, а трябва "
            f"поне {minimum}:1")

    def test_text_meets_aa(self):
        for name, theme in a11y.THEMES.items():
            self.assert_ratio(theme["fg"], theme["bg"], a11y.AA_TEXT,
                              f"{name}: основен текст")
            self.assert_ratio(theme["fg"], theme["surface"], a11y.AA_TEXT,
                              f"{name}: текст върху панел")
            self.assert_ratio(theme["fg_muted"], theme["bg"], a11y.AA_TEXT,
                              f"{name}: второстепенен текст")
            self.assert_ratio(theme["fg_muted"], theme["surface"], a11y.AA_TEXT,
                              f"{name}: второстепенен текст върху панел")
            self.assert_ratio(theme["selection_fg"], theme["selection_bg"],
                              a11y.AA_TEXT, f"{name}: избран ред")
            self.assert_ratio(theme["accent_fg"], theme["accent"], a11y.AA_TEXT,
                              f"{name}: текст върху главния бутон")

    def test_interface_elements_meet_aa(self):
        for name, theme in a11y.THEMES.items():
            self.assert_ratio(theme["border"], theme["bg"], a11y.AA_NON_TEXT,
                              f"{name}: рамки")
            self.assert_ratio(theme["border"], theme["surface"], a11y.AA_NON_TEXT,
                              f"{name}: рамки върху панел")
            self.assert_ratio(theme["focus"], theme["bg"], a11y.AA_NON_TEXT,
                              f"{name}: показалец на фокуса")
            self.assert_ratio(theme["focus"], theme["surface"], a11y.AA_NON_TEXT,
                              f"{name}: показалец на фокуса върху панел")
            self.assert_ratio(theme["accent"], theme["bg"], a11y.AA_NON_TEXT,
                              f"{name}: главен бутон")

    def test_status_rows_meet_aa(self):
        for name, theme in a11y.THEMES.items():
            for state, colors in theme["rows"].items():
                self.assert_ratio(colors["fg"], colors["bg"], a11y.AA_TEXT,
                                  f"{name}: ред „{state}“")

    def test_high_contrast_theme_reaches_aaa(self):
        theme = a11y.THEMES["contrast"]
        self.assert_ratio(theme["fg"], theme["bg"], a11y.AAA_TEXT,
                          "висок контраст: основен текст")
        for state, colors in theme["rows"].items():
            self.assert_ratio(colors["fg"], colors["bg"], a11y.AAA_TEXT,
                              f"висок контраст: ред „{state}“")

    def test_every_theme_defines_every_state(self):
        expected = {STATE_RUNNING, STATE_SOON, STATE_DUE, STATE_MISSED, STATE_PAUSED}
        for name, theme in a11y.THEMES.items():
            self.assertEqual(set(theme["rows"]), expected, f"тема {name}")


class NonColorSignalsTest(unittest.TestCase):
    """WCAG 1.4.1 — цветът никога не е единственият носител на информация."""

    def test_every_state_has_text_and_sign(self):
        for state in (STATE_RUNNING, STATE_SOON, STATE_DUE, STATE_MISSED,
                      STATE_PAUSED):
            sign, word = a11y.STATE_LABELS[state]
            self.assertTrue(sign.strip(), f"{state} няма знак")
            self.assertTrue(word.strip(), f"{state} няма текст")
            self.assertIn(word, a11y.state_text(state))

    def test_state_texts_are_distinct(self):
        texts = [a11y.state_text(s) for s in a11y.STATE_LABELS]
        self.assertEqual(len(texts), len(set(texts)))


class ResizeTest(unittest.TestCase):
    """WCAG 1.4.4 — текстът се уголемява до 200% без загуба на съдържание."""

    def test_scale_range(self):
        self.assertEqual(a11y.FONT_SCALES[0], 100)
        self.assertEqual(a11y.FONT_SCALES[-1], 200)

    def test_font_grows_with_scale(self):
        sizes = [a11y.scaled_font_size(s) for s in a11y.FONT_SCALES]
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(a11y.scaled_font_size(200),
                         2 * a11y.scaled_font_size(100))

    def test_font_never_gets_unreadably_small(self):
        self.assertGreaterEqual(a11y.scaled_font_size(10), 8)

    def test_rows_keep_the_minimum_target_size(self):
        """WCAG 2.5.8 — целите за щракане са поне 24 пиксела."""
        for scale in a11y.FONT_SCALES:
            self.assertGreaterEqual(a11y.scaled_row_height(scale),
                                    a11y.MIN_TARGET_PX)


class KeyboardTest(unittest.TestCase):
    """WCAG 2.1.1 — всяко действие трябва да има клавишен път."""

    def test_help_covers_the_main_actions(self):
        described = " ".join(d for _k, d in a11y.KEYBOARD_HELP).lower()
        for action in ("нов таймер", "готово", "цикъл", "изтриване", "раздел"):
            self.assertIn(action, described)

    def test_shortcuts_are_unique(self):
        keys = [k for k, _d in a11y.KEYBOARD_HELP]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
