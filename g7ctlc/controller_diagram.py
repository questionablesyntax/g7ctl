"""ControllerDiagram, D2 of the redesign (`IMPLEMENTATION-PLAN.md` Track
D): the traced front-view line art (`assets/drawing/front.svg`,
provenance in that directory's own `SOURCES.md`), with the ability to
highlight one named button -- the Buttons page uses this to sync the
diagram to whichever row currently has keyboard or mouse focus.

Named hit regions are invisible elements already baked into the SVG
(`fill="none"`, no stroke) -- this widget never draws them; it only asks
`QSvgRenderer.boundsOnElement()` for an id's geometry and paints its own
highlight shape there, in the palette's signal colour. Scales with the
widget the same way the rest of this app's vector assets do: render into
whatever rect the layout gives it, aspect-fit, no fixed pixel size.

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

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSizePolicy, QWidget

from g7ctlc.palette import Palette

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


class ControllerDiagram(QWidget):
    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._renderer = _build_renderer(palette)
        self._highlighted: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 130)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._renderer = _build_renderer(palette)
        self.update()

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
        painter.end()

    def _paint_highlight(self, painter: QPainter, draw_rect: QRectF) -> None:
        vb = self._renderer.viewBoxF()
        bounds = self._renderer.boundsOnElement(self._highlighted)
        if bounds.isEmpty():
            return
        scale_x = draw_rect.width() / vb.width()
        scale_y = draw_rect.height() / vb.height()
        mapped = QRectF(
            draw_rect.x() + (bounds.x() - vb.x()) * scale_x,
            draw_rect.y() + (bounds.y() - vb.y()) * scale_y,
            bounds.width() * scale_x,
            bounds.height() * scale_y,
        )
        pad = max(3.0, mapped.width() * 0.12)
        mapped = mapped.adjusted(-pad, -pad, pad, pad)
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
