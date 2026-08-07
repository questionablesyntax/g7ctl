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

from pyg7.buttons import KNOWN_BUTTON_IDS
from pyg7.session import shift_layer_addressable

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


log = logging.getLogger(__name__)

_NO_SHIFT_LAYER_TOOLTIP = (
    "g7ctl cannot reach this profile's Shift layer. Only one address on the "
    "controller reaches a Shift layer at all, and a write aimed at another "
    "profile's lands in Profile 1's Default layer instead -- so editing here "
    "would silently damage Profile 1. Shift bindings can be edited on "
    "Profile 1. Whether the other profiles have their own Shift layer that "
    "some other mechanism reaches is still being worked out."
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
        self._combos = {}  # (button_id, layer) -> QComboBox

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
        header.addWidget(self._muted_label("Default Layer"), 1)
        # Kept as an attribute: the Shift header gains a "(Profile 1 only)"
        # suffix on the profiles whose Shift layer we can't reach -- see load_state().
        self.shift_header = self._muted_label("Shift Layer")
        header.addWidget(self.shift_header, 1)
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

                rows.addWidget(row_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setProperty("role", "separator")
        rows.addWidget(separator)

        self.swap_stick_dpad = QCheckBox("Swap Left Stick and D-pad")
        self.swap_stick_dpad.toggled.connect(self._on_edit)
        self.swap_stick_dpad.setToolTip(
            "Implemented 2026-07-28 from a single captured write -- not yet "
            "confirmed with a real write+read round trip on hardware. See "
            "pyg7/dpad_options.py."
        )
        rows.addWidget(self.swap_stick_dpad)

        self.dpad_diagonal_lock = QCheckBox("D-Pad Diagonal Lock")
        self.dpad_diagonal_lock.toggled.connect(self._on_edit)
        rows.addWidget(self.dpad_diagonal_lock)

        rows.addStretch(1)
        scroll.setWidget(rows_widget)

    def load_state(self, state: dict) -> None:
        self._state = state
        # Only Profile 1 has a Shift layer the firmware can address. On the
        # others the column is disabled rather than hidden: an empty column
        # that silently disappears reads as a GUI fault, and this is a real
        # property of the hardware the user is entitled to see. Leaving it
        # editable was worse than cosmetic -- syncing one of those bindings
        # overwrote Profile 1's Default layer. See pyg7/session.py's
        # profile_layer_byte().
        shift_available = shift_layer_addressable(state.get("controller_slot") or 1)
        self.shift_header.setText("Shift Layer" if shift_available else "Shift Layer (Profile 1 only)")
        self.shift_header.setToolTip("" if shift_available else _NO_SHIFT_LAYER_TOOLTIP)

        # A state file exported by a version before the Shift-layer fix
        # carries bindings here that were never this profile's -- they are
        # Profile 1's Default layer, read back through the category the
        # firmware falls back on. They cannot be written (validate_state()
        # refuses them), and with the column disabled the user has no way to
        # clear them by hand, so a profile switch would dead-end at a sync
        # error. Dropping them is dropping a misrecording, not user intent.
        if not shift_available and state["buttons"].get("shift"):
            log.info("profile %s's Shift layer is unreachable; dropping %d binding(s) carried in from an "
                     "earlier read -- see pyg7.session.profile_layer_byte()",
                     state.get("controller_slot"), len(state["buttons"]["shift"]))
            state["buttons"]["shift"] = {}

        for (button_id, layer), combo in self._combos.items():
            value = state["buttons"].get(layer, {}).get(button_id)
            combo.blockSignals(True)
            select_by_data(combo, value)
            combo.blockSignals(False)
            if layer == "shift":
                combo.setEnabled(shift_available)
                combo.setToolTip("" if shift_available else _NO_SHIFT_LAYER_TOOLTIP)
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
        self._state["dpad_diagonal_lock"] = self.dpad_diagonal_lock.isChecked()
        self._state["swap_stick_dpad"] = self.swap_stick_dpad.isChecked()
        self.changed.emit()
