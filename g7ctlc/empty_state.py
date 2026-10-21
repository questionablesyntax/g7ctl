"""EmptyState, A2 of the redesign (`DIRECTION-A.md` section 5): "Heading,
one sentence, one or two actions." Used for "no controller" and "unread
profile" per the component inventory.

Takes a `FontLoadResult` (`g7ctlc/fonts.py`) rather than leaving the
heading on the app's default font -- the type scale is applied through
`font_for()`, same as every other sized text in this redesign, not a
parallel QSS font-size rule that would drift from it.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from g7ctlc.fonts import FontLoadResult, font_for


class EmptyState(QWidget):
    def __init__(
        self,
        heading: str,
        sentence: str,
        font_load: FontLoadResult,
        *,
        actions: list[tuple[str, Callable[[], None]]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """`actions` is `[(label, on_click), ...]`, at most two per the spec.
        The first action is given `role="write"` only by the caller setting
        it on the returned button -- this widget doesn't assume which (if
        any) action touches the controller.
        """
        if actions is not None and len(actions) > 2:
            raise ValueError("EmptyState takes at most two actions")
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self.heading_label = QLabel(heading, self)
        self.heading_label.setFont(font_for("title", font_load))
        self.heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.heading_label)

        self.sentence_label = QLabel(sentence, self)
        self.sentence_label.setFont(font_for("body", font_load))
        self.sentence_label.setProperty("role", "secondary")
        self.sentence_label.setWordWrap(True)
        self.sentence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sentence_label)

        self.buttons: list[QPushButton] = []
        if actions:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 8, 0, 0)
            row_layout.setSpacing(8)
            for label, on_click in actions:
                button = QPushButton(label, row)
                button.clicked.connect(on_click)
                row_layout.addWidget(button)
                self.buttons.append(button)
            layout.addWidget(row, 0, Qt.AlignmentFlag.AlignHCenter)

        self.setAccessibleName(heading)
        self.setAccessibleDescription(sentence)
