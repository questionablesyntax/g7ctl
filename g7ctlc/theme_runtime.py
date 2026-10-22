"""Qt-aware theme wiring, A1 of the redesign. The only module that
connects `PaletteProvider` (`g7ctlc/palette.py`, framework-agnostic on
purpose) to Qt's own system-theme signal, so widgets have exactly one
place to connect to for "the theme changed, re-fetch your `Palette` and
icons."

Confirmed present on this project's floor in A0: `QStyleHints.colorScheme`
needs Qt 6.5, `pyproject.toml` now requires PyQt6>=6.7.

Also registers the vendored fonts (A1's fonts.py), found genuinely
unwired while building A5's EmptyState: qss.py's QWidget rule has
requested `font-family: "Atkinson Hyperlegible Next"` since A1, but
nothing ever called load_fonts() anywhere in the running app --
QFontDatabase never knew the family existed, so every build through A4
silently fell back to fonts.py's own FALLBACK_CHAIN (Noto Sans/DejaVu
Sans) instead of the chosen typefaces. Not visibly broken (the fallback
chain is real, readable type), just not what A1 actually specified.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication

from g7ctlc.fonts import load_fonts
from g7ctlc.icon_loader import LucideIconLoader
from g7ctlc.palette import Palette, PaletteProvider, ThemeVariant


def _variant_from_qt(scheme: Qt.ColorScheme) -> ThemeVariant:
    if scheme == Qt.ColorScheme.Light:
        return ThemeVariant.LIGHT
    # Qt.ColorScheme.Dark and Qt.ColorScheme.Unknown both fall back to the
    # dark theme -- matches today's app, which has only ever shipped dark.
    return ThemeVariant.DARK


class ThemeController(QObject):
    """Owns one `PaletteProvider` and one `LucideIconLoader` for the
    application's lifetime. `paletteChanged` is the one signal every
    themed widget connects to; it fires with the new `Palette` already
    current on `provider`, and the icon cache already cleared, so a slot
    can just re-pull both.
    """

    paletteChanged = pyqtSignal(object)  # emits the new Palette

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        style_hints = QGuiApplication.styleHints()
        initial = _variant_from_qt(style_hints.colorScheme())
        self.provider = PaletteProvider(initial)
        self.icons = LucideIconLoader()
        self.fonts = load_fonts()
        style_hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self.set_variant(_variant_from_qt(scheme))

    def set_variant(self, variant: ThemeVariant) -> None:
        """Also reachable directly, for the app's own theme-override
        preference, not only the system signal."""
        if variant is self.provider.variant:
            return
        self.provider.set_variant(variant)
        self.icons.clear_cache()
        self.paletteChanged.emit(self.provider.current)

    @property
    def palette(self) -> Palette:
        return self.provider.current
