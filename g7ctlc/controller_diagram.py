"""ControllerDiagram, D2 of the redesign (`IMPLEMENTATION-PLAN.md` Track
D): the traced front-view line art (`assets/drawing/front.svg`,
provenance in that directory's own `SOURCES.md`) as the primary button-
remapping surface, not a decoration beside the table (see this module's
own history in `IMPLEMENTATION-PLAN.md`'s D2 section --
an earlier pass built this as a highlight that only mirrored table focus,
which is NOT what this widget does).

Each bindable part is a real Qt focus target (`_DiagramHotspot`), not a
simulated hit-test inside one big widget -- the SVG's named hit regions
(`fill="none"`, no stroke, baked into the source) are just painted
geometry, so Tab needs an actual child widget per part to land on. A
hotspot's geometry is computed from `QSvgRenderer.boundsOnElement()`
mapped through the same aspect-fit math the highlight ring and the
callout placement both reuse (`_mapped_bounds`) -- one geometry
computation, not three that could drift apart.

Clicking or keyboard-activating a hotspot emits `activated(button_id)`;
the owning page (e.g. `ButtonsView`) is the one that knows what that
means (which layer, which picker), so this widget stays ignorant of
bindings beyond the display text it's handed for callouts.

Callouts (`set_bindings`) show only for remapped controls -- an id absent
from the mapping paints nothing, matching `DIRECTION-A.md`'s "the drawing
stays quiet" rule -- sourced from whatever text the caller's own field
already displays, not recomputed here, so the callout can never say
something different from the row it mirrors.

Theming, real bug fixed 2026-10-22: `fill="currentColor"` in the SVG
source does *not* pick up the host `QPainter`'s pen the way it would in
a browser -- `QSvgRenderer` resolves it once, internally, against its
own default (black), regardless of what the painter handed to
`render()`. It rendered black line art on the dark theme until this was
caught. `LucideIconLoader` (`icon_loader.py`) already solved this the
only way that actually works for `QSvgRenderer`: text-substitute the
colour into the SVG source itself before constructing the renderer.
This widget does the same, rebuilding its renderer whenever the palette
changes rather than trying to recolour at paint time.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QByteArray, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSizePolicy, QWidget

from g7ctlc.palette import Palette
from pyg7.buttons import KNOWN_BUTTON_IDS

_SVG_PATH = Path(__file__).parent / "assets" / "drawing" / "front.svg"
_SVG_SOURCE = _SVG_PATH.read_text(encoding="utf-8")

_FILL_CURRENT_COLOR_RE = re.compile(r'fill="currentColor"')
_STROKE_CURRENT_COLOR_RE = re.compile(r'stroke="currentColor"')

# Padding (px) kept clear around the aspect-fit drawing so the highlight
# ring on an edge button (e.g. l4/r4) never clips against the widget edge.
_MARGIN = 4


def _build_renderer(palette: Palette) -> QSvgRenderer:
    hex_color = palette.text_primary
    svg = _FILL_CURRENT_COLOR_RE.sub(f'fill="{hex_color}"', _SVG_SOURCE)
    svg = _STROKE_CURRENT_COLOR_RE.sub(f'stroke="{hex_color}"', svg)
    return QSvgRenderer(QByteArray(svg.encode("utf-8")))


class _DiagramHotspot(QWidget):
    """One focusable Tab stop over a single named hit region. Paints only
    its own hover/focus ring -- the line art, the selected-button
    highlight and the binding callouts are all the parent diagram's own
    paintEvent, since they need to draw relative to the SVG geometry the
    hotspot doesn't otherwise care about.
    """

    activated = pyqtSignal()

    def __init__(self, button_id: str, diagram: ControllerDiagram) -> None:
        super().__init__(diagram)
        self.button_id = button_id
        self._diagram = diagram
        self._hovered = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        super().focusInEvent(event)
        self._diagram.set_highlighted(self.button_id)
        self._diagram.focused.emit(self.button_id)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        super().focusOutEvent(event)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        self._hovered = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.activated.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if not (self.hasFocus() or self._hovered):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(rect.width(), rect.height()) / 2
        palette = self._diagram._palette
        if self.hasFocus():
            # Focus ring only, never a fill -- `focus` and `selected`
            # (the diagram's own signal-coloured highlight) are
            # deliberately distinct states (DIRECTION-A.md component
            # table, ControllerDrawing row), and focus never borrows the
            # accent colour.
            painter.setPen(QPen(QColor(palette.focus_ring), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.surface_raised))
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()


class ControllerDiagram(QWidget):
    # Emits the hit-region's button id on click, Enter or Space -- the
    # owning page decides what that means (which layer, which picker).
    activated = pyqtSignal(str)
    # Emits whenever a hit region gains keyboard or mouse focus -- Tab
    # alone (no activation) reaches every part, and the owning page uses
    # this to show that part's own detail (binding, Latch, Shift
    # reference) without necessarily opening the picker.
    focused = pyqtSignal(str)

    def __init__(
        self,
        palette: Palette,
        parent: QWidget | None = None,
        *,
        labels: dict[str, str] | None = None,
        order: list[str] | None = None,
        interactive: bool = True,
    ) -> None:
        """`interactive=False` (Overview's own instance) skips building any
        hotspots at all -- line art, the selected-button highlight and
        `set_bindings()`'s callouts all work identically either way, since
        none of that painting depends on a hotspot existing. A page that
        isn't a remapping surface gets no Tab stops and no `activated`/
        `focused` signals, rather than a Tab-reachable, clickable-looking
        part that silently does nothing (the real gap this flag closes,
        found once the Buttons page's own diagram started doing real work
        -- see HANDOFF.md's "Findings in today's code")."""
        super().__init__(parent)
        self._palette = palette
        self._renderer = _build_renderer(palette)
        self._highlighted: str | None = None
        self._labels = labels or {}
        self._bindings: dict[str, str] = {}
        self._hotspots: dict[str, _DiagramHotspot] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 130)
        if interactive:
            self._build_hotspots(order or list(KNOWN_BUTTON_IDS))
            self._layout_hotspots()

    # -- construction -----------------------------------------------------

    def _build_hotspots(self, order: list[str]) -> None:
        for button_id in order:
            if not self._renderer.elementExists(button_id):
                continue
            hotspot = _DiagramHotspot(button_id, self)
            hotspot.setAccessibleName(self._accessible_name(button_id))
            hotspot.activated.connect(lambda b=button_id: self.activated.emit(b))
            self._hotspots[button_id] = hotspot

    def hotspot_for(self, button_id: str) -> QWidget | None:
        """The focusable child for `button_id`, for a caller that wants to
        anchor its own popup (e.g. the keycode picker) at the part the
        user actually activated rather than at a table row."""
        return self._hotspots.get(button_id)

    # -- palette / bindings -------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._renderer = _build_renderer(palette)
        self.update()
        for hotspot in self._hotspots.values():
            hotspot.update()

    def set_bindings(self, bindings: dict[str, str]) -> None:
        """`bindings` maps button_id -> the exact display text its own
        field already shows, for every button that currently has a
        non-default binding. An id left out is "not remapped" and paints
        no callout -- see the module docstring for why the drawing stays
        quiet rather than labelling all 21 controls at once."""
        if bindings == self._bindings:
            return
        self._bindings = dict(bindings)
        for button_id, hotspot in self._hotspots.items():
            hotspot.setAccessibleName(self._accessible_name(button_id))
        self.update()

    def _label_for(self, button_id: str) -> str:
        return self._labels.get(button_id, button_id.upper())

    def _accessible_name(self, button_id: str) -> str:
        label = self._label_for(button_id)
        text = self._bindings.get(button_id)
        return f"{label} button, remapped to {text}" if text else f"{label} button, not remapped"

    def set_highlighted(self, button_id: str | None) -> None:
        """button_id must be a hit-region element id in the SVG (or None
        to clear). An unknown id is treated the same as None rather than
        raising -- a page wiring bug here shouldn't crash the GUI, just
        silently show no highlight, and `set_highlighted` is called from
        several signal handlers where raising would be hard to trace back."""
        resolved = button_id if button_id and self._renderer.elementExists(button_id) else None
        if resolved == self._highlighted:
            return
        self._highlighted = resolved
        self.update()

    # -- geometry (shared by hotspot layout, the highlight ring and
    # callout placement, so there is exactly one aspect-fit/scale
    # computation to get right) -------------------------------------------

    def _draw_rect(self) -> QRectF:
        """The aspect-fit rect the SVG renders into, inside this widget."""
        avail = QRectF(self.rect()).adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        vb = self._renderer.viewBoxF()
        if avail.width() <= 0 or avail.height() <= 0 or vb.width() <= 0 or vb.height() <= 0:
            return avail
        scale = min(avail.width() / vb.width(), avail.height() / vb.height())
        w, h = vb.width() * scale, vb.height() * scale
        x = avail.x() + (avail.width() - w) / 2
        y = avail.y() + (avail.height() - h) / 2
        return QRectF(x, y, w, h)

    def _mapped_bounds(self, button_id: str | None, draw_rect: QRectF) -> QRectF | None:
        """`button_id`'s SVG-space hit region, mapped into this widget's
        own coordinates and padded a little past its literal bounds --
        shared by the hotspot layout, the selected-button highlight and
        callout placement. None for an unknown id or a zero-size draw
        rect (e.g. before the widget has ever been shown)."""
        if not button_id:
            return None
        vb = self._renderer.viewBoxF()
        if draw_rect.width() <= 0 or draw_rect.height() <= 0 or vb.width() <= 0 or vb.height() <= 0:
            return None
        bounds = self._renderer.boundsOnElement(button_id)
        if bounds.isEmpty():
            return None
        scale_x = draw_rect.width() / vb.width()
        scale_y = draw_rect.height() / vb.height()
        mapped = QRectF(
            draw_rect.x() + (bounds.x() - vb.x()) * scale_x,
            draw_rect.y() + (bounds.y() - vb.y()) * scale_y,
            bounds.width() * scale_x,
            bounds.height() * scale_y,
        )
        pad = max(3.0, mapped.width() * 0.12)
        return mapped.adjusted(-pad, -pad, pad, pad)

    def _layout_hotspots(self) -> None:
        draw_rect = self._draw_rect()
        for button_id, hotspot in self._hotspots.items():
            mapped = self._mapped_bounds(button_id, draw_rect)
            hotspot.setGeometry(mapped.toRect() if mapped is not None else QRect())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        super().resizeEvent(event)
        self._layout_hotspots()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        # No painter.setPen() for the line art itself -- see the module
        # docstring. The colour is already baked into self._renderer by
        # _build_renderer(); a pen set here would do nothing for it and
        # falsely suggest this is how the theming works.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_rect = self._draw_rect()
        self._renderer.render(painter, draw_rect)
        if self._highlighted is not None:
            self._paint_highlight(painter, draw_rect)
        self._paint_callouts(painter, draw_rect)
        painter.end()

    def _paint_highlight(self, painter: QPainter, draw_rect: QRectF) -> None:
        mapped = self._mapped_bounds(self._highlighted, draw_rect)
        if mapped is None:
            return
        fill = QColor(self._palette.surface_signal_tint)
        border = QColor(self._palette.signal_mark)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        radius = min(mapped.width(), mapped.height()) / 2
        painter.drawRoundedRect(mapped, radius, radius)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawRoundedRect(mapped, radius, radius)

    def _callout_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        return font

    def _paint_callouts(self, painter: QPainter, draw_rect: QRectF) -> None:
        if not self._bindings:
            return
        painter.setFont(self._callout_font())
        metrics = painter.fontMetrics()
        center_x = draw_rect.center().x()
        for button_id, text in self._bindings.items():
            mapped = self._mapped_bounds(button_id, draw_rect)
            if mapped is None:
                continue
            self._paint_one_callout(painter, metrics, mapped, text, center_x)

    def _paint_one_callout(self, painter, metrics, mapped: QRectF, text: str, center_x: float) -> None:
        pad_x, pad_y, gap = 6.0, 3.0, 6.0
        box_w = metrics.horizontalAdvance(text) + pad_x * 2
        box_h = metrics.height() + pad_y * 2
        x = mapped.right() + gap if mapped.center().x() <= center_x else mapped.left() - gap - box_w
        y = mapped.center().y() - box_h / 2
        x = max(2.0, min(x, self.width() - box_w - 2.0))
        y = max(2.0, min(y, self.height() - box_h - 2.0))
        box = QRectF(x, y, box_w, box_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._palette.surface_panel))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QPen(QColor(self._palette.border_subtle), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor(self._palette.text_secondary))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
