"""ModalOverlayBase, A2 of the redesign. `DESIGN-SPEC.md` 10.2 item 7: "The
review sheet is a real modal overlay: input and shortcut blocking, focus
trapping and restoration, dialog semantics." This is the base the later
review sheet (wave 2) and any other overlay (confirm/failure dialogs) build
on -- the frame, the modality, and focus restoration. Content is the
subclass's job.

Scope note: only the enter fade is implemented (`windowOpacity`, `ease.out`,
`DIRECTION-A.md` section 6's duration) -- `done()` closes synchronously, so
an exit fade needs to defer the actual close until its animation finishes,
which is a real-content concern (what shows mid-fade) left to whichever
phase builds the actual review sheet on this base. Scale and reduced-motion
detection are the same deferral. `animate=False` is the hook both attach to.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from g7ctlc.palette import Palette
from g7ctlc.qss import generate_stylesheet
from g7ctlc.tokens import MOTION_BASE, RADIUS_PANEL


class ModalOverlayBase(QDialog):
    """Frameless, application-modal panel centred over its parent.

    Dialog semantics: application-modal (blocks input to the rest of the
    app, not just its own parent -- the review sheet must not let a stray
    click elsewhere start a second concurrent action), Escape closes
    (`QDialog`'s own default -- `reject()`; subclasses override `reject()`
    to ask "Keep editing?" instead of closing silently, wave 2's job, not
    this base's). Focus is captured on open and explicitly restored to
    whichever widget had it, rather than relying on whatever Qt leaves
    focused after a modal dialog closes.
    """

    def __init__(self, palette: Palette, parent: QWidget | None = None, *, animate: bool = True) -> None:
        super().__init__(parent)
        self._animate = animate
        self._focus_before_open: QWidget | None = None
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setStyleSheet(generate_stylesheet(palette) + f"""
QDialog {{
    background: {palette.surface_overlay};
    border: 1px solid {palette.border_control};
    border-radius: {RADIUS_PANEL}px;
}}
""")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(16)

    def exec(self) -> int:  # noqa: A003 - matching QDialog's own name
        self._focus_before_open = QApplication.focusWidget()
        # Settle the real geometry (word-wrapped label heights included)
        # *before* the fade starts, not after. Qt computes a word-wrapped
        # QLabel's height from whatever width it has at the moment -- if
        # that resolves for the first time mid-animation (the dialog's
        # first show(), inside super().exec() below, is otherwise the
        # first point anything forces a layout pass), windowOpacity
        # blends the pre- and post-relayout paints together into the
        # kind of doubled/overlapping text a screenshot mid-fade showed
        # on 2026-10-26. adjustSize() forces that settling up front so
        # the fade animates one stable frame, not a resize in progress.
        self.adjustSize()
        if self._animate:
            self._fade(0.0, 1.0, MOTION_BASE.duration_ms)
        else:
            self.setWindowOpacity(1.0)
        return super().exec()

    def done(self, result: int) -> None:  # noqa: N802 - Qt override signature
        super().done(result)
        if self._focus_before_open is not None:
            self._focus_before_open.setFocus()

    def _fade(self, start: float, end: float, duration_ms: int) -> None:
        self.setWindowOpacity(start)
        self._animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._animation.setDuration(duration_ms)
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()
