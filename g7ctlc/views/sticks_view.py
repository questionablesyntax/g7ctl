"""Sticks tab: Left/Right stick trajectory/curve/deadzone/advanced-mapping.

Right Stick shares the exact same shape as Left (see pyg7/sticks.py);
this view just instantiates the same widget twice.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7.curves import preset_points

from ..curve_editor import CurveEditor
from ..widgets import (
    CURVE_OPTIONS,
    CategorySideWidget,
    CurvePointsEditor,
    make_keycode_combo,
    percent_spin,
    select_by_data,
)
from ..widgets import (
    set_row_visible as _set_row_visible,
)

TRAJECTORY_OPTIONS = ["circle", "raw"]
OUTPUT_MODE_OPTIONS = [
    ("left_stick", "Left Stick"), ("right_stick", "Right Stick"),
    ("directional", "Directional Buttons"), ("mouse", "Simulate Mouse"),
]


class _StickSideWidget(CategorySideWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        basic_box = QGroupBox("Basic")
        form = QFormLayout(basic_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        self.trajectory = QComboBox()
        self.trajectory.addItems(TRAJECTORY_OPTIONS)
        self.trajectory.setToolTip(
            "Circle: normalizes diagonal stick travel to a circular range. "
            "Raw: passes the physical X/Y axis values through unshaped."
        )
        self.curve = QComboBox()
        self.curve.addItems(CURVE_OPTIONS)
        self.curve.setToolTip("The input-to-output response curve shape.")
        self.dz_initial = percent_spin()
        self.dz_initial.setToolTip(
            "Stick movement below this percent of travel from center is ignored."
        )
        self.dz_max = percent_spin()
        self.dz_max.setToolTip(
            "Percent of travel from center at which the stick reports full output."
        )
        self.adz_initial = percent_spin()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts the output "
            "curve near center instead of ignoring it -- compensates for a "
            "stick that has a real mechanical dead zone."
        )
        self.adz_max = percent_spin()
        self.adz_max.setToolTip(self.adz_initial.toolTip())
        self.resolution_bits = QSpinBox()
        self.resolution_bits.setRange(8, 12)
        self.resolution_bits.setToolTip(
            "ADC resolution the stick reports at, 8-12 bits. Lower values "
            "coarsen precision."
        )
        form.addRow("Trajectory", self.trajectory)
        form.addRow("Curve preset", self.curve)
        self.curve_points = CurvePointsEditor()
        self.curve_points.changed.connect(self._emit_changed)
        self.curve_points.changed.connect(self._sync_curve_editor)
        # Own group: these are 0-255 while every field around them is a
        # percentage, and they only apply to a Custom curve.
        self.curve_points_box = QGroupBox("Custom curve points (0-255, not %)")
        _pts_layout = QVBoxLayout(self.curve_points_box)
        _pts_layout.setContentsMargins(10, 8, 10, 8)
        self._last_preset = "standard"
        self.curve_editor = CurveEditor()
        self.curve_editor.setToolTip(
            "Drag the five handles. The outer two are the Deadzone and "
            "Anti-Deadzone values (0-100%); the inner three are the curve's "
            "control points (0-255, positioned within the span the "
            "endpoints define).\n\n"
            "Straight segments between handles is what GameSir Nexus draws "
            "for a Custom curve. How the controller itself shapes the "
            "response between control points is not known."
        )
        self.curve_editor.points_changed.connect(self._on_editor_points)
        self.curve_editor.endpoints_changed.connect(self._on_editor_endpoints)
        _pts_layout.addWidget(self.curve_editor, 1)
        _pts_layout.addWidget(self.curve_points)
        form.addRow("Deadzone (initial)", self.dz_initial)
        form.addRow("Deadzone (max)", self.dz_max)
        form.addRow("Anti-Deadzone (initial)", self.adz_initial)
        form.addRow("Anti-Deadzone (max)", self.adz_max)
        form.addRow("Resolution (bits)", self.resolution_bits)
        outer.addWidget(basic_box)
        outer.addWidget(self.curve_points_box)

        adv_box = QGroupBox("Advanced Mapping")
        self.adv_form = QFormLayout(adv_box)
        self.adv_form.setVerticalSpacing(10)
        self.adv_form.setHorizontalSpacing(14)
        self.output_mode = QComboBox()
        for value, label in OUTPUT_MODE_OPTIONS:
            self.output_mode.addItem(label, value)
        self.output_mode.setToolTip(
            "What this stick emulates: itself, the other stick, D-pad-style "
            "directional buttons, or mouse movement."
        )
        self.invert_x = QCheckBox("Invert X")
        self.invert_x.setToolTip("Reverses this stick's X axis.")
        self.invert_y = QCheckBox("Invert Y")
        self.invert_y.setToolTip("Reverses this stick's Y axis.")
        self.sensitivity = percent_spin()
        self.sensitivity.setToolTip("X/Y sensitivity scale, 0-100 (50 = balanced).")
        self.overlap_area = percent_spin()
        self.overlap_area.setToolTip(
            "How much the diagonal zones overlap between adjacent directional "
            "buttons (Directional output mode only)."
        )
        self.dpi = percent_spin()
        self.dpi.setToolTip("Mouse movement speed (Simulate Mouse output mode only).")
        self.adv_form.addRow("Output mode", self.output_mode)
        self.adv_form.addRow("", self.invert_x)
        self.adv_form.addRow("", self.invert_y)
        self.adv_form.addRow("Sensitivity", self.sensitivity)
        self.adv_form.addRow("Overlap area (Directional only)", self.overlap_area)
        self.adv_form.addRow("DPI (Simulate Mouse only)", self.dpi)

        self.direction_combos = {}
        self.direction_box = QGroupBox("Direction Bindings (Directional Buttons only)")
        dir_form = QFormLayout(self.direction_box)
        dir_form.setVerticalSpacing(10)
        dir_form.setHorizontalSpacing(14)
        for zone in ("up", "down", "left", "right", "ring"):
            combo = make_keycode_combo()
            combo.setToolTip(
                f"Keycode sent while the stick is held toward {zone.capitalize()} "
                "(Directional output mode only)."
            )
            combo.currentIndexChanged.connect(self._emit_changed)
            dir_form.addRow(zone.capitalize(), combo)
            self.direction_combos[zone] = combo
        self.adv_form.addRow(self.direction_box)
        outer.addWidget(adv_box)
        outer.addStretch(1)

        self.trajectory.currentIndexChanged.connect(self._emit_changed)
        # Connection order matters here -- Qt fires slots in the order
        # they're connected on the same signal. _update_curve_points_enabled
        # must run BEFORE _emit_changed: switching to "custom" seeds
        # curve_points from the shown preset there, and _emit_changed flows
        # to save_into(), which reads curve_points immediately. Real bug,
        # found 2026-09-01, with these connected in the opposite order:
        # switching to "custom" on an unconfigured curve wrote the widget's
        # pre-seed value (all zeros) into state, one signal-fire before the
        # seed that was supposed to replace it -- silently wrong data synced
        # or exported, never shown on screen.
        self.curve.currentIndexChanged.connect(self._update_curve_points_enabled)
        self.curve.currentIndexChanged.connect(self._emit_changed)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max,
                  self.resolution_bits, self.sensitivity, self.overlap_area, self.dpi):
            w.valueChanged.connect(self._emit_changed)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max):
            w.valueChanged.connect(self._sync_curve_editor)
        for w in (self.invert_x, self.invert_y):
            w.toggled.connect(self._emit_changed)
        self.output_mode.currentIndexChanged.connect(self._update_visibility)
        self.output_mode.currentIndexChanged.connect(self._emit_changed)

    def _update_curve_points_enabled(self) -> None:
        custom = self.curve.currentText() == "custom"
        if custom and not self.curve_points.is_configured():
            # A profile whose curve block was never written has no points to
            # edit. Seed from whichever preset is showing, which is what
            # Nexus does -- switching preset -> Custom keeps the shape on
            # screen rather than starting from three points at the origin.
            seed = preset_points(self._last_preset) or preset_points("standard")
            self.curve_points.load(seed)
        if not custom:
            self._last_preset = self.curve.currentText()
        self.curve_points.set_points_enabled(custom)
        self._sync_curve_editor()
    # --- graphical curve editor ------------------------------------------
    #
    # The editor and the numeric fields are two views of the same four
    # registers plus three points, so each has to update the other without
    # looping. Both funnel through the existing _loading guard that load()
    # already uses.

    def _sync_curve_editor(self) -> None:
        self.curve_editor.set_curve(
            self.dz_initial.value(), self.dz_max.value(),
            self.adz_initial.value(), self.adz_max.value(),
            self.curve_points.points())
        self.curve_editor.set_points_editable(self.curve.currentText() == "custom")

    def _on_editor_points(self, points: list) -> None:
        self.curve_points.load(points)
        self._emit_changed()

    def _on_editor_endpoints(self, dz_i: int, dz_m: int, adz_i: int, adz_m: int) -> None:
        for widget, value in ((self.dz_initial, dz_i), (self.dz_max, dz_m),
                              (self.adz_initial, adz_i), (self.adz_max, adz_m)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._emit_changed()


    def _update_visibility(self) -> None:
        self._update_curve_points_enabled()
        mode = self.output_mode.currentData()
        _set_row_visible(self.adv_form, self.sensitivity, mode in ("left_stick", "right_stick", "mouse"))
        _set_row_visible(self.adv_form, self.overlap_area, mode == "directional")
        _set_row_visible(self.adv_form, self.dpi, mode == "mouse")
        self.direction_box.setVisible(mode == "directional")

    def _load_fields(self, side_data: dict) -> None:
        self.trajectory.setCurrentText(side_data.get("trajectory") or "circle")
        curve = side_data.get("curve") or {}
        self.curve.setCurrentText(curve.get("preset") or "standard")
        self.curve_points.load(curve.get("points"))
        dz = side_data.get("deadzone") or {}
        self.dz_initial.setValue(dz.get("initial") if dz.get("initial") is not None else 0)
        self.dz_max.setValue(dz.get("max") if dz.get("max") is not None else 100)
        adz = side_data.get("anti_deadzone") or {}
        self.adz_initial.setValue(adz.get("initial") if adz.get("initial") is not None else 0)
        self.adz_max.setValue(adz.get("max") if adz.get("max") is not None else 100)
        self.resolution_bits.setValue(side_data.get("resolution_bits") or 12)

        am = side_data.get("advanced_mapping") or {}
        idx = self.output_mode.findData(am.get("output_mode") or "left_stick")
        # Index 0 is "left_stick" -- the confirmed factory default.
        self.output_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.invert_x.setChecked(bool(am.get("invert_x")))
        self.invert_y.setChecked(bool(am.get("invert_y")))
        self.sensitivity.setValue(am.get("sensitivity") if am.get("sensitivity") is not None else 50)
        self.overlap_area.setValue(am.get("overlap_area") if am.get("overlap_area") is not None else 50)
        self.dpi.setValue(am.get("dpi") if am.get("dpi") is not None else 50)
        db = am.get("direction_bindings") or {}
        for zone, combo in self.direction_combos.items():
            select_by_data(combo, db.get(zone))

    def _after_load(self) -> None:
        self._update_visibility()
        self._sync_curve_editor()

    def save_into(self, side_data: dict) -> None:
        side_data["trajectory"] = self.trajectory.currentText()
        # Merge rather than replace: a plain assignment here dropped the
        # "points" a device read had brought back, so any unrelated edit
        # silently discarded them.
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.currentText()
        curve["points"] = self.curve_points.points() if self.curve.currentText() == "custom" else None
        side_data["deadzone"] = {"initial": self.dz_initial.value(), "max": self.dz_max.value()}
        side_data["anti_deadzone"] = {"initial": self.adz_initial.value(), "max": self.adz_max.value()}
        side_data["resolution_bits"] = self.resolution_bits.value()
        am = side_data.setdefault("advanced_mapping", {})
        am["output_mode"] = self.output_mode.currentData()
        am["invert_x"] = self.invert_x.isChecked()
        am["invert_y"] = self.invert_y.isChecked()
        am["sensitivity"] = self.sensitivity.value()
        am["overlap_area"] = self.overlap_area.value()
        am["dpi"] = self.dpi.value()
        if am["output_mode"] == "directional":
            am["direction_bindings"] = {
                zone: combo.currentData() for zone, combo in self.direction_combos.items()
            }


class SticksView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.sides = {"left": _StickSideWidget(), "right": _StickSideWidget()}
        for side, widget in self.sides.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            widget.changed.connect(self._on_edit)
            self.tabs.addTab(scroll, f"{side.capitalize()} Stick")
        layout.addWidget(self.tabs)

    def load_state(self, state: dict) -> None:
        self._state = state
        for side, widget in self.sides.items():
            widget.load(state["sticks"].setdefault(side, {}))

    def _on_edit(self) -> None:
        if self._state is None:
            return
        for side, widget in self.sides.items():
            widget.save_into(self._state["sticks"].setdefault(side, {}))
        self.changed.emit()
