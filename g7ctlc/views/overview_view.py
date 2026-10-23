"""Overview page, D2 of the redesign (`DIRECTION-A.md` section 7
position 2, mockup at that file's "Overview (home)"): the rail is
primary navigation, and this page's drawing is the Overview's hero and
a shortcut, not a gate.

The drawing here is read-only -- `interactive=False`, so it builds no
hotspots at all, not just inert-looking ones. Buttons is the only
remapping surface (D2's own rework; see `IMPLEMENTATION-PLAN.md`'s D2
section); this page just reflects whatever the Base layer currently
holds, via the same `set_bindings()` callout mechanism, fed by
`load_state()` reading the state dict directly rather than through any
`BindingField`. `keycode_display_text()` is the same read-only wording
`BindingRow.set_shift_reference()` already uses for its Shift column --
not `BindingField`'s own "Raw: ..." phrasing, which is specifically for
an editable field (`g7ctlc/widgets.py`'s docstrings explain why the two
read-only/editable wordings differ).

Everything else the full mockup calls for -- a scope line, a Front/Back
toggle, live connection status, report-rate controls -- is still not
here. Each remains its own real design/wiring decision (live status
needs `DeviceWatcher`, whose plumbing this page hasn't touched), not
something to bundle in sight-unseen.

No `changed` signal use either -- this page still has nothing editable.
It exists so this view fits `MainWindow._build_pages()`'s uniform
`widget.changed.connect(self._on_dirty)` loop without a special case;
it's simply never emitted.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..controller_diagram import ControllerDiagram
from ..palette import DARK_PALETTE, Palette
from ..widgets import keycode_display_text


class OverviewView(QWidget):
    changed = pyqtSignal()

    def __init__(self, palette: Palette = DARK_PALETTE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.diagram = ControllerDiagram(palette, parent=self, interactive=False)
        layout.addWidget(self.diagram, 1)

    def set_palette(self, palette: Palette) -> None:
        self.diagram.set_palette(palette)

    def load_state(self, state: dict) -> None:
        """Base-layer callouts only -- the drawing mirrors what's bound
        right now, not the separate, shared Shift layer (the mockup's own
        "Remapped on this profile: ... Shift layer: 1 binding (shared)"
        line keeps that distinction in words; this page doesn't build
        that summary line yet, see the module docstring)."""
        default_layer = state.get("buttons", {}).get("default", {})
        bindings = {
            button_id: keycode_display_text(value)
            for button_id, value in default_layer.items()
            if value is not None
        }
        self.diagram.set_bindings(bindings)
