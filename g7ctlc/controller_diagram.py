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

Callouts (`set_bindings`) form an always-visible perimeter map. Every
bindable control gets one; ids absent from the mapping show the one local
unmapped string below. Remapped text is still sourced from the caller's
own display text, so the diagram never invents a second description for a
binding.

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

from PyQt6.QtCore import QByteArray, QEvent, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from g7ctlc.palette import Palette
from pyg7.buttons import KNOWN_BUTTON_IDS

_SVG_PATH = Path(__file__).parent / "assets" / "drawing" / "front.svg"
_SVG_SOURCE = _SVG_PATH.read_text(encoding="utf-8")

_FILL_CURRENT_COLOR_RE = re.compile(r'fill="currentColor"')
_STROKE_CURRENT_COLOR_RE = re.compile(r'stroke="currentColor"')

# This is deliberately the only display string owned by the diagram. Binding
# text always comes from the caller, which keeps the map and picker wording in
# lockstep.
UNMAPPED_CALLOUT_TEXT = "Not remapped"

# Display names for the 21 bindable controls, shared by every page that shows
# the diagram so a control reads consistently everywhere it appears.
BUTTON_LABELS = {
    "share": "Share", "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "l3": "L3 (stick click)", "r3": "R3 (stick click)",
    "view": "View", "menu": "Menu", "l4": "L4", "r4": "R4",
    "l5": "L5", "r5": "R5",
    "dpad_up": "D-Pad Up", "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left", "dpad_right": "D-Pad Right",
}

# Padding (px) kept clear around the aspect-fit drawing so the highlight
# ring on an edge button (e.g. l4/r4) never clips against the widget edge.
_MARGIN = 4

# The traced source contains very small, intentional contour variations.  A
# modest supersample/downsample pass keeps those same contours but removes
# their pixel stair-steps when the diagram is viewed large.
_ART_SUPERSAMPLE = 3

# The ordered rows leave a stable, readable perimeter around the drawing.
# Their vertical order follows the control positions, which keeps leaders
# uncrossed even when every binding has a long display string.
_CALLOUT_SIDES: dict[str, tuple[str, ...]] = {
    "top": ("view", "share", "menu"),
    "left": ("l5", "lt", "lb", "l3", "dpad_up", "dpad_left", "dpad_right", "dpad_down"),
    "right": ("r5", "rt", "rb", "y", "x", "b", "a", "r3"),
    "bottom": ("l4", "r4"),
}

# The usual evenly-spaced rail works for most controls.  Controls that share
# a horizontal level need deliberate lanes so their leaders never merge or
# cross.  Fractions run from the callout card (0) toward the artwork (1).
_CALLOUT_ROUTE_FRACTIONS: dict[str, float] = {
    "l5": 0.08, "lt": 0.25, "lb": 0.62,
    "dpad_left": 0.04, "dpad_right": 0.36,
    "r5": 0.10, "rt": 0.23, "rb": 0.33, "y": 0.10,
    "x": 0.20, "b": 0.48,
}

# These controls take a short vertical departure before entering their rail.
# That keeps their long horizontal run on a distinct level.  All remaining
# routes make their first turn at the outer rail, immediately beside the
# label, which prevents a late vertical segment from crossing another leader.
_CALLOUT_EARLY_DEPARTURES: dict[str, float] = {
    "l5": -12.0,
    "r5": -12.0,
    "x": -11.0,
    "y": 10.0,
    "dpad_left": -13.0,
}

# Share sits below the guide glyph.  Its top-card route takes a short step
# left before rising, so its vertical run clears that glyph instead of
# bisecting it.
_CALLOUT_TOP_LANE_WIDTHS: dict[str, float] = {"share": -1.7}


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
        """`interactive=False` skips building any hotspots at all -- line
        art, the selected-button highlight and
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
        self._labels = labels or BUTTON_LABELS
        self._bindings: dict[str, str] = {}
        self._hotspots: dict[str, _DiagramHotspot] = {}
        self._callout_rects: dict[str, QRectF] = {}
        # (size, image) of the supersampled line art; see _paint_line_art().
        self._art_cache: tuple[tuple[int, int], QImage] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # ButtonsView is scroll-wrapped; a larger hard minimum here would
        # force every tab in the main window to inherit the diagram's height.
        self.setMinimumSize(160, 130)
        self.setMouseTracking(True)
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
        self._art_cache = None
        self.update()
        for hotspot in self._hotspots.values():
            hotspot.update()

    def set_bindings(self, bindings: dict[str, str]) -> None:
        """`bindings` maps button_id -> the exact display text its own
        field already shows, for every button that currently has a
        non-default binding. An id left out remains absent from
        `self._bindings`, but paints with UNMAPPED_CALLOUT_TEXT."""
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
        return f"{label} button, remapped to {text}" if text else f"{label} button, {UNMAPPED_CALLOUT_TEXT.lower()}"

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

    def _callout_side_width(self) -> float:
        """Keep the side rail outside the artwork, even in a narrow shell."""
        return min(260.0, max(72.0, self.width() * 0.205))

    def _draw_rect(self) -> QRectF:
        """The aspect-fit rect for the artwork, leaving a clear callout rail."""
        rail = self._callout_side_width()
        # The cards need their full text width, but the channel between each
        # rail and the drawing only needs enough room to turn a leader line.
        # Keeping it deliberately narrow gives the controller its share of
        # the composition instead of marooning it between two empty gutters.
        channel_gap = max(16.0, self.width() * 0.025)
        vertical_rail = max(44.0, self.height() * 0.085)
        art_width = self.width() - (rail + channel_gap) * 2 - _MARGIN * 4
        art_height = self.height() - vertical_rail * 2
        if art_width < 120 or art_height < 130:
            avail = QRectF(self.rect()).adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        else:
            avail = QRectF(rail + channel_gap + _MARGIN * 2, vertical_rail, art_width, art_height)
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
        self._paint_line_art(painter, draw_rect)
        if self._highlighted is not None:
            self._paint_highlight(painter, draw_rect)
        self._paint_callouts(painter, draw_rect)
        painter.end()

    def _paint_line_art(self, painter: QPainter, draw_rect: QRectF) -> None:
        """Render the SVG at a modest higher resolution before compositing it.

        The source remains vector geometry; this only smooths the final
        raster edge produced by Qt's SVG renderer.  It matters most for the
        long traced shell contour at large diagram sizes.
        """
        width = max(1, round(draw_rect.width() * _ART_SUPERSAMPLE))
        height = max(1, round(draw_rect.height() * _ART_SUPERSAMPLE))
        # Rendering the whole SVG at 3x is the expensive part, and the result
        # only changes with the size or the palette (set_palette() clears it),
        # so repaints from a hover, a highlight or a callout change reuse it.
        if self._art_cache is not None and self._art_cache[0] == (width, height):
            image = self._art_cache[1]
        else:
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            art_painter = QPainter(image)
            art_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._renderer.render(art_painter, QRectF(0, 0, width, height))
            art_painter.end()
            self._art_cache = ((width, height), image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(draw_rect, image)

    def _paint_highlight(self, painter: QPainter, draw_rect: QRectF) -> None:
        mapped = self._mapped_bounds(self._highlighted, draw_rect)
        if mapped is None:
            return
        border = QColor(self._palette.signal_mark)
        # A ring preserves the button's letter/glyph. A filled disc made A/B/X/Y
        # unreadable precisely when the user needed the selected state most.
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(2.5)
        painter.setPen(pen)
        radius = min(mapped.width(), mapped.height()) / 2
        painter.drawRoundedRect(mapped, radius, radius)

    def _callout_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        return font

    def _paint_callouts(self, painter: QPainter, draw_rect: QRectF) -> None:
        painter.setFont(self._callout_font())
        metrics = painter.fontMetrics()
        layouts = self._callout_layout(metrics)
        self._callout_rects = {button_id: box for button_id, box, _side in layouts}
        for button_id, box, side in layouts:
            mapped = self._mapped_bounds(button_id, draw_rect)
            if mapped is None:
                continue
            remapped = button_id in self._bindings
            self._paint_leader(painter, button_id, mapped, box, side, remapped)
            self._paint_one_callout(painter, metrics, button_id, box, remapped)

    def _callout_layout(self, metrics) -> list[tuple[str, QRectF, str]]:
        """Return non-overlapping perimeter cards in widget coordinates."""
        margin = 6.0
        card_h = max(24.0, metrics.height() + 8.0)
        side_w = self._callout_side_width()
        layouts: list[tuple[str, QRectF, str]] = []

        for side in ("left", "right"):
            ids = _CALLOUT_SIDES[side]
            usable_top = max(70.0, self.height() * 0.13)
            usable_bottom = self.height() - max(70.0, self.height() * 0.13)
            desired = []
            draw_rect = self._draw_rect()
            for button_id in ids:
                mapped = self._mapped_bounds(button_id, draw_rect)
                center_y = mapped.center().y() if mapped is not None else usable_top
                desired.append(max(usable_top, min(center_y - card_h / 2, usable_bottom - card_h)))
            positions = []
            for target in desired:
                positions.append(max(target, positions[-1] + card_h + 4.0 if positions else target))
            overflow = positions[-1] - (usable_bottom - card_h)
            if overflow > 0:
                positions = [y - overflow for y in positions]
            x = margin if side == "left" else self.width() - side_w - margin
            for button_id, y in zip(ids, positions):
                layouts.append((button_id, QRectF(x, y, side_w, card_h), side))

        top_w = min(220.0, max(96.0, self.width() * 0.17))
        top_gap = max(6.0, self.width() * 0.012)
        top_total = top_w * 3 + top_gap * 2
        top_x = (self.width() - top_total) / 2
        for index, button_id in enumerate(_CALLOUT_SIDES["top"]):
            layouts.append((button_id, QRectF(top_x + index * (top_w + top_gap), margin, top_w, card_h), "top"))

        bottom_w = min(220.0, max(112.0, self.width() * 0.19))
        bottom_gap = max(12.0, self.width() * 0.03)
        bottom_total = bottom_w * 2 + bottom_gap
        bottom_x = (self.width() - bottom_total) / 2
        bottom_y = self.height() - card_h - margin
        for index, button_id in enumerate(_CALLOUT_SIDES["bottom"]):
            layouts.append((button_id, QRectF(bottom_x + index * (bottom_w + bottom_gap), bottom_y, bottom_w, card_h), "bottom"))
        return layouts

    def _callout_text(self, button_id: str) -> str:
        return self._bindings.get(button_id, UNMAPPED_CALLOUT_TEXT)

    def _callout_full_text(self, button_id: str) -> str:
        return f"{self._label_for(button_id)} — {self._callout_text(button_id)}"

    def _paint_leader(
        self, painter: QPainter, button_id: str, mapped: QRectF, box: QRectF, side: str, remapped: bool
    ) -> None:
        color = QColor(self._palette.signal_mark if remapped else self._palette.border_control)
        pen = QPen(color, 1.3 if remapped else 1.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        anchor = mapped.center()
        order = _CALLOUT_SIDES[side]
        position = order.index(button_id) + 1
        fraction = _CALLOUT_ROUTE_FRACTIONS.get(button_id, position / (len(order) + 1))
        art = self._draw_rect()
        if side == "left":
            end = QPointF(box.right(), box.center().y())
            channel = box.right() + (art.left() - box.right()) * fraction
            path = QPainterPath(anchor)
            departure_y = anchor.y() + _CALLOUT_EARLY_DEPARTURES.get(button_id, 0.0)
            if button_id in _CALLOUT_EARLY_DEPARTURES:
                path.lineTo(anchor.x(), departure_y)
            path.lineTo(channel, departure_y)
            path.lineTo(channel, end.y())
            path.lineTo(end)
        elif side == "right":
            end = QPointF(box.left(), box.center().y())
            channel = box.left() - (box.left() - art.right()) * fraction
            path = QPainterPath(anchor)
            departure_y = anchor.y() + _CALLOUT_EARLY_DEPARTURES.get(button_id, 0.0)
            if button_id in _CALLOUT_EARLY_DEPARTURES:
                path.lineTo(anchor.x(), departure_y)
            path.lineTo(channel, departure_y)
            path.lineTo(channel, end.y())
            path.lineTo(end)
        elif side == "top":
            end = QPointF(box.center().x(), box.bottom())
            channel = box.bottom() + (art.top() - box.bottom()) * fraction
            path = QPainterPath(anchor)
            lane_x = anchor.x() + mapped.width() * _CALLOUT_TOP_LANE_WIDTHS.get(button_id, 0.0)
            if lane_x != anchor.x():
                path.lineTo(lane_x, anchor.y())
            path.lineTo(lane_x, channel)
            path.lineTo(end.x(), channel)
            path.lineTo(end)
        else:
            end = QPointF(box.center().x(), box.top())
            channel = box.top() - (box.top() - art.bottom()) * fraction
            path = QPainterPath(anchor)
            path.lineTo(anchor.x(), channel)
            path.lineTo(end.x(), channel)
            path.lineTo(end)
        painter.drawPath(path)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(mapped.center(), 2.0 if remapped else 1.5, 2.0 if remapped else 1.5)

    def _paint_one_callout(self, painter, metrics, button_id: str, box: QRectF, remapped: bool) -> None:
        text_color = QColor(self._palette.text_signal if remapped else self._palette.text_secondary)
        border = QColor(self._palette.signal_mark if remapped else self._palette.border_subtle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._palette.surface_raised))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QPen(border, 1.1 if remapped else 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        font = painter.font()
        font.setBold(remapped)
        painter.setFont(font)
        elided = metrics.elidedText(self._callout_full_text(button_id), Qt.TextElideMode.ElideRight, int(box.width() - 12))
        painter.setPen(text_color)
        painter.drawText(box.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.setFont(self._callout_font())

    def _callout_at(self, point) -> str | None:
        # QRectF.contains() takes only a QPointF, but a tooltip event hands over
        # a QPoint (QHelpEvent.pos()) while mouse events give a QPointF.
        point = QPointF(point)
        for button_id, rect in self._callout_rects.items():
            if rect.contains(point):
                return button_id
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if (button_id := self._callout_at(event.position())) and button_id in self._hotspots:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        button_id = self._callout_at(event.position())
        hotspot = self._hotspots.get(button_id) if button_id else None
        if hotspot is not None and event.button() == Qt.MouseButton.LeftButton:
            hotspot.setFocus(Qt.FocusReason.MouseFocusReason)
            self.activated.emit(button_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def event(self, event) -> bool:  # noqa: N802 - Qt override signature
        if event.type() == QEvent.Type.ToolTip:
            button_id = self._callout_at(event.pos())
            if button_id:
                QToolTip.showText(event.globalPos(), self._callout_full_text(button_id), self, self._callout_rects[button_id].toRect())
                return True
        return super().event(event)
