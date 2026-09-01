"""Graphical curve editor: the five draggable handles of a response curve.

Geometry, because it is not obvious from the widget alone (see PROTOCOL.md
"A curve is five handles"):

- The two **endpoints** are the Deadzone and Anti-Deadzone registers. The
  bottom endpoint is (deadzone_initial, anti_deadzone_initial) and the top
  is (deadzone_max, anti_deadzone_max), both **0-100 percentages** of the
  full input/output axes.
- The three **interior points** are stored 0-255, and they are *not* on the
  same axis. They are positions **within the span the endpoints define**:

      x_pct = dz_init  + (px / 255) * (dz_max  - dz_init)
      y_pct = adz_init + (py / 255) * (adz_max - adz_init)

  There is no conversion factor between the two scales -- they are separate
  coordinate systems. Established 2026-08-08; several captures went into
  looking for a factor that does not exist.

The curve is drawn as **straight segments through the handles**, which is
what Nexus itself draws for a Custom curve (its presets are drawn smooth --
the two modes render differently). That is a statement about Nexus's
rendering and **not** about firmware interpolation: the wire carries control
points and nothing about the shape between them, so what the controller
computes between them is unknown and not claimed here.

Ordering is constrained so handles cannot cross, matching Nexus. The
firmware does not require it -- P1=(0,0) alongside P3=(255,255) was accepted
on hardware -- so this is a UI choice.
"""
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .theme import ACCENT, BORDER, SURFACE, TEXT_MUTED

# Interior points are stored 0-255; endpoints are 0-100.
POINT_MAX = 255
PCT_MAX = 100

_MARGIN_L = 34      # room for the "Output" label
_MARGIN_B = 22      # room for the "Input" label
_MARGIN_T = 10
_MARGIN_R = 10
_HANDLE_R = 5.0
_GRAB_R = 11.0      # generous hit radius; 5px targets are miserable to hit


class CurveEditor(QWidget):
    """Five draggable handles. Emits on release, not per pixel."""

    points_changed = pyqtSignal(list)                 # [[x, y], ...] 0-255
    endpoints_changed = pyqtSignal(int, int, int, int)  # dz_i, dz_max, adz_i, adz_max

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._dz = [0, 100]        # initial, max   (percent)
        self._adz = [0, 100]       # initial, max   (percent)
        self._points = [[40, 41], [128, 128], [215, 214]]
        self._configured = True
        # _plot_rect() cache: mouseMoveEvent's hover path (setMouseTracking
        # above) calls it once per handle via _handle_positions()/_hit() on
        # every mouse move over the widget, not just drags -- a real,
        # continuous, high-frequency path. Keyed on (width, height) rather
        # than invalidated via resizeEvent so it self-corrects regardless of
        # whether that event reliably fires in every environment (headless
        # test widgets included), not just the common case.
        self._plot_rect_cache: Optional[QRectF] = None
        self._plot_rect_size: Optional[tuple[int, int]] = None
        self._drag = None          # ("end", 0|1) | ("pt", i) | None
        self._hover = None
        self._enabled_points = True

    # --- state ---------------------------------------------------------

    def set_curve(self, dz_init: int, dz_max: int, adz_init: int, adz_max: int,
                  points: Optional[list]) -> None:
        self._dz = [int(dz_init), int(dz_max)]
        self._adz = [int(adz_init), int(adz_max)]
        # None means the curve block has never been written (see
        # curves.CURVE_SCALE_CONFIGURED). Three handles stacked on the
        # origin is not a curve, so say so rather than drawing one.
        self._configured = points is not None
        if points:
            self._points = [[int(x), int(y)] for x, y in points]
        self.update()

    def points(self) -> list:
        return [list(p) for p in self._points]

    def set_points_editable(self, editable: bool) -> None:
        """Interior points only apply to a Custom curve; the endpoints are
        the deadzone sliders and stay live regardless."""
        self._enabled_points = editable
        self.update()

    # --- coordinate mapping --------------------------------------------

    def _plot_rect(self) -> QRectF:
        size = (self.width(), self.height())
        if self._plot_rect_cache is None or self._plot_rect_size != size:
            self._plot_rect_cache = QRectF(
                _MARGIN_L, _MARGIN_T,
                max(1, self.width() - _MARGIN_L - _MARGIN_R),
                max(1, self.height() - _MARGIN_T - _MARGIN_B))
            self._plot_rect_size = size
        return self._plot_rect_cache

    def _pct_to_px(self, x_pct: float, y_pct: float) -> QPointF:
        r = self._plot_rect()
        return QPointF(r.left() + (x_pct / PCT_MAX) * r.width(),
                       r.bottom() - (y_pct / PCT_MAX) * r.height())

    def _px_to_pct(self, pos) -> tuple[float, float]:
        r = self._plot_rect()
        x = (pos.x() - r.left()) / r.width() * PCT_MAX
        y = (r.bottom() - pos.y()) / r.height() * PCT_MAX
        return max(0.0, min(PCT_MAX, x)), max(0.0, min(PCT_MAX, y))

    def _point_to_pct(self, px: int, py: int) -> tuple[float, float]:
        """Interior point (0-255) -> percent, via the endpoint span."""
        span_x = self._dz[1] - self._dz[0]
        span_y = self._adz[1] - self._adz[0]
        return (self._dz[0] + (px / POINT_MAX) * span_x,
                self._adz[0] + (py / POINT_MAX) * span_y)

    def _pct_to_point(self, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Inverse. A zero-width span cannot be inverted -- the endpoints sit
        on top of each other and every interior point maps to the same place
        -- so the old value is kept rather than dividing by zero."""
        span_x = self._dz[1] - self._dz[0]
        span_y = self._adz[1] - self._adz[0]
        px = round((x_pct - self._dz[0]) / span_x * POINT_MAX) if span_x else None
        py = round((y_pct - self._adz[0]) / span_y * POINT_MAX) if span_y else None
        return px, py

    # --- handles --------------------------------------------------------

    def _handle_positions(self) -> list:
        """[(kind, index, QPointF)] in draw order, bottom endpoint first."""
        out = [("end", 0, self._pct_to_px(self._dz[0], self._adz[0]))]
        if self._configured:
            for i, (px, py) in enumerate(self._points):
                out.append(("pt", i, self._pct_to_px(*self._point_to_pct(px, py))))
        out.append(("end", 1, self._pct_to_px(self._dz[1], self._adz[1])))
        return out

    def _hit(self, pos) -> Optional[tuple]:
        best, best_d = None, _GRAB_R
        for kind, i, p in self._handle_positions():
            if kind == "pt" and not self._enabled_points:
                continue
            d = ((p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = (kind, i), d
        return best

    # --- painting -------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()

        p.fillRect(r, QColor(SURFACE))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRect(r)
        # quarter gridlines, so a handle's position is readable at a glance
        p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.DotLine))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(r.left() + r.width() * f, r.top()),
                       QPointF(r.left() + r.width() * f, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * f),
                       QPointF(r.right(), r.top() + r.height() * f))

        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        p.setFont(font)
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), _MARGIN_B - 4),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Input")
        p.save()
        p.translate(10, r.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-40, -8, 80, 16), Qt.AlignmentFlag.AlignCenter, "Output")
        p.restore()

        if not self._configured:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "no custom curve stored\nfor this profile")

        handles = self._handle_positions()
        # Straight segments through every handle -- what Nexus draws for a
        # Custom curve. See the module docstring: this is Nexus's rendering,
        # not a claim about how the firmware interpolates.
        p.setPen(QPen(QColor(ACCENT), 2))
        for a, b in zip(handles, handles[1:]):
            p.drawLine(a[2], b[2])

        for kind, i, pt in handles:
            live = kind == "end" or self._enabled_points
            fill = QColor(ACCENT) if live else QColor(BORDER)
            if self._hover == (kind, i) and live:
                fill = fill.lighter(130)
            p.setBrush(QBrush(fill))
            p.setPen(QPen(QColor(SURFACE), 2))
            # endpoints drawn slightly larger: they are a different kind of
            # thing (the deadzone registers), not a fourth and fifth point
            radius = _HANDLE_R + (1.5 if kind == "end" else 0)
            p.drawEllipse(pt, radius, radius)
        p.end()

    # --- interaction -----------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._hit(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            hover = self._hit(event.position())
            if hover != self._hover:
                self._hover = hover
                self.setCursor(Qt.CursorShape.SizeAllCursor if hover
                               else Qt.CursorShape.ArrowCursor)
                self.update()
            return
        x_pct, y_pct = self._px_to_pct(event.position())
        kind, i = self._drag
        if kind == "end":
            self._move_endpoint(i, x_pct, y_pct)
        else:
            self._move_point(i, x_pct, y_pct)
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        """Emit once, on release. Emitting per mouse-move would queue a write
        per pixel through the state layer."""
        if self._drag is None:
            return
        kind, _i = self._drag
        self._drag = None
        if kind == "end":
            self.endpoints_changed.emit(self._dz[0], self._dz[1],
                                        self._adz[0], self._adz[1])
        else:
            self.points_changed.emit(self.points())

    def _move_endpoint(self, i: int, x_pct: float, y_pct: float) -> None:
        # Endpoints cannot cross each other. Interior points are stored
        # relative to the span, so they follow automatically -- no rescaling
        # here, which matches the device: moving an endpoint in Nexus leaves
        # the stored interior points untouched.
        if i == 0:
            self._dz[0] = int(round(min(x_pct, self._dz[1])))
            self._adz[0] = int(round(min(y_pct, self._adz[1])))
        else:
            self._dz[1] = int(round(max(x_pct, self._dz[0])))
            self._adz[1] = int(round(max(y_pct, self._adz[0])))

    def _move_point(self, i: int, x_pct: float, y_pct: float) -> None:
        px, py = self._pct_to_point(x_pct, y_pct)
        if px is None or py is None:
            return          # degenerate span, nothing meaningful to set
        lo_x = self._points[i - 1][0] if i > 0 else 0
        hi_x = self._points[i + 1][0] if i < len(self._points) - 1 else POINT_MAX
        lo_y = self._points[i - 1][1] if i > 0 else 0
        hi_y = self._points[i + 1][1] if i < len(self._points) - 1 else POINT_MAX
        self._points[i] = [max(lo_x, min(hi_x, px)), max(lo_y, min(hi_y, py))]
