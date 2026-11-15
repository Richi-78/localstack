"""
LocalStack theme - palette, fonts and ttk styling.

The whole UI is built on top of ``clam``, which is the only stock ttk theme
that lets us repaint every element (backgrounds, borders, indicators).  All
sizes are derived from the font metrics, so the layout still holds together on
HiDPI screens.
"""

import json
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------

LIGHT = {
    "name": "light",
    "bg": "#f4f5f7",
    "surface": "#ffffff",
    "surface_alt": "#f0f2f5",
    "surface_hover": "#e9ecf1",
    "border": "#e2e5ea",
    "text": "#17202b",
    "muted": "#6c7787",
    "accent": "#2f6bed",
    "accent_hover": "#1e56cc",
    "accent_text": "#ffffff",
    "accent_soft": "#e9f0ff",
    "accent_on_soft": "#1e56cc",
    "success": "#17803d",
    "success_soft": "#e7f6ed",
    "success_text": "#116631",
    "warning": "#b05e0b",
    "warning_soft": "#fdf1e0",
    "warning_text": "#8c4a08",
    "danger": "#bb2d2d",
    "danger_soft": "#fdecec",
    "danger_text": "#9d2020",
    "field": "#ffffff",
    "sidebar": "#0e1420",
    "sidebar_hover": "#1a2233",
    "sidebar_active": "#202a3d",
    "sidebar_text": "#eef2f8",
    "sidebar_muted": "#8a94a6",
    "toast_bg": "#1c2431",
    "toast_fg": "#f7f9fc",
    "mono_bg": "#f7f8fa",
}

DARK = {
    "name": "dark",
    "bg": "#0d1017",
    "surface": "#141922",
    "surface_alt": "#1a202b",
    "surface_hover": "#202836",
    "border": "#242c39",
    "text": "#e7ebf2",
    "muted": "#8b96a8",
    "accent": "#3f78f5",
    "accent_hover": "#5b8cff",
    "accent_text": "#ffffff",
    "accent_soft": "#1d2f52",
    "accent_on_soft": "#8ab4ff",
    "success": "#3ecf8e",
    "success_soft": "#12271e",
    "success_text": "#6ee7b7",
    "warning": "#f0b429",
    "warning_soft": "#2a2213",
    "warning_text": "#fcd34d",
    "danger": "#f87171",
    "danger_soft": "#2b1618",
    "danger_text": "#fca5a5",
    "field": "#10151d",
    "sidebar": "#0a0d13",
    "sidebar_hover": "#151b26",
    "sidebar_active": "#1c2432",
    "sidebar_text": "#e7ebf2",
    "sidebar_muted": "#7f8a9c",
    "toast_bg": "#e7ebf2",
    "toast_fg": "#10151d",
    "mono_bg": "#0f141c",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# Preferred UI fonts, in descending order.  Missing families fall through to
# the first one Tk actually knows about.
UI_FONTS = (
    "Inter", "Cantarell", "Adwaita Sans", "Ubuntu", "Noto Sans",
    "Segoe UI", "Liberation Sans", "DejaVu Sans",
)
MONO_FONTS = (
    "JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro",
    "Ubuntu Mono", "Liberation Mono", "DejaVu Sans Mono",
)


def _settings_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "localstack", "settings.json")


def load_preference() -> str:
    """Return the stored theme name, defaulting to light."""
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            mode = json.load(f).get("theme", "light")
    except (OSError, ValueError):
        return "light"
    return mode if mode in PALETTES else "light"


def save_preference(mode: str) -> None:
    """Persist the theme choice, ignoring failures (read-only home etc.)."""
    path = _settings_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data["theme"] = mode
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (OSError, ValueError):
        pass


class ThemeManager:
    """Builds the ttk styles for the current palette and tracks tk widgets."""

    def __init__(self, root: tk.Tk, mode: str = "light"):
        self.root = root
        self.mode = mode if mode in PALETTES else "light"
        self._observers = []
        self._text_widgets = []
        self._canvas_painters = []
        self._build_fonts()
        self.apply()

    # -- palette ----------------------------------------------------------

    @property
    def p(self) -> dict:
        return PALETTES[self.mode]

    def toggle(self) -> str:
        self.set_mode("dark" if self.mode == "light" else "light")
        return self.mode

    def set_mode(self, mode: str) -> None:
        if mode not in PALETTES or mode == self.mode:
            return
        self.mode = mode
        self.apply()
        save_preference(mode)

    # -- fonts ------------------------------------------------------------

    def _build_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        ui = next((f for f in UI_FONTS if f in families), "TkDefaultFont")
        mono = next((f for f in MONO_FONTS if f in families), "TkFixedFont")

        self._fonts = {}

        def named(name, family, size, weight="normal"):
            try:
                return tkfont.nametofont(name, root=self.root)
            except tk.TclError:
                font = tkfont.Font(
                    self.root, name=name, family=family,
                    size=size, weight=weight,
                )
                self._fonts[name] = font
                return font

        named("LSBody", ui, 10)
        named("LSBold", ui, 10, "bold")
        named("LSSmall", ui, 9)
        named("LSBoldSmall", ui, 9, "bold")
        named("LSDisplay", ui, 18, "bold")
        named("LSH2", ui, 12, "bold")
        named("LSValue", ui, 20, "bold")
        named("LSMono", mono, 10)

    def row_height(self) -> int:
        return tkfont.nametofont("LSBody").metrics("linespace") + 14

    # -- observers --------------------------------------------------------

    def on_change(self, callback) -> None:
        self._observers.append(callback)

    def register_text(self, widget: tk.Text) -> None:
        self._text_widgets.append(widget)
        self._paint_text(widget)

    def register_canvas(self, canvas: tk.Canvas, painter) -> None:
        self._canvas_painters.append((canvas, painter))
        self._paint_canvas(canvas, painter)

    def _paint_text(self, widget: tk.Text) -> None:
        p = self.p
        try:
            widget.configure(
                background=p["mono_bg"], foreground=p["text"],
                insertbackground=p["text"], selectbackground=p["accent_soft"],
                selectforeground=p["text"], highlightbackground=p["border"],
                highlightcolor=p["accent"],
            )
        except tk.TclError:
            pass

    def _paint_canvas(self, canvas: tk.Canvas, painter) -> None:
        try:
            painter(canvas, self.p)
        except tk.TclError:
            pass

    # -- styling ----------------------------------------------------------

    def apply(self) -> None:
        p = self.p
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(background=p["bg"])
        self.root.option_add("*tearOff", False)

        # Defaults for every ttk widget.  Individual styles override these.
        style.configure(
            ".",
            background=p["bg"], foreground=p["text"], font="LSBody",
            borderwidth=0, focuscolor=p["accent"],
            troughcolor=p["surface_alt"],
            selectbackground=p["accent_soft"], selectforeground=p["text"],
            insertcolor=p["text"],
        )
        style.map(".", background=[("active", p["surface"])])

        # Frames -----------------------------------------------------------
        style.configure("App.TFrame", background=p["bg"])
        style.configure("Card.TFrame", background=p["surface"],
                        bordercolor=p["border"], relief="solid", borderwidth=1)
        style.configure("Surface.TFrame", background=p["surface"])
        style.configure("Sidebar.TFrame", background=p["sidebar"])
        style.configure("Toast.TFrame", background=p["toast_bg"])

        # Labels -----------------------------------------------------------
        style.configure("H1.TLabel", background=p["bg"], foreground=p["text"],
                        font="LSDisplay")
        style.configure("Subtitle.TLabel", background=p["bg"],
                        foreground=p["muted"], font="LSSmall")
        style.configure("H2.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSH2")
        style.configure("H3.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSBold")
        style.configure("Body.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSBody")
        style.configure("Muted.TLabel", background=p["surface"],
                        foreground=p["muted"], font="LSSmall")
        style.configure("MutedApp.TLabel", background=p["bg"],
                        foreground=p["muted"], font="LSSmall")
        style.configure("Hint.TLabel", background=p["surface"],
                        foreground=p["muted"], font="LSSmall")
        style.configure("AccentHint.TLabel", background=p["surface"],
                        foreground=p["accent"], font="LSSmall")
        style.configure("StatLabel.TLabel", background=p["surface"],
                        foreground=p["muted"], font="LSBoldSmall")
        style.configure("StatValue.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSValue")
        style.configure("StatGood.TLabel", background=p["surface"],
                        foreground=p["success"], font="LSValue")
        style.configure("StatWarn.TLabel", background=p["surface"],
                        foreground=p["warning"], font="LSValue")
        style.configure("StatBad.TLabel", background=p["surface"],
                        foreground=p["danger"], font="LSValue")
        style.configure("OkText.TLabel", background=p["surface"],
                        foreground=p["success"], font="LSBody")
        style.configure("WarnText.TLabel", background=p["surface"],
                        foreground=p["warning"], font="LSBody")
        style.configure("ErrorText.TLabel", background=p["surface"],
                        foreground=p["danger"], font="LSBody")
        style.configure("Step.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSSmall")
        style.configure("StepNum.TLabel", background=p["accent_soft"],
                        foreground=p["accent_on_soft"], font="LSBoldSmall",
                        padding=(6, 2))
        style.configure("StatusBar.TLabel", background=p["surface"],
                        foreground=p["muted"], font="LSSmall")
        style.configure("StatusBarStrong.TLabel", background=p["surface"],
                        foreground=p["text"], font="LSSmall")
        style.configure("Toast.TLabel", background=p["toast_bg"],
                        foreground=p["toast_fg"], font="LSBold")
        style.configure("OkBadge.TLabel", background=p["success_soft"],
                        foreground=p["success_text"], font="LSBoldSmall",
                        padding=(9, 3))
        style.configure("WarnBadge.TLabel", background=p["warning_soft"],
                        foreground=p["warning_text"], font="LSBoldSmall",
                        padding=(9, 3))
        style.configure("BadBadge.TLabel", background=p["danger_soft"],
                        foreground=p["danger_text"], font="LSBoldSmall",
                        padding=(9, 3))
        style.configure("NeutralBadge.TLabel", background=p["surface_alt"],
                        foreground=p["muted"], font="LSBoldSmall",
                        padding=(9, 3))
        style.configure("Check.TLabel", background=p["surface"],
                        foreground=p["success"], font="LSBody")
        style.configure("Rule.TFrame", background=p["border"])
        style.configure("SidebarRule.TFrame", background=p["sidebar_hover"])

        # URL preview strip at the bottom of the new-project form
        style.configure("Preview.TFrame", background=p["surface_alt"])
        style.configure("PreviewLabel.TLabel", background=p["surface_alt"],
                        foreground=p["muted"], font="LSBoldSmall")
        style.configure("PreviewValue.TLabel", background=p["surface_alt"],
                        foreground=p["accent_on_soft"], font="LSMono")

        # Sidebar ----------------------------------------------------------
        style.configure("Brand.TLabel", background=p["sidebar"],
                        foreground=p["sidebar_text"], font="LSH2")
        style.configure("BrandSub.TLabel", background=p["sidebar"],
                        foreground=p["sidebar_muted"], font="LSSmall")
        style.configure("NavSection.TLabel", background=p["sidebar"],
                        foreground=p["sidebar_muted"], font="LSBoldSmall")
        self._button_style(
            style, "Nav.TButton", p["sidebar"], p["sidebar_muted"],
            p["sidebar_hover"], p["sidebar_text"], border=p["sidebar"],
            padding=(12, 9), bold=False, anchor="w",
        )
        self._button_style(
            style, "NavActive.TButton", p["sidebar_active"], p["sidebar_text"],
            p["sidebar_active"], p["sidebar_text"], border=p["sidebar_active"],
            padding=(12, 9), bold=True, anchor="w",
        )

        # Buttons ----------------------------------------------------------
        self._button_style(
            style, "Accent.TButton", p["accent"], p["accent_text"],
            p["accent_hover"], p["accent_text"], border=p["accent"],
            padding=(16, 9), bold=True,
        )
        self._button_style(
            style, "Success.TButton", p["success"], "#ffffff",
            p["success"], "#ffffff", border=p["success"],
            padding=(12, 8), bold=True,
        )
        self._button_style(
            style, "Secondary.TButton", p["surface_alt"], p["text"],
            p["surface_hover"], p["text"], border=p["surface_alt"],
            padding=(14, 8), bold=False,
        )
        self._button_style(
            style, "Ghost.TButton", p["surface"], p["muted"],
            p["surface_hover"], p["text"], border=p["surface"],
            padding=(12, 8), bold=False,
        )
        self._button_style(
            style, "GhostApp.TButton", p["bg"], p["muted"],
            p["surface_hover"], p["text"], border=p["bg"],
            padding=(10, 8), bold=False,
        )
        self._button_style(
            style, "Danger.TButton", p["danger_soft"], p["danger_text"],
            p["danger"], "#ffffff", border=p["danger_soft"],
            padding=(14, 8), bold=True,
        )
        style.configure("Link.TButton", background=p["sidebar"],
                        foreground=p["sidebar_muted"], font="LSSmall",
                        borderwidth=0, padding=(8, 6), relief="flat",
                        anchor="e", width=0)
        style.map("Link.TButton", foreground=[("active", p["sidebar_text"])])

        # Entries ----------------------------------------------------------
        style.configure(
            "TEntry",
            fieldbackground=p["field"], background=p["field"],
            foreground=p["text"], bordercolor=p["border"],
            lightcolor=p["field"], darkcolor=p["field"],
            insertcolor=p["text"], padding=(10, 7), relief="flat",
            borderwidth=1, selectbackground=p["accent_soft"],
            selectforeground=p["text"],
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", p["accent"])],
            lightcolor=[("focus", p["accent"])],
            darkcolor=[("focus", p["accent"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=p["field"], background=p["field"],
            foreground=p["text"], bordercolor=p["border"],
            lightcolor=p["field"], darkcolor=p["field"],
            arrowcolor=p["muted"], padding=(8, 6), borderwidth=1,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p["field"])],
            bordercolor=[("focus", p["accent"])],
        )

        # Radio / check buttons -------------------------------------------
        for widget in ("TRadiobutton", "TCheckbutton"):
            style.configure(
                widget,
                background=p["surface"], foreground=p["text"],
                font="LSBody", focusthickness=0,
                indicatorbackground=p["field"],
                indicatorforeground=p["accent"],
                upperbordercolor=p["border"],
                lowerbordercolor=p["border"],
                indicatorsize=12,
            )
            style.map(
                widget,
                background=[("active", p["surface"])],
                foreground=[("active", p["text"])],
                indicatorbackground=[("selected", p["accent"]),
                                     ("active", p["field"])],
                indicatorforeground=[("selected", p["accent_text"])],
                upperbordercolor=[("selected", p["accent"])],
                lowerbordercolor=[("selected", p["accent"])],
            )

        # Segmented control (database choice): a radio button drawn as a
        # button, so no stock indicator can clash with the palette.
        try:
            style.layout("Segment.TRadiobutton", style.layout("Toolbutton"))
        except tk.TclError:
            pass
        style.configure(
            "Segment.TRadiobutton",
            background=p["surface_alt"], foreground=p["muted"], font="LSBody",
            padding=(16, 8), relief="flat", borderwidth=1,
            bordercolor=p["surface_alt"], lightcolor=p["surface_alt"],
            darkcolor=p["surface_alt"], anchor="center", width=0,
        )
        style.map(
            "Segment.TRadiobutton",
            background=[("selected", p["accent_soft"]),
                        ("active", p["surface_hover"])],
            foreground=[("selected", p["accent_on_soft"]),
                        ("active", p["text"])],
            bordercolor=[("selected", p["accent"])],
            lightcolor=[("selected", p["accent"])],
            darkcolor=[("selected", p["accent"])],
        )

        # Treeview ---------------------------------------------------------
        style.configure(
            "Treeview",
            background=p["surface"], fieldbackground=p["surface"],
            foreground=p["text"], bordercolor=p["surface"],
            lightcolor=p["surface"], darkcolor=p["surface"],
            rowheight=self.row_height(), font="LSBody", borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", p["accent_soft"])],
            foreground=[("selected", p["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=p["surface_alt"], foreground=p["muted"],
            font="LSBoldSmall", relief="flat", borderwidth=0,
            bordercolor=p["surface_alt"], lightcolor=p["surface_alt"],
            darkcolor=p["surface_alt"], padding=(10, 8),
        )
        style.map("Treeview.Heading", background=[("active", p["surface_hover"])])

        # Scrollbars / separators -----------------------------------------
        style.configure(
            "Vertical.TScrollbar",
            background=p["border"], troughcolor=p["surface"],
            bordercolor=p["surface"], arrowcolor=p["muted"],
            lightcolor=p["border"], darkcolor=p["border"],
            gripcount=0, arrowsize=12, width=10,
        )
        style.map("Vertical.TScrollbar",
                  background=[("active", p["muted"])])
        style.configure(
            "Horizontal.TScrollbar",
            background=p["border"], troughcolor=p["surface"],
            bordercolor=p["surface"], arrowcolor=p["muted"],
            lightcolor=p["border"], darkcolor=p["border"],
            gripcount=0, arrowsize=12,
        )
        style.configure("TSeparator", background=p["border"])

        # Repaint the plain-tk widgets we created ourselves.
        for widget in list(self._text_widgets):
            self._paint_text(widget)
        for canvas, painter in list(self._canvas_painters):
            self._paint_canvas(canvas, painter)
        for callback in list(self._observers):
            try:
                callback(self.p)
            except tk.TclError:
                pass

    def _button_style(self, style, name, bg, fg, hover_bg, hover_fg, border,
                      padding=(14, 8), bold=True, anchor="center"):
        font = "LSBold" if bold else "LSBody"
        disabled_bg = self.p["surface_alt"]
        disabled_fg = self.p["muted"]
        style.configure(
            name,
            background=bg, foreground=fg, font=font,
            bordercolor=border, lightcolor=border, darkcolor=border,
            focuscolor=bg, relief="flat", borderwidth=1,
            padding=padding, anchor=anchor, width=0,
        )
        style.map(
            name,
            background=[("disabled", disabled_bg), ("pressed", hover_bg),
                        ("active", hover_bg)],
            foreground=[("disabled", disabled_fg), ("active", hover_fg)],
            bordercolor=[("disabled", disabled_bg), ("active", border)],
            lightcolor=[("disabled", disabled_bg), ("active", border)],
            darkcolor=[("disabled", disabled_bg), ("active", border)],
        )
