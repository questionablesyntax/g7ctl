"""Overview page, D2 of the redesign (`DIRECTION-A.md` section 7
position 2, mockup at that file's "Overview (home)"): the rail is
primary navigation, and this page's drawing is the Overview's hero and
a shortcut, not a gate.

Minimal first slice, by design (2026-10-22): just the hero drawing,
reusing `ControllerDiagram` as-is. The full mockup also calls for a
scope line, remapped-bindings callout columns either side of the
drawing, a Front/Back toggle, live connection status, and report-rate
controls -- none of that is here yet. Each is its own real design/
wiring decision (callouts need a binding-summary data source; live
status needs `DeviceWatcher`, whose plumbing this page hasn't touched),
not something to bundle into one commit sight-unseen after D2's Buttons
slice.

No `load_state()`/`changed` signal yet either -- this page has nothing
editable or state-driven in this slice. `changed` still exists so it
fits `MainWindow._build_pages()`'s uniform
`widget.changed.connect(self._on_dirty)` loop without a special case;
it's simply never emitted.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..controller_diagram import ControllerDiagram
from ..palette import DARK_PALETTE, Palette


class OverviewView(QWidget):
    changed = pyqtSignal()

    def __init__(self, palette: Palette = DARK_PALETTE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.diagram = ControllerDiagram(palette, self)
        layout.addWidget(self.diagram, 1)

    def set_palette(self, palette: Palette) -> None:
        self.diagram.set_palette(palette)
