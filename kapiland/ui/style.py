"""Прилагане на цветова тема, мащаб на шрифта и видим фокус (WCAG 2.1 AA)."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .. import a11y


class AppStyle:
    """Пази текущата тема и мащаба и ги прилага върху всички ttk елементи."""

    def __init__(self, root: tk.Misc, theme_name: str = "light",
                 font_scale: int = 100) -> None:
        self.root = root
        self.theme_name = theme_name
        self.font_scale = font_scale
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")  # единствената вградена тема, която
        except tk.TclError:               # позволява собствени цветове навсякъде
            pass
        self.base_font = tkfont.Font(family="Segoe UI", size=10)
        self.bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.mono_font = tkfont.Font(family="Consolas", size=10)
        self.heading_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.apply()

    # ------------------------------------------------------------------

    @property
    def colors(self) -> dict:
        return a11y.theme(self.theme_name)

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        self.apply()

    def set_scale(self, percent: int) -> None:
        self.font_scale = max(100, min(200, int(percent)))
        self.apply()

    def bump_scale(self, step: int) -> int:
        scales = list(a11y.FONT_SCALES)
        try:
            index = scales.index(self.font_scale)
        except ValueError:
            index = 0
        index = max(0, min(len(scales) - 1, index + step))
        self.set_scale(scales[index])
        return self.font_scale

    def row_height(self) -> int:
        return a11y.scaled_row_height(self.font_scale)

    def row_tags(self) -> dict:
        return self.colors["rows"]

    # ------------------------------------------------------------------

    def apply(self) -> None:
        c = self.colors
        size = a11y.scaled_font_size(self.font_scale)
        self.base_font.configure(size=size)
        self.bold_font.configure(size=size, weight="bold")
        self.mono_font.configure(size=size)
        self.heading_font.configure(size=size + 3, weight="bold")

        # Минимална височина на бутоните: 24px при 100% (WCAG 2.5.8).
        pad_y = max(4, int(round(6 * self.font_scale / 100)))
        pad_x = max(8, int(round(12 * self.font_scale / 100)))

        st = self.style
        self.root.configure(background=c["bg"])
        st.configure(".", background=c["bg"], foreground=c["fg"],
                     fieldbackground=c["bg"], font=self.base_font,
                     bordercolor=c["border"], darkcolor=c["surface"],
                     lightcolor=c["surface"], troughcolor=c["surface"],
                     focuscolor=c["focus"])
        st.configure("TFrame", background=c["bg"])
        st.configure("Surface.TFrame", background=c["surface"])
        st.configure("TLabel", background=c["bg"], foreground=c["fg"])
        st.configure("Surface.TLabel", background=c["surface"], foreground=c["fg"])
        st.configure("Muted.TLabel", background=c["bg"], foreground=c["fg_muted"])
        st.configure("Heading.TLabel", background=c["bg"], foreground=c["fg"],
                     font=self.heading_font)
        st.configure("Status.TLabel", background=c["surface"], foreground=c["fg"],
                     font=self.bold_font, padding=(8, 6))

        st.configure("TButton", padding=(pad_x, pad_y), foreground=c["fg"],
                     background=c["surface"], bordercolor=c["border"],
                     focusthickness=2, focuscolor=c["focus"])
        st.map("TButton",
               background=[("active", c["selection_bg"]), ("disabled", c["surface"])],
               foreground=[("active", c["selection_fg"]), ("disabled", c["fg_muted"])])
        st.configure("Accent.TButton", background=c["accent"],
                     foreground=c["accent_fg"], font=self.bold_font)
        st.map("Accent.TButton",
               background=[("active", c["fg"]), ("disabled", c["surface"])],
               foreground=[("active", c["bg"]), ("disabled", c["fg_muted"])])

        st.configure("TEntry", fieldbackground=c["bg"], foreground=c["fg"],
                     bordercolor=c["border"], insertcolor=c["fg"], padding=4)
        st.map("TEntry", bordercolor=[("focus", c["focus"])],
               lightcolor=[("focus", c["focus"])])
        st.configure("TCombobox", fieldbackground=c["bg"], foreground=c["fg"],
                     background=c["surface"], bordercolor=c["border"], padding=4,
                     arrowcolor=c["fg"])
        st.map("TCombobox", bordercolor=[("focus", c["focus"])],
               fieldbackground=[("readonly", c["bg"])],
               foreground=[("readonly", c["fg"])])
        st.configure("TCheckbutton", background=c["bg"], foreground=c["fg"],
                     focuscolor=c["focus"], indicatorcolor=c["bg"],
                     bordercolor=c["border"], padding=4)
        st.map("TCheckbutton", indicatorcolor=[("selected", c["accent"])],
               background=[("active", c["bg"])])
        st.configure("TRadiobutton", background=c["bg"], foreground=c["fg"],
                     focuscolor=c["focus"], indicatorcolor=c["bg"],
                     bordercolor=c["border"], padding=4)
        st.map("TRadiobutton", indicatorcolor=[("selected", c["accent"])],
               background=[("active", c["bg"])])
        st.configure("TLabelframe", background=c["bg"], foreground=c["fg"],
                     bordercolor=c["border"])
        st.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"],
                     font=self.bold_font)
        st.configure("TSpinbox", fieldbackground=c["bg"], foreground=c["fg"],
                     bordercolor=c["border"], arrowcolor=c["fg"], padding=4)
        st.configure("TSeparator", background=c["border"])
        st.configure("TScrollbar", background=c["surface"], troughcolor=c["bg"],
                     bordercolor=c["border"], arrowcolor=c["fg"])

        st.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
        st.configure("TNotebook.Tab", background=c["surface"], foreground=c["fg"],
                     padding=(pad_x, pad_y), focuscolor=c["focus"])
        st.map("TNotebook.Tab",
               background=[("selected", c["accent"])],
               foreground=[("selected", c["accent_fg"])],
               font=[("selected", self.bold_font)])

        st.configure("Treeview", background=c["bg"], fieldbackground=c["bg"],
                     foreground=c["fg"], bordercolor=c["border"],
                     rowheight=self.row_height(), font=self.base_font)
        st.map("Treeview",
               background=[("selected", c["selection_bg"])],
               foreground=[("selected", c["selection_fg"])])
        st.configure("Treeview.Heading", background=c["surface"], foreground=c["fg"],
                     font=self.bold_font, padding=(6, pad_y), relief="flat")
        st.map("Treeview.Heading", background=[("active", c["surface"])])

        st.configure("TProgressbar", background=c["accent"], troughcolor=c["surface"],
                     bordercolor=c["border"], lightcolor=c["accent"],
                     darkcolor=c["accent"])

    # ------------------------------------------------------------------

    def tag_tree(self, tree: ttk.Treeview) -> None:
        """Задава цветовете на редовете по състояние."""
        for state, colors in self.row_tags().items():
            tree.tag_configure(state, background=colors["bg"],
                               foreground=colors["fg"])
        tree.tag_configure("bold", font=self.bold_font)
