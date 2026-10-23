"""ScopeLine, A2 of the redesign (`DIRECTION-A.md` section 5): "Static.
Icon plus sentence." Used under a page's title to say what scope the page
edits (a single profile, or "Shared by all profiles") -- scope is carried
by position, icon and words, never colour alone (`DESIGN-SPEC.md` section 2).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from g7ctlc.icon_loader import LucideIconLoader
from g7ctlc.icons import IconName
from g7ctlc.palette import Palette


class ScopeLine(QWidget):
    def __init__(
        self,
        icon_name: IconName,
        sentence: str,
        palette: Palette,
        icon_loader: LucideIconLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._palette = palette
        self._icon_loader = icon_loader

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.icon_label = QLabel(self)
        layout.addWidget(self.icon_label)
        self._refresh_icon()

        self.text_label = QLabel(sentence, self)
        self.text_label.setProperty("role", "secondary")
        layout.addWidget(self.text_label)
        layout.addStretch(1)

        self.setAccessibleName(sentence)

    def _refresh_icon(self) -> None:
        icon = self._icon_loader.icon(self._icon_name, 16, "text_secondary", self._palette)
        self.icon_label.setPixmap(icon.pixmap(16, 16))

    def set_sentence(self, sentence: str) -> None:
        self.text_label.setText(sentence)
        self.setAccessibleName(sentence)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._refresh_icon()
