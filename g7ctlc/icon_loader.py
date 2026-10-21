"""`IconLoader` (`g7ctlc/icons.py`) concrete implementation, A1 of the
redesign. Needs PyQt6 (QtSvg, `QPixmap`) -- split into its own module,
separate from the Qt-free `icons.py`, so the frozen interface and
constants there stay importable (and testable) without it, same reasoning
as `palette.py`/`theme_runtime.py` versus `tokens.py`/`qss.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from g7ctlc.icons import IconName, IconSize
from g7ctlc.palette import Palette

_ASSETS_ICONS_DIR = Path(__file__).parent / "assets" / "icons"

# `g7ctlc/assets/icons/SOURCES.md`: vendored at Lucide's default
# stroke-width="2"; DIRECTION-A.md calls for 1.5px. This is the one place
# that override happens -- not per call site, not by re-vendoring edited
# copies.
_TARGET_STROKE_WIDTH = "1.5"

_STROKE_COLOR_RE = re.compile(r'stroke="currentColor"')
_STROKE_WIDTH_RE = re.compile(r'stroke-width="[0-9.]+"')


class LucideIconLoader:
    """Implements `IconLoader` against the vendored SVGs. Recolours at
    load time by text substitution on the SVG source (never a coloured
    copy on disk, `DIRECTION-A.md` section 2), then rasterises with
    `QSvgRenderer`. Caches by (name, size, role, palette variant) so a
    theme change invalidates cleanly: construct a fresh loader (or call
    `clear_cache`) from the same place `PaletteProvider` notifies
    listeners (`g7ctlc/theme_runtime.py`).

    HiDPI-correct rendering (device pixel ratio, fractional scaling) is
    A5's job (`IMPLEMENTATION-PLAN.md`); this loader rasterises at the
    nominal pixel size only.
    """

    def __init__(self) -> None:
        self._svg_source_cache: dict[str, str] = {}
        self._icon_cache: dict[tuple[str, int, str, str], QIcon] = {}

    def _source(self, name: str) -> str:
        cached = self._svg_source_cache.get(name)
        if cached is not None:
            return cached
        path = _ASSETS_ICONS_DIR / f"{name}.svg"
        text = path.read_text(encoding="utf-8")
        self._svg_source_cache[name] = text
        return text

    def icon(self, name: IconName, size: IconSize, role: str, palette: Palette) -> QIcon:
        hex_color = getattr(palette, role)
        cache_key = (name, size, role, palette.variant.value)
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            return cached

        svg = self._source(name)
        svg = _STROKE_COLOR_RE.sub(f'stroke="{hex_color}"', svg)
        svg = _STROKE_WIDTH_RE.sub(f'stroke-width="{_TARGET_STROKE_WIDTH}"', svg)

        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()

        icon = QIcon(pixmap)
        self._icon_cache[cache_key] = icon
        return icon

    def clear_cache(self) -> None:
        self._icon_cache.clear()
