"""Buttons tab: per-button Default/Shift-layer keycode assignment.

Row order groups controls the way they're physically arranged on the
controller (face buttons, stick clicks, shoulder/paddle pairs, trigger/
paddle pairs, D-pad, misc) rather than KNOWN_BUTTON_IDS's declaration
order -- a flat alphabetical-ish list was the single biggest usability
complaint on the first pass. Short-term measure; the eventual goal is a
diagram layout closer to GameSir Nexus's own controller-image UI.
"""
import logging
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyg7.buttons import BUTTON_TABLE_SLOTS, KNOWN_BUTTON_IDS

from ..widgets import make_keycode_combo, select_by_data

_BUTTON_LABELS = {
    "share": "Share", "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "l3": "L3 (stick click)", "r3": "R3 (stick click)",
    "view": "View", "menu": "Menu", "l4": "L4", "r4": "R4",
    "l5": "L5", "r5": "R5",
    "dpad_up": "D-Pad Up", "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left", "dpad_right": "D-Pad Right",
}

_BUTTON_GROUPS = [
    ("a", "b", "x", "y"),
    ("r3", "l3"),
    ("rb", "lb", "r5", "l5"),
    ("rt", "lt", "l4", "r4"),
    ("dpad_up", "dpad_down", "dpad_left", "dpad_right"),
    ("view", "menu", "share"),
]

_NAME_COL_WIDTH = 140
_CONTINUOUS_COL_WIDTH = 90

_CONTINUOUS_TOOLTIP = (
    "Continuous Trigger makes the button latch: press once and it stays "
    "held until you press it again.\n\n"
    "It is not turbo/rapid-fire -- the button does not repeat. That is also "
    "why there is no rate setting.\n\n"
    "Independent of the binding: it doesn't change what the button sends, "
    "only how long it stays sent.\n\n"
    "Profile-scoped, and stored inside the button's own record, so it "
    "applies to the Default layer only."
)

# LT/RT are the exception: they have no record in the button table (their
# keycode is a lone byte inside the Triggers category's data), so there is
# no Continuous Trigger byte to derive for them -- see
# pyg7.buttons.continuous_trigger_offset(). They get a blank spacer instead
# of a checkbox, rather than a checkbox that silently does nothing.
_CONTINUOUS_UNSUPPORTED_TOOLTIP = (
    "The triggers have no Continuous Trigger setting -- they're stored differently "
    "from the other buttons, and whether the hardware supports it for them "
    "at all is unknown."
)


log = logging.getLogger(__name__)

_SHARED_SHIFT_TOOLTIP = (
    "The controller has ONE Shift layer, shared by all four profiles -- "
    "editing it here changes it for every profile, not just this one. "
    "GameSir Nexus shows a Shift section under each profile tab, which makes "
    "it look per-profile, but the same bindings appear under all of them."
)


class ButtonsView(QWidget):
    changed = pyqtSignal()

    @staticmethod
    def _muted_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "muted")
        return label

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        self._layer = "default"
        self._combos = {}  # (button_id, layer) -> QComboBox
        self._continuous = {}  # button_id -> QCheckBox (Default layer only)
        self._continuous_spacers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        rows_widget = QWidget()
        rows = QVBoxLayout(rows_widget)
        rows.setContentsMargins(10, 8, 10, 8)
        rows.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 8)
        name_header = QLabel("Button")
        name_header.setProperty("role", "muted")
        name_header.setFixedWidth(_NAME_COL_WIDTH)
        header.addWidget(name_header)
        # One binding column. Which layer it edits is set by set_layer():
        # the Shift layer is device-global and lives behind its own entry in
        # the profile selector, not beside a per-profile column.
        self.column_header = self._muted_label("Default Layer")
        header.addWidget(self.column_header, 1)
        self.continuous_header = self._muted_label("Continuous Trigger")
        self.continuous_header.setFixedWidth(_CONTINUOUS_COL_WIDTH)
        self.continuous_header.setToolTip(_CONTINUOUS_TOOLTIP)
        header.addWidget(self.continuous_header)
        rows.addLayout(header)

        # Defensive check: a button present in KNOWN_BUTTON_IDS but missing
        # from _BUTTON_GROUPS would silently vanish from the GUI, exactly
        # the L5/R5 bug from before this list existed.
        grouped = {b for group in _BUTTON_GROUPS for b in group}
        missing = [b for b in KNOWN_BUTTON_IDS if b not in grouped]
        assert not missing, f"buttons missing from _BUTTON_GROUPS: {missing}"

        for group_index, group in enumerate(_BUTTON_GROUPS):
            if group_index > 0:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setProperty("role", "separator")
                rows.addWidget(separator)

            for button_id in group:
                row_widget = QWidget()
                row = QHBoxLayout(row_widget)
                row.setContentsMargins(8, 6, 8, 6)

                name_label = QLabel(_BUTTON_LABELS.get(button_id, button_id))
                name_label.setFixedWidth(_NAME_COL_WIDTH)
                row.addWidget(name_label)

                for layer in ("default", "shift"):
                    combo = make_keycode_combo()
                    combo.currentIndexChanged.connect(self._on_edit)
                    row.addWidget(combo, 1)
                    self._combos[(button_id, layer)] = combo

                if button_id in BUTTON_TABLE_SLOTS:
                    check = QCheckBox()
                    check.setToolTip(_CONTINUOUS_TOOLTIP)
                    check.toggled.connect(self._on_edit)
                    check.setFixedWidth(_CONTINUOUS_COL_WIDTH)
                    row.addWidget(check)
                    self._continuous[button_id] = check
                else:
                    spacer = QLabel()
                    spacer.setFixedWidth(_CONTINUOUS_COL_WIDTH)
                    spacer.setToolTip(_CONTINUOUS_UNSUPPORTED_TOOLTIP)
                    row.addWidget(spacer)
                    self._continuous_spacers.append(spacer)

                rows.addWidget(row_widget)

        self.options_separator = QFrame()
        self.options_separator.setFrameShape(QFrame.Shape.HLine)
        self.options_separator.setProperty("role", "separator")
        rows.addWidget(self.options_separator)

        self.swap_stick_dpad = QCheckBox("Swap Left Stick and D-pad")
        self.swap_stick_dpad.toggled.connect(self._on_edit)
        self.swap_stick_dpad.setToolTip(
            "Hardware-verified 2026-07-29: a full-blob diff of a real ON then "
            "OFF write changed exactly the two intended bytes each time, and "
            "the OFF blob came back byte-identical to the pre-write baseline. "
            "See pyg7/dpad_options.py."
        )
        rows.addWidget(self.swap_stick_dpad)

        self.dpad_diagonal_lock = QCheckBox("D-Pad Diagonal Lock")
        self.dpad_diagonal_lock.toggled.connect(self._on_edit)
        rows.addWidget(self.dpad_diagonal_lock)

        rows.addStretch(1)
        scroll.setWidget(rows_widget)

        # Apply the starting layer rather than trusting the caller to.
        # Both layers' combos are built above and are visible by default, so
        # without this the Shift column sits next to the Default one until
        # something calls set_layer() -- which MainWindow only does on a
        # profile *change*. That put a shared, device-global column inside
        # the per-profile screen on every fresh launch, showing exactly the
        # thing the Shift-as-its-own-screen change existed to stop showing.
        self.set_layer(self._layer)

    def set_layer(self, layer: str) -> None:
        """Show the Default layer's bindings, or the shared Shift layer's.

        Both sets of combos stay built and populated -- only their visibility
        changes -- so switching views never drops a value that _on_edit()
        would then sweep out of the state dict.
        """
        self._layer = layer
        shift = layer == "shift"
        self.column_header.setText(
            "Shift Layer (shared by all profiles)" if shift else "Default Layer")
        self.column_header.setToolTip(_SHARED_SHIFT_TOOLTIP if shift else "")
        for (_button_id, combo_layer), combo in self._combos.items():
            combo.setVisible(combo_layer == layer)
        # D-pad options are profile-scoped, so they have no meaning on the
        # Shift screen -- and no way to be written there either.
        self.swap_stick_dpad.setVisible(not shift)
        self.dpad_diagonal_lock.setVisible(not shift)
        self.options_separator.setVisible(not shift)
        # Continuous Trigger lives in the per-profile button record, so it has no
        # meaning on the device-global Shift screen -- and no way to be
        # written there either, same as the D-pad options above.
        self.continuous_header.setVisible(not shift)
        for check in self._continuous.values():
            check.setVisible(not shift)
        for spacer in self._continuous_spacers:
            spacer.setVisible(not shift)

    def load_state(self, state: dict) -> None:
        self._state = state
        for (button_id, layer), combo in self._combos.items():
            value = state["buttons"].get(layer, {}).get(button_id)
            combo.blockSignals(True)
            select_by_data(combo, value)
            combo.blockSignals(False)
            if layer == "shift":
                combo.setToolTip(_SHARED_SHIFT_TOOLTIP)
        continuous = state.get("continuous_trigger") or {}
        for button_id, check in self._continuous.items():
            check.blockSignals(True)
            check.setChecked(bool(continuous.get(button_id)))
            check.blockSignals(False)
        self.swap_stick_dpad.blockSignals(True)
        self.swap_stick_dpad.setChecked(bool(state.get("swap_stick_dpad")))
        self.swap_stick_dpad.blockSignals(False)
        self.dpad_diagonal_lock.blockSignals(True)
        self.dpad_diagonal_lock.setChecked(bool(state.get("dpad_diagonal_lock")))
        self.dpad_diagonal_lock.blockSignals(False)

    def _on_edit(self, *_: object) -> None:
        if self._state is None:
            return
        for (button_id, layer), combo in self._combos.items():
            value = combo.currentData()
            layer_dict = self._state["buttons"].setdefault(layer, {})
            if value in (None, "__header__"):
                layer_dict.pop(button_id, None)
            else:
                layer_dict[button_id] = value
        continuous = self._state.setdefault("continuous_trigger", {})
        for button_id, check in self._continuous.items():
            continuous[button_id] = check.isChecked()
        self._state["dpad_diagonal_lock"] = self.dpad_diagonal_lock.isChecked()
        self._state["swap_stick_dpad"] = self.swap_stick_dpad.isChecked()
        self.changed.emit()
