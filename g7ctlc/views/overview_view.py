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
editable field. `keycode_display_text()` is the read-only wording for a
binding -- not `BindingField`'s own "Raw: ..." phrasing (still used on
Sticks/Motion's own direction pickers), which is specifically for an
editable field (`g7ctlc/widgets.py`'s docstrings explain why the two
read-only/editable wordings differ).

Scope line and report rate are wired now too (owner decision,
2026-10-22): the scope line is a plain `ScopeLine` (already built in A2,
unused until now), reading the viewed profile slot and whichever slot is
physically active on the controller -- both pushed in by `MainWindow`
directly (`set_profile_scope`), not through `load_state()`, since the
profile number must track the rail's own selection immediately, not lag
behind a device read the way the diagram's callouts do. Report rate is a
second, independent `SegmentedControl` instance -- same control that
already lives on its own Profile Settings rail entry (`CRITIC.md #9`'s
fix, `main_window.py::_build_profile_settings_page`), not moved, not the
same widget object. `MainWindow` keeps both in sync off the one
`report_rate_hz` state key, same as `_sync_report_rate_combo()` already
did for the single instance.

Two explicit cuts, owner decision, 2026-10-22: **no Front/Back toggle**
-- every bindable control, including the back paddles, is already on
the single front-view diagram, so a back view would duplicate rather
than add controls. **No live connection status** -- the clamp bar at
the top of the window already shows held/connecting/released/error;
repeating it here would be redundant, not a gap. Neither is coming
back unless the owner revisits it.

`changed` still exists, still never emitted -- this page has nothing
*written* here even now (report rate's `selectionChanged` goes straight
to `MainWindow`, same as the Settings page's own instance; this view
doesn't own that state). It's here only so this view fits
`MainWindow._build_pages()`'s uniform
`widget.changed.connect(self._on_dirty)` loop without a special case.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..controller_diagram import ControllerDiagram
from ..icon_loader import LucideIconLoader
from ..palette import DARK_PALETTE, Palette
from ..scope_line import ScopeLine
from ..segmented_control import SegmentedControl
from ..widgets import keycode_display_text

_REPORT_RATE_TOOLTIP = (
    "Per-profile polling rate. Note: GameSir Nexus disables native "
    "trigger vibration when this is set to 1000 Hz -- likely a real "
    "bandwidth constraint, not a bug."
)


class OverviewView(QWidget):
    changed = pyqtSignal()
    # Mirrors the Settings page's own report_rate_combo -- MainWindow
    # listens to both instances the same way and keeps whichever one the
    # user didn't just touch in sync.
    reportRateChanged = pyqtSignal(object)

    def __init__(
        self,
        palette: Palette = DARK_PALETTE,
        parent: QWidget | None = None,
        icon_loader: LucideIconLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile_slot = 1
        self._active_profile: int | None = None
        icon_loader = icon_loader or LucideIconLoader()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        self.scope_line = ScopeLine(
            "gamepad-2", self._scope_sentence(), palette, icon_loader, self)
        layout.addWidget(self.scope_line)

        self.diagram = ControllerDiagram(palette, parent=self, interactive=False)
        layout.addWidget(self.diagram, 1)

        report_rate_row = QHBoxLayout()
        self.report_rate_combo = SegmentedControl([(str(hz), f"{hz} Hz") for hz in (250, 500, 1000)])
        self.report_rate_combo.setToolTip(_REPORT_RATE_TOOLTIP)
        self.report_rate_combo.blockSignals(True)
        self.report_rate_combo.set_value("1000")
        self.report_rate_combo.blockSignals(False)
        self.report_rate_combo.selectionChanged.connect(self.reportRateChanged)
        report_rate_row.addWidget(self.report_rate_combo)
        report_rate_row.addStretch(1)
        layout.addLayout(report_rate_row)

    def set_palette(self, palette: Palette) -> None:
        self.scope_line.set_palette(palette)
        self.diagram.set_palette(palette)

    def load_state(self, state: dict) -> None:
        """Base-layer callouts only -- the drawing mirrors what's bound
        right now, not the separate, shared Shift layer (the mockup's own
        "Remapped on this profile: ... Shift layer: 1 binding (shared)"
        line keeps that distinction in words; this page doesn't build
        that summary line yet, see the module docstring). Report rate
        isn't read here -- MainWindow pushes it via `set_report_rate()`
        from the one place that already owns keeping every report-rate
        control in sync, `_sync_report_rate_combo()`."""
        default_layer = state.get("buttons", {}).get("default", {})
        bindings = {
            button_id: keycode_display_text(value)
            for button_id, value in default_layer.items()
            if value is not None
        }
        self.diagram.set_bindings(bindings)

    def set_profile_scope(self, slot: int, active_slot: int | None) -> None:
        """Pushed directly by `MainWindow`, not read from `load_state()`'s
        state dict -- the viewed profile number must update the instant
        the rail selection changes, not lag behind whatever a device read
        or import happens to be doing (module docstring)."""
        self._profile_slot = slot
        self._active_profile = active_slot
        self.scope_line.set_sentence(self._scope_sentence())

    def _scope_sentence(self) -> str:
        sentence = f"Applies to Profile {self._profile_slot}."
        if self._active_profile == self._profile_slot:
            sentence += " The controller is using this profile right now."
        return sentence

    def set_report_rate(self, hz: int) -> None:
        """Reflect report_rate_hz without re-emitting reportRateChanged --
        guards via blockSignals() rather than MainWindow's
        `_loading_report_rate_combo` flag, so this stays correct even if
        ever called outside that guarded flow (e.g. directly in a test)."""
        value = str(hz) if hz in (250, 500, 1000) else "1000"
        self.report_rate_combo.blockSignals(True)
        try:
            self.report_rate_combo.set_value(value)
        finally:
            self.report_rate_combo.blockSignals(False)
