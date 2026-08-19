"""Motion tab: Aim/Tilt gyro settings.

Aim and Tilt are NOT symmetric the way Sticks' Left/Right are (see
pyg7/motion.py's module docstring): Tilt has no "Invert Roll" equivalent
at all, under any combination of Output/X-Axis Output Mode tested. So
`_MotionSideWidget` takes a `side` argument, unlike Sticks' identical
`_StickSideWidget` used twice -- the one place this tab's shape genuinely
differs per side, everything else (fields, layout) is the same widget
twice.

Custom curve point *editing* is deliberately not offered here -- unlike
Sticks/Triggers, pyg7.motion has no `curve_points` setting (dragging a
point was never captured on the wire for Motion, only the three named
presets and Custom's mode-select flag -- see pyg7/motion.py). The preset
picker still works; only the graphical point editor is absent.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets import (
    CURVE_OPTIONS,
    CategorySideWidget,
    make_keycode_combo,
    percent_spin,
    select_by_data,
)
from ..widgets import (
    set_row_visible as _set_row_visible,
)
from .sticks_view import OUTPUT_MODE_OPTIONS

X_AXIS_OUTPUT_MODE_OPTIONS = [("yaw", "Yaw"), ("yaw_roll", "Yaw + Roll")]
# Confirmed 2026-08-18 (owner, reading Nexus's own dropdown) -- see
# pyg7/motion.py's ACTIVATE_METHODS.
ACTIVATE_METHOD_OPTIONS = [
    ("off", "Off"), ("hold_to_activate", "Hold to Activate"),
    ("press_to_activate", "Press to Activate"), ("always_on", "Always On"),
]


class _MotionSideWidget(CategorySideWidget):
    def __init__(self, side: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.side = side
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        basic_box = QGroupBox("Basic")
        self.form = QFormLayout(basic_box)
        self.form.setVerticalSpacing(10)
        self.form.setHorizontalSpacing(14)

        self.activate_method = QComboBox()
        for value, label in ACTIVATE_METHOD_OPTIONS:
            self.activate_method.addItem(label, value)
        self.activate_method.setToolTip("How motion input gets activated.")
        self.activate_button = make_keycode_combo()
        self.activate_button.setToolTip("Which button, held or pressed, activates motion input.")
        self.x_axis_output_mode = QComboBox()
        for value, label in X_AXIS_OUTPUT_MODE_OPTIONS:
            self.x_axis_output_mode.addItem(label, value)
        self.x_axis_output_mode.setToolTip(
            "Yaw + Roll reveals an extra invert control below; plain Yaw does not."
        )
        self.curve = QComboBox()
        self.curve.addItems(CURVE_OPTIONS)
        self.curve.setToolTip(
            "The input-to-output response curve shape. Custom curves can be "
            "selected but their control points aren't editable here yet -- "
            "not captured on the wire for Motion (see pyg7/motion.py)."
        )
        self.dz_initial = percent_spin()
        self.dz_initial.setToolTip("Motion below this percent of the stick's travel range is ignored.")
        self.dz_max = percent_spin()
        self.dz_max.setToolTip("Percent of travel at which motion reports full output.")
        self.adz_initial = percent_spin()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts output near center instead of ignoring it."
        )
        self.adz_max = percent_spin()
        self.adz_max.setToolTip(self.adz_initial.toolTip())
        self.sensitivity_scale = percent_spin()
        self.sensitivity_scale.setToolTip("X/Y sensitivity scale, 0-100 (50 = balanced).")

        self.form.addRow("Activate Method", self.activate_method)
        self.form.addRow("Activate Button", self.activate_button)
        self.form.addRow("X-Axis Output Mode", self.x_axis_output_mode)
        self.form.addRow("Curve preset", self.curve)
        self.form.addRow("Deadzone (initial)", self.dz_initial)
        self.form.addRow("Deadzone (max)", self.dz_max)
        self.form.addRow("Anti-Deadzone (initial)", self.adz_initial)
        self.form.addRow("Anti-Deadzone (max)", self.adz_max)
        self.form.addRow("X/Y Sensitivity Scale", self.sensitivity_scale)

        self.invert_y = QCheckBox("Invert Y")
        self.invert_y.setToolTip("Reverses this sub-tab's Y axis.")
        self.form.addRow("", self.invert_y)
        self.invert_yaw = QCheckBox("Invert Yaw")
        self.invert_yaw.setToolTip(
            "Only shown by Nexus when X-Axis Output Mode is Yaw + Roll and "
            "Output is not Button Binds. Address confirmed on the wire; "
            "whether Nexus still calls this \"Invert Yaw\" on the Tilt "
            "sub-tab specifically is not (see pyg7/motion.py)."
        )
        self.form.addRow("", self.invert_yaw)
        if side == "aim":
            self.invert_roll = QCheckBox("Invert Roll")
            self.invert_roll.setToolTip(
                "Aim only -- Tilt has no equivalent control. Only shown by "
                "Nexus when X-Axis Output Mode is Yaw + Roll and Output is "
                "Button Binds."
            )
            self.form.addRow("", self.invert_roll)
        else:
            self.invert_roll = None
        outer.addWidget(basic_box)

        adv_box = QGroupBox("Output")
        self.adv_form = QFormLayout(adv_box)
        self.adv_form.setVerticalSpacing(10)
        self.adv_form.setHorizontalSpacing(14)
        self.output = QComboBox()
        for value, label in OUTPUT_MODE_OPTIONS:
            self.output.addItem(label, value)
        self.output.setToolTip("What this sub-tab's motion is translated to.")
        self.overlap_area = percent_spin()
        self.overlap_area.setToolTip(
            "How much the diagonal zones overlap between adjacent directional buttons (Button Binds only)."
        )
        self.adv_form.addRow("Output", self.output)
        self.adv_form.addRow("Overlap area (Button Binds only)", self.overlap_area)

        self.direction_combos = {}
        self.direction_box = QGroupBox("Direction Bindings (Button Binds only)")
        dir_form = QFormLayout(self.direction_box)
        dir_form.setVerticalSpacing(10)
        dir_form.setHorizontalSpacing(14)
        # No "ring" zone here, unlike Sticks' direction_bindings -- Motion
        # has no stick click to bind (see pyg7/motion.py).
        for zone in ("up", "down", "left", "right"):
            combo = make_keycode_combo()
            combo.setToolTip(f"Keycode sent while motion is held toward {zone.capitalize()} (Button Binds only).")
            combo.currentIndexChanged.connect(self._emit_changed)
            dir_form.addRow(zone.capitalize(), combo)
            self.direction_combos[zone] = combo
        self.adv_form.addRow(self.direction_box)
        outer.addWidget(adv_box)
        outer.addStretch(1)

        for w in (self.activate_method, self.activate_button, self.x_axis_output_mode, self.curve):
            w.currentIndexChanged.connect(self._emit_changed)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max,
                  self.sensitivity_scale, self.overlap_area):
            w.valueChanged.connect(self._emit_changed)
        for w in (self.invert_y, self.invert_yaw):
            w.toggled.connect(self._emit_changed)
        if self.invert_roll is not None:
            self.invert_roll.toggled.connect(self._emit_changed)
        self.output.currentIndexChanged.connect(self._update_visibility)
        self.output.currentIndexChanged.connect(self._emit_changed)
        self.x_axis_output_mode.currentIndexChanged.connect(self._update_visibility)

    def _update_visibility(self) -> None:
        directional = self.output.currentData() == "directional"
        yaw_roll = self.x_axis_output_mode.currentData() == "yaw_roll"
        _set_row_visible(self.adv_form, self.overlap_area, directional)
        self.direction_box.setVisible(directional)
        _set_row_visible(self.form, self.invert_yaw, yaw_roll and not directional)
        if self.invert_roll is not None:
            _set_row_visible(self.form, self.invert_roll, yaw_roll and directional)

    def _load_fields(self, side_data: dict) -> None:
        am_idx = self.activate_method.findData(side_data.get("activate_method") or "off")
        self.activate_method.setCurrentIndex(am_idx if am_idx >= 0 else 0)
        select_by_data(self.activate_button, side_data.get("activate_button"))
        idx = self.x_axis_output_mode.findData(side_data.get("x_axis_output_mode") or "yaw")
        self.x_axis_output_mode.setCurrentIndex(idx if idx >= 0 else 0)
        curve = side_data.get("curve") or {}
        self.curve.setCurrentText(curve.get("preset") or "standard")
        dz = side_data.get("deadzone") or {}
        self.dz_initial.setValue(dz.get("initial") if dz.get("initial") is not None else 0)
        self.dz_max.setValue(dz.get("max") if dz.get("max") is not None else 100)
        adz = side_data.get("anti_deadzone") or {}
        self.adz_initial.setValue(adz.get("initial") if adz.get("initial") is not None else 0)
        self.adz_max.setValue(adz.get("max") if adz.get("max") is not None else 100)
        self.sensitivity_scale.setValue(
            side_data.get("sensitivity_scale") if side_data.get("sensitivity_scale") is not None else 50)
        self.invert_y.setChecked(bool(side_data.get("invert_y")))
        self.invert_yaw.setChecked(bool(side_data.get("invert_yaw")))
        if self.invert_roll is not None:
            self.invert_roll.setChecked(bool(side_data.get("invert_roll")))
        out_idx = self.output.findData(side_data.get("output") or "left_stick")
        self.output.setCurrentIndex(out_idx if out_idx >= 0 else 0)
        self.overlap_area.setValue(
            side_data.get("overlap_area") if side_data.get("overlap_area") is not None else 50)
        db = side_data.get("direction_bindings") or {}
        for zone, combo in self.direction_combos.items():
            select_by_data(combo, db.get(zone))

    def _after_load(self) -> None:
        self._update_visibility()

    def save_into(self, side_data: dict) -> None:
        side_data["activate_method"] = self.activate_method.currentData()
        side_data["activate_button"] = self.activate_button.currentData()
        side_data["x_axis_output_mode"] = self.x_axis_output_mode.currentData()
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.currentText()
        # Points are never written for Motion (no curve_points setting in
        # pyg7.motion yet) -- always None here, unlike Sticks, so a fresh
        # export doesn't claim editable points that don't exist.
        curve["points"] = None
        side_data["deadzone"] = {"initial": self.dz_initial.value(), "max": self.dz_max.value()}
        side_data["anti_deadzone"] = {"initial": self.adz_initial.value(), "max": self.adz_max.value()}
        side_data["invert_y"] = self.invert_y.isChecked()
        side_data["invert_yaw"] = self.invert_yaw.isChecked()
        side_data["invert_roll"] = self.invert_roll.isChecked() if self.invert_roll is not None else None
        side_data["sensitivity_scale"] = self.sensitivity_scale.value()
        side_data["output"] = self.output.currentData()
        side_data["overlap_area"] = self.overlap_area.value()
        if side_data["output"] == "directional":
            side_data["direction_bindings"] = {
                zone: combo.currentData() for zone, combo in self.direction_combos.items()
            }


class MotionView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.sides = {"aim": _MotionSideWidget("aim"), "tilt": _MotionSideWidget("tilt")}
        for side, widget in self.sides.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            widget.changed.connect(self._on_edit)
            self.tabs.addTab(scroll, side.capitalize())
        layout.addWidget(self.tabs)

    def load_state(self, state: dict) -> None:
        self._state = state
        # Additive section (see pyg7/state.py's validate_state()) -- an
        # older imported state dict may not have "motion" at all.
        motion = state.setdefault("motion", {"aim": {}, "tilt": {}})
        for side, widget in self.sides.items():
            widget.load(motion.setdefault(side, {}))

    def _on_edit(self) -> None:
        if self._state is None:
            return
        motion = self._state.setdefault("motion", {"aim": {}, "tilt": {}})
        for side, widget in self.sides.items():
            widget.save_into(motion.setdefault(side, {}))
        self.changed.emit()
