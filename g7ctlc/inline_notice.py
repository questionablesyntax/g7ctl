"""InlineNotice, A2 of the redesign (`DIRECTION-A.md` section 5): "Full
hairline border on all sides plus icon plus text, never a side stripe.
Optional action link." Three variants -- info, caution, alarm -- map
directly onto `Palette` text roles and one `IconLoader` name each.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from g7ctlc.icon_loader import LucideIconLoader
from g7ctlc.palette import Palette

NoticeVariant = Literal["info", "caution", "alarm"]

_ICON_BY_VARIANT: dict[NoticeVariant, str] = {
    "info": "info",
    "caution": "triangle-alert",
    "alarm": "circle-alert",
}
_TEXT_ROLE_BY_VARIANT: dict[NoticeVariant, str] = {
    "info": "text_primary",
    "caution": "text_caution",
    "alarm": "text_alarm",
}


class InlineNotice(QWidget):
    def __init__(
        self,
        variant: NoticeVariant,
        text: str,
        palette: Palette,
        icon_loader: LucideIconLoader,
        *,
        action_text: str | None = None,
        on_action: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if variant not in _ICON_BY_VARIANT:
            raise ValueError(f"unknown notice variant: {variant!r}")
        super().__init__(parent)
        self.variant = variant
        self.setProperty("role", f"notice-{variant}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        icon_role = _TEXT_ROLE_BY_VARIANT[variant]
        icon = icon_loader.icon(_ICON_BY_VARIANT[variant], 20, icon_role, palette)
        icon_label = QLabel(self)
        icon_label.setPixmap(icon.pixmap(20, 20))
        icon_label.setAccessibleName("")  # decorative; the notice's own accessible name carries the text
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        self.text_label = QLabel(text, self)
        self.text_label.setWordWrap(True)
        text_role = {"caution": "caution", "alarm": "alarm"}.get(variant)
        if text_role is not None:
            self.text_label.setProperty("role", text_role)
        layout.addWidget(self.text_label, 1)

        self.action_button: QPushButton | None = None
        if action_text is not None:
            self.action_button = QPushButton(action_text, self)
            self.action_button.setProperty("role", "link")
            self.action_button.setFlat(True)
            if on_action is not None:
                self.action_button.clicked.connect(on_action)
            layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignTop)

        self.setAccessibleName(text)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        self.setAccessibleName(text)
