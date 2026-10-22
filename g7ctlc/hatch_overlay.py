"""HatchOverlay, A5 of the redesign: the "unread" visual treatment
(`DIRECTION-A.md` section 6's "Unread to read reveal", the one
orchestrated moment this app's motion plan allows). Unknown state must
never look like a real, confirmed reading -- see DESIGN-SPEC.md's
roadmap item "the GUI displays unread state as if it were real", the
bug class A3/A4 already closed structurally (every control actually
disabled while unconfirmed) but without the visual DIRECTION-A.md calls
for: a diagonal hatch pattern over the content, not just dimmed controls
and a banner.

Scope note: wave 1 has no per-field intent/observation boundary (that is
track S, a wave 2 prerequisite -- DESIGN-SPEC.md 10.2 item 2) and no way
to know a single field is unread independent of the whole draft. So this
overlay is whole-page, not per-field: it sits over MainWindow's entire
content area, matching wave 1's actual all-or-nothing confirmation model
(DESIGN-SPEC.md 10.2 item 1) rather than drawing a per-row hatch this
phase has no real data to back.

The reveal itself is one property animation on this overlay's own opacity
(`QGraphicsOpacityEffect`, applied only to this small custom-paint widget,
not to the composite content beneath it -- DESIGN-SPEC.md's motion plan
explicitly warns `QGraphicsOpacityEffect` is costly and clips child
rendering "on large composite widgets"; this sidesteps that by fading the
thin overlay out, not the page underneath it in). Reduced motion is a
constructor flag here, not live OS-preference detection -- Qt has no
portable query for it and reading the GNOME/KDE keys is its own deferred
item (DESIGN-SPEC.md section 6), same gap `ModalOverlayBase` (A2) already
flagged the same way.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from g7ctlc.palette import Palette
from g7ctlc.tokens import MOTION_FAST, MOTION_SLOW

_STRIPE_SPACING = 10


class HatchOverlay(QWidget):
    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        # Covers unconfirmed content without blocking the scrolling that
        # content's own QScrollArea still allows (A3: "browsing isn't
        # editing") -- the hatch is purely a visual layer.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._animation: QPropertyAnimation | None = None
        self.hide()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def set_unread(self, unread: bool, *, reduced_motion: bool = False) -> None:
        """Show (confirmed -> unread, e.g. a profile switch) or hide
        (unread -> confirmed, the one reveal) the hatch. The confirmed ->
        unread direction is instant -- DIRECTION-A.md's orchestrated
        moment is specifically "unknown becoming known", not the reverse;
        going unread should read as immediate, same as every other
        high-frequency state change in this app's motion plan.

        `reduced_motion=True` still animates -- DESIGN-SPEC.md section 6:
        "Single 120ms cross-fade, no stagger" for this exact transition,
        not an instant cut; there is no reduced-motion variant that skips
        the reveal outright.
        """
        if unread:
            if self._animation is not None:
                self._animation.stop()
            self._effect.setOpacity(1.0)
            self.show()
            self.raise_()
            return
        if self.isHidden():
            # isHidden(), not isVisible(): this overlay is usually nested
            # deep inside a window that may never be shown (every test
            # here, and any other offscreen context) -- isVisible()
            # answers false for every child of an unshown top-level
            # regardless of this widget's own show()/hide() calls.
            # isHidden() reflects the explicit call show()/set_unread(True)
            # above made, which is the thing actually worth checking: has
            # a reveal already run, or is there nothing to fade.
            return
        duration = MOTION_FAST.duration_ms if reduced_motion else MOTION_SLOW.duration_ms
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(duration)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_fade_finished)
        self._animation.start()

    def _on_fade_finished(self) -> None:
        self.hide()
        self._effect.setOpacity(1.0)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(self._palette.surface_ground))
        pen = QPen(QColor(self._palette.border_subtle))
        pen.setWidth(1)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        for x in range(-h, w, _STRIPE_SPACING):
            painter.drawLine(x, h, x + h, 0)
        painter.end()
