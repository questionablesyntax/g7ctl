"""Buttons tab: per-button Default/Shift-layer keycode assignment.

Row order groups controls the way they're physically arranged on the
controller (face buttons, stick clicks, shoulder/paddle pairs, trigger/
paddle pairs, D-pad, misc) rather than KNOWN_BUTTON_IDS's declaration
order -- a flat alphabetical-ish list was the single biggest usability
complaint on the first pass. Short-term measure; the eventual goal is a
diagram layout closer to GameSir Nexus's own controller-image UI.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from pyg7.buttons import KNOWN_BUTTON_IDS
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


class ButtonsView(QWidget):
    changed = pyqtSignal()

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
        for text in ("Default Layer", "Shift Layer"):
            label = QLabel(text)
            label.setProperty("role", "muted")
            header.addWidget(label, 1)
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
        for (button_id, layer), combo in self._combos.items():
            value = state["buttons"].get(layer, {}).get(button_id)
            combo.blockSignals(True)
            select_by_data(combo, value)
            combo.blockSignals(False)
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
