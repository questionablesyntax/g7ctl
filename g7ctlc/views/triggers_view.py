"""Triggers tab: Left/Right trigger hair-trigger mode/deadzone/curve.

Right Trigger shares the exact same shape as Left (see pyg7/triggers.py);
this view just instantiates the same widget twice.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets import CURVE_OPTIONS, CategorySideWidget, CurvePointsEditor, percent_spin

HAIR_TRIGGER_OPTIONS = [("off", "Off"), ("adaptive", "Adaptive"), ("fixed", "Fixed")]


class _TriggerSideWidget(CategorySideWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)

        box = QGroupBox("Trigger Settings")
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self.hair_trigger_mode = QComboBox()
        for value, label in HAIR_TRIGGER_OPTIONS:
            self.hair_trigger_mode.addItem(label, value)
        self.hair_trigger_mode.setToolTip(
            "Adaptive/Fixed shorten the trigger's travel before it registers "
            "as fully pressed -- useful for shooters. Off uses the full "
            "mechanical travel."
        )
        self.curve = QComboBox()
        self.curve.addItems(CURVE_OPTIONS)
        self.curve.setToolTip("The input-to-output response curve shape.")
        self.dz_initial = percent_spin()
        self.dz_initial.setToolTip(
            "Trigger movement below this percent of travel is ignored."
        )
        self.dz_max = percent_spin()
        self.dz_max.setToolTip(
            "Percent of travel at which the trigger reports full output."
        )
        self.adz_initial = percent_spin()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts the output "
            "curve near the resting position instead of ignoring it -- "
            "compensates for a trigger that has a real mechanical dead zone."
        )
        self.adz_max = percent_spin()
        self.adz_max.setToolTip(self.adz_initial.toolTip())

        form.addRow("Hair Trigger Mode", self.hair_trigger_mode)
        form.addRow("Curve preset", self.curve)
        self.curve_points = CurvePointsEditor()
        self.curve_points.changed.connect(self._emit_changed)
        self.curve_points_box = QGroupBox("Custom curve points (0-255, not %)")
        _pts_layout = QVBoxLayout(self.curve_points_box)
        _pts_layout.setContentsMargins(10, 8, 10, 8)
        _pts_layout.addWidget(self.curve_points)
        form.addRow("Deadzone (initial)", self.dz_initial)
        form.addRow("Deadzone (max)", self.dz_max)
        form.addRow("Anti-Deadzone (initial)", self.adz_initial)
        form.addRow("Anti-Deadzone (max)", self.adz_max)
        outer.addWidget(box)
        outer.addWidget(self.curve_points_box)
        outer.addStretch(1)

        self.hair_trigger_mode.currentIndexChanged.connect(self._emit_changed)
        self.curve.currentIndexChanged.connect(self._emit_changed)
        self.curve.currentIndexChanged.connect(self._update_curve_points_enabled)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max):
            w.valueChanged.connect(self._emit_changed)

    def _update_curve_points_enabled(self) -> None:
        self.curve_points.set_points_enabled(self.curve.currentText() == "custom")

    def _after_load(self) -> None:
        self._update_curve_points_enabled()

    def _load_fields(self, side_data: dict) -> None:
        idx = self.hair_trigger_mode.findData(side_data.get("hair_trigger_mode") or "off")
        # Index 0 is "off" -- the confirmed factory default.
        self.hair_trigger_mode.setCurrentIndex(idx if idx >= 0 else 0)
        curve = side_data.get("curve") or {}
        self.curve.setCurrentText(curve.get("preset") or "standard")
        self.curve_points.load(curve.get("points"))
        dz = side_data.get("deadzone") or {}
        self.dz_initial.setValue(dz.get("initial") if dz.get("initial") is not None else 0)
        self.dz_max.setValue(dz.get("max") if dz.get("max") is not None else 100)
        adz = side_data.get("anti_deadzone") or {}
        self.adz_initial.setValue(adz.get("initial") if adz.get("initial") is not None else 0)
        self.adz_max.setValue(adz.get("max") if adz.get("max") is not None else 100)

    def save_into(self, side_data: dict) -> None:
        side_data["hair_trigger_mode"] = self.hair_trigger_mode.currentData()
        # Merge, don't replace -- see sticks_view for why.
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.currentText()
        curve["points"] = self.curve_points.points() if self.curve.currentText() == "custom" else None
        side_data["deadzone"] = {"initial": self.dz_initial.value(), "max": self.dz_max.value()}
        side_data["anti_deadzone"] = {"initial": self.adz_initial.value(), "max": self.adz_max.value()}


class TriggersView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.sides = {"left": _TriggerSideWidget(), "right": _TriggerSideWidget()}
        for side, widget in self.sides.items():
            widget.changed.connect(self._on_edit)
            self.tabs.addTab(widget, f"{side.capitalize()} Trigger")
        layout.addWidget(self.tabs)

    def load_state(self, state: dict) -> None:
        self._state = state
        for side, widget in self.sides.items():
            widget.load(state["triggers"].setdefault(side, {}))

    def _on_edit(self) -> None:
        if self._state is None:
            return
        for side, widget in self.sides.items():
            widget.save_into(self._state["triggers"].setdefault(side, {}))
        self.changed.emit()
