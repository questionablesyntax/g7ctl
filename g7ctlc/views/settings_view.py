"""Dock page: LED Brightness and Auto On/Off -- genuinely global,
device-wide settings (not per-profile, see pyg7/dock_settings.py),
found in Nexus's own top-level "Settings" section rather than a
per-category tab. Renamed "Dock" in the rail (DIRECTION-A.md section 3)
-- this module keeps its original name, SettingsView, since MainWindow
and tests already address it that way and nothing about the class
itself changed meaning.

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): this
page's second slice onto the real per-field draft model (after
Vibration's levels) -- `fieldTouched`/`fieldReverted` replace nothing of
the existing `_brightness_touched`/`_on_edit()` old-path write (kept,
unchanged, so Sync Now and Export still see every edit). Both
`DOCK_FIELDS` entries are plain `FieldSpec` with no coupling at all
(simpler than Vibration's levels in that one respect), and this is the
first SHARED-scope page wired on -- its `DesiredDraft` must survive a
profile switch, unlike Vibration's per-profile one (DESIGN-SPEC.md 10.1
#5). `profile=1` on every `ApprovedIntent` here is an ignored
placeholder, not a real scope -- `DOCK_FIELDS`' own `build_kwargs`
already discards it, matching `dock_settings.set_value()`'s own
no-profile-argument signature.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyg7.field_spec import DOCK_FIELDS

from ..checkbox import Checkbox
from ..segmented_control import SegmentedControl

_DOCK_PROFILE_PLACEHOLDER = 1  # see module docstring -- ignored by DOCK_FIELDS' own build_kwargs

BRIGHTNESS_OPTIONS = [(0, "Off"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]
_BRIGHTNESS_SEGMENTS = [(str(percent), label) for percent, label in BRIGHTNESS_OPTIONS]


def _nearest_brightness_index(value: Optional[int]) -> int:
    """Which of BRIGHTNESS_OPTIONS a value is closest to, for display --
    mirrors vibration_view.py's _nearest_level_index() for the identical
    problem: pyg7/dock_settings.py and the CLI's `dock-set brightness`
    accept any 0-100 value, but this control only offers five discrete
    stops. Display only: doesn't touch the state dict, so an off-scale
    value stays exactly what it was until this control is actually
    edited."""
    if value is None:
        value = 100
    return min(
        range(len(BRIGHTNESS_OPTIONS)),
        key=lambda i: abs(BRIGHTNESS_OPTIONS[i][0] - value),
    )


class SettingsView(QWidget):
    changed = pyqtSignal()
    # path, FieldSpec, desired value, profile (an ignored placeholder here
    # -- see module docstring) -- MainWindow's DesiredDraft ledger listens
    # to this, not to `changed` (same shape as VibrationView's signal).
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
        # True once the user has genuinely picked a brightness -- see
        # _on_edit()'s own comment for why this can't just be "whatever
        # the control currently shows."
        self._brightness_touched = False
        self._auto_on_off_touched = False
        # The values as of the last load_state() -- purely for this view's
        # own "was X" mark text, same role as VibrationView's
        # _loaded_levels; MainWindow's DesiredDraft is the authoritative
        # record.
        self._loaded: dict[str, Optional[object]] = {}
        # Modest content today, but QTabWidget sizes the whole main window's
        # minimum height to fit the LARGEST tab page, not just whichever is
        # visible -- wrapped for consistency with every other tab so this
        # can't quietly become the new bottleneck as it grows. See
        # TriggersView's __init__ for the incident that made this explicit.
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        dock_box = QGroupBox("Dock")
        form = QFormLayout(dock_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        # Stepped-meter SegmentedControl (DIRECTION-A.md section 5), same
        # pattern as VibrationView's five-stop levels -- a cumulative fill
        # reads as "how much brightness" more honestly than a dropdown.
        self.brightness = SegmentedControl(_BRIGHTNESS_SEGMENTS, meter=True)
        self.brightness.setToolTip(
            "Dock LED brightness. Device-wide -- not per-profile, unlike "
            "every other page in this app."
        )
        # Order matters: Qt fires same-signal slots in connection order, and
        # _on_edit() below only writes brightness into state when
        # _brightness_touched is already True. REAL BUG, found 2026-09-18
        # (Sol's bug-sweep): this used to connect _on_edit first, so the
        # FIRST edit after a load ran it while the flag was still False --
        # the control showed the new value but state silently kept the old
        # one until a second edit. _mark_brightness_touched must run first.
        self.brightness.selectionChanged.connect(self._mark_brightness_touched)
        self.brightness.selectionChanged.connect(self._on_edit)
        brightness_row = QWidget()
        brightness_layout = QHBoxLayout(brightness_row)
        brightness_layout.setContentsMargins(0, 0, 0, 0)
        brightness_layout.setSpacing(8)
        brightness_layout.addWidget(self.brightness)
        self._brightness_was_label = QLabel("")
        self._brightness_was_label.setProperty("role", "muted")
        self._brightness_was_label.setVisible(False)
        brightness_layout.addWidget(self._brightness_was_label)
        self._brightness_revert_btn = QPushButton("Revert")
        self._brightness_revert_btn.setProperty("role", "link")
        self._brightness_revert_btn.setVisible(False)
        self._brightness_revert_btn.clicked.connect(self._revert_brightness)
        brightness_layout.addWidget(self._brightness_revert_btn)
        brightness_layout.addStretch(1)
        form.addRow("LED Brightness", brightness_row)

        self.auto_on_off = Checkbox("Auto On/Off (with docking/undocking)")
        self.auto_on_off.setToolTip(
            "Automatically power the dock's LED on when a controller docks "
            "and off when it undocks. Device-wide -- not per-profile."
        )
        self.auto_on_off.toggled.connect(self._mark_auto_on_off_touched)
        self.auto_on_off.toggled.connect(self._on_edit)
        auto_row = QWidget()
        auto_layout = QHBoxLayout(auto_row)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(8)
        auto_layout.addWidget(self.auto_on_off)
        self._auto_was_label = QLabel("")
        self._auto_was_label.setProperty("role", "muted")
        self._auto_was_label.setVisible(False)
        auto_layout.addWidget(self._auto_was_label)
        self._auto_revert_btn = QPushButton("Revert")
        self._auto_revert_btn.setProperty("role", "link")
        self._auto_revert_btn.setVisible(False)
        self._auto_revert_btn.clicked.connect(self._revert_auto_on_off)
        auto_layout.addWidget(self._auto_revert_btn)
        auto_layout.addStretch(1)
        form.addRow("", auto_row)

        outer.addWidget(dock_box)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def load_state(self, state: dict) -> None:
        self._state = state
        self._loading = True
        try:
            idx = _nearest_brightness_index(state.get("dock_led_brightness"))
            self.brightness.set_value(str(BRIGHTNESS_OPTIONS[idx][0]))
            self.brightness.set_edited(False)
            self.auto_on_off.setChecked(bool(state.get("dock_auto_on_off")))
            self.auto_on_off.set_edited(False)
        finally:
            self._loading = False
        # Reset AFTER loading, not before -- a fresh load's own display
        # selection (however it landed) must never count as "the user
        # touched it." selectionChanged fires during the set_value() above
        # too, but _mark_brightness_touched() already ignores that under
        # the _loading guard; this reset also covers a stale True left
        # over from a previous load/edit cycle on this same widget.
        self._brightness_touched = False
        self._auto_on_off_touched = False
        self._loaded = {
            "dock_led_brightness": state.get("dock_led_brightness"),
            "dock_auto_on_off": state.get("dock_auto_on_off"),
        }
        self._brightness_was_label.setVisible(False)
        self._brightness_revert_btn.setVisible(False)
        self._auto_was_label.setVisible(False)
        self._auto_revert_btn.setVisible(False)

    def _mark_brightness_touched(self, *_args: object) -> None:
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): _on_edit() used to
        # unconditionally re-derive dock_led_brightness from
        # self.brightness's current value on ANY edit, including toggling
        # auto_on_off, which has nothing to do with brightness. The control
        # only offers five coarse stops (_nearest_brightness_index() picks
        # the closest one for DISPLAY), but pyg7/dock_settings.py and the
        # CLI accept any 0-100 value -- so an off-scale exact value (e.g.
        # 43%) got silently rounded to its nearest stop (e.g. 50%) the
        # moment an unrelated checkbox was toggled, even though the
        # control's own tooltip and _nearest_brightness_index()'s own
        # docstring both promise it stays exact "until this control is
        # actually edited." This flag is what actually keeps that promise:
        # only set when brightness's own signal fires for a real reason
        # (guarded by _loading, same as load()'s own guard elsewhere in
        # this codebase), not on every edit anywhere in this tab.
        if self._loading:
            return
        self._brightness_touched = True
        self.brightness.set_edited(True)
        observed = self._loaded.get("dock_led_brightness")
        self._brightness_was_label.setText("was Unknown" if observed is None else f"was {observed}%")
        self._brightness_was_label.setVisible(True)
        self._brightness_revert_btn.setVisible(True)
        self.fieldTouched.emit(("dock_led_brightness",), DOCK_FIELDS["dock_led_brightness"],
                                int(self.brightness.value()), _DOCK_PROFILE_PLACEHOLDER)

    def _mark_auto_on_off_touched(self, *_args: object) -> None:
        if self._loading:
            return
        self._auto_on_off_touched = True
        self.auto_on_off.set_edited(True)
        observed = self._loaded.get("dock_auto_on_off")
        self._auto_was_label.setText("was Unknown" if observed is None else f"was {'on' if observed else 'off'}")
        self._auto_was_label.setVisible(True)
        self._auto_revert_btn.setVisible(True)
        self.fieldTouched.emit(("dock_auto_on_off",), DOCK_FIELDS["dock_auto_on_off"],
                                self.auto_on_off.isChecked(), _DOCK_PROFILE_PLACEHOLDER)

    def _revert_brightness(self) -> None:
        if self._state is None:
            return
        observed = self._loaded.get("dock_led_brightness")
        idx = _nearest_brightness_index(observed)
        self._loading = True
        try:
            self.brightness.set_value(str(BRIGHTNESS_OPTIONS[idx][0]))
        finally:
            self._loading = False
        self._brightness_touched = False
        self.brightness.set_edited(False)
        self._brightness_was_label.setVisible(False)
        self._brightness_revert_btn.setVisible(False)
        self._state["dock_led_brightness"] = observed
        self.fieldReverted.emit(("dock_led_brightness",))
        self.changed.emit()

    def _revert_auto_on_off(self) -> None:
        if self._state is None:
            return
        observed = bool(self._loaded.get("dock_auto_on_off"))
        self._loading = True
        try:
            self.auto_on_off.setChecked(observed)
        finally:
            self._loading = False
        self._auto_on_off_touched = False
        self.auto_on_off.set_edited(False)
        self._auto_was_label.setVisible(False)
        self._auto_revert_btn.setVisible(False)
        self._state["dock_auto_on_off"] = observed
        self.fieldReverted.emit(("dock_auto_on_off",))
        self.changed.emit()

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        if self._brightness_touched:
            self._state["dock_led_brightness"] = int(self.brightness.value())
        self._state["dock_auto_on_off"] = self.auto_on_off.isChecked()
        self.changed.emit()
