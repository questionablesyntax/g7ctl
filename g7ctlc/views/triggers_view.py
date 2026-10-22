"""Triggers tab: Left/Right trigger hair-trigger mode/deadzone/curve.

Right Trigger shares the exact same shape as Left (see pyg7/triggers.py);
this view just instantiates the same widget twice.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7.curves import preset_points

from ..curve_editor import CurveEditor
from ..number_field import NumberField
from ..palette import DARK_PALETTE, Palette
from ..segmented_control import SegmentedControl
from ..widgets import CategorySideWidget, CurvePointsEditor

HAIR_TRIGGER_OPTIONS = [("off", "Off"), ("adaptive", "Adaptive"), ("fixed", "Fixed")]
_CURVE_SEGMENTS = [("standard", "Standard"), ("concave", "Concave"),
                   ("s_curve", "S-curve"), ("custom", "Custom")]


class _TriggerSideWidget(CategorySideWidget):
    def __init__(self, palette: Palette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)

        box = QGroupBox("Trigger Settings")
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self.hair_trigger_mode = SegmentedControl(HAIR_TRIGGER_OPTIONS)
        self.hair_trigger_mode.setToolTip(
            "Adaptive/Fixed shorten the trigger's travel before it registers "
            "as fully pressed -- useful for shooters. Off uses the full "
            "mechanical travel."
        )
        self.curve = SegmentedControl(_CURVE_SEGMENTS)
        self.curve.setToolTip("The input-to-output response curve shape.")
        # Real bug (see sticks_view.py's identical fix and its own longer
        # comment): unlike QComboBox, a fresh SegmentedControl is off-scale
        # until something calls set_value() -- curve.value() reaching
        # preset_points(None) as an unhandled exception inside a Qt signal
        # callback is fatal, not catchable. Signals blocked: this is a
        # display default, not a user edit or a load.
        self.hair_trigger_mode.blockSignals(True)
        self.hair_trigger_mode.set_value("off")
        self.hair_trigger_mode.blockSignals(False)
        self.curve.blockSignals(True)
        self.curve.set_value("standard")
        self.curve.blockSignals(False)
        self.dz_initial = NumberField.percent()
        self.dz_initial.setToolTip(
            "Trigger movement below this percent of travel is ignored."
        )
        self.dz_max = NumberField.percent()
        self.dz_max.setToolTip(
            "Percent of travel at which the trigger reports full output."
        )
        self.adz_initial = NumberField.percent()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts the output "
            "curve near the resting position instead of ignoring it -- "
            "compensates for a trigger that has a real mechanical dead zone."
        )
        self.adz_max = NumberField.percent()
        self.adz_max.setToolTip(self.adz_initial.toolTip())

        form.addRow("Hair Trigger Mode", self.hair_trigger_mode)
        form.addRow("Curve preset", self.curve)
        self.curve_points = CurvePointsEditor()
        self.curve_points.changed.connect(self._emit_changed)
        self.curve_points.changed.connect(self._sync_curve_editor)
        self.curve_points_box = QGroupBox("Custom curve points (0-255, not %)")
        _pts_layout = QVBoxLayout(self.curve_points_box)
        _pts_layout.setContentsMargins(10, 8, 10, 8)
        self._last_preset = "standard"
        self.curve_editor = CurveEditor(palette)
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
        outer.addWidget(box)
        outer.addWidget(self.curve_points_box)
        outer.addStretch(1)

        self.hair_trigger_mode.selectionChanged.connect(self._emit_changed)
        # Connection order matters here -- Qt fires slots in the order
        # they're connected on the same signal. _update_curve_points_enabled
        # must run BEFORE _emit_changed: switching to "custom" seeds
        # curve_points from the shown preset there, and _emit_changed flows
        # to save_into(), which reads curve_points immediately. Real bug,
        # found 2026-09-01, with these connected in the opposite order:
        # switching to "custom" on an unconfigured curve wrote the widget's
        # pre-seed value (all zeros) into state, one signal-fire before the
        # seed that was supposed to replace it -- silently wrong data synced
        # or exported, never shown on screen. See sticks_view.py, which had
        # the identical bug.
        self.curve.selectionChanged.connect(self._update_curve_points_enabled)
        self.curve.selectionChanged.connect(self._emit_changed)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max):
            w.valueChanged.connect(self._emit_changed)
            w.valueChanged.connect(self._sync_curve_editor)

    def _update_curve_points_enabled(self) -> None:
        custom = self.curve.value() == "custom"
        if custom and not self.curve_points.is_configured():
            # A profile whose curve block was never written has no points to
            # edit. Seed from whichever preset is showing, which is what
            # Nexus does -- switching preset -> Custom keeps the shape on
            # screen rather than starting from three points at the origin.
            seed = preset_points(self._last_preset) or preset_points("standard")
            self.curve_points.load(seed)
        if not custom:
            self._last_preset = self.curve.value()
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
        self.curve_editor.set_points_editable(self.curve.value() == "custom")

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


    def _after_load(self) -> None:
        self._update_curve_points_enabled()
        self._sync_curve_editor()

    def _load_fields(self, side_data: dict) -> None:
        # "off" is the confirmed factory default.
        self.hair_trigger_mode.set_value(side_data.get("hair_trigger_mode") or "off")
        curve = side_data.get("curve") or {}
        self.curve.set_value(curve.get("preset") or "standard")
        self.curve_points.load(curve.get("points"))
        dz = side_data.get("deadzone") or {}
        self.dz_initial.setValue(dz.get("initial") if dz.get("initial") is not None else 0)
        self.dz_max.setValue(dz.get("max") if dz.get("max") is not None else 100)
        adz = side_data.get("anti_deadzone") or {}
        self.adz_initial.setValue(adz.get("initial") if adz.get("initial") is not None else 0)
        self.adz_max.setValue(adz.get("max") if adz.get("max") is not None else 100)

    def save_into(self, side_data: dict) -> None:
        side_data["hair_trigger_mode"] = self.hair_trigger_mode.value()
        # Merge, don't replace -- see sticks_view for why.
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.value()
        curve["points"] = self.curve_points.points() if self.curve.value() == "custom" else None
        side_data["deadzone"] = {"initial": self.dz_initial.value(), "max": self.dz_max.value()}
        side_data["anti_deadzone"] = {"initial": self.adz_initial.value(), "max": self.adz_max.value()}


class TriggersView(QWidget):
    changed = pyqtSignal()

    def __init__(self, palette: Palette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.sides = {"left": _TriggerSideWidget(palette), "right": _TriggerSideWidget(palette)}
        for side, widget in self.sides.items():
            # Unlike SticksView (which this otherwise mirrors), this was
            # missing the QScrollArea wrap -- each side holds a CurveEditor
            # with a hardcoded 200px minimum height plus a full form above
            # it, uncapped. QTabWidget sizes its window to fit the LARGEST
            # tab page's minimum, not just whichever one is visible, so this
            # alone was dragging the whole main window's minimum height up
            # regardless of which tab a user was actually looking at.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            widget.changed.connect(self._on_edit)
            self.tabs.addTab(scroll, f"{side.capitalize()} Trigger")
        layout.addWidget(self.tabs)

    def set_palette(self, palette: Palette) -> None:
        """Repaints both sides' CurveEditor on a theme change -- see
        SticksView.set_palette()'s identical reasoning."""
        for widget in self.sides.values():
            widget.curve_editor.set_palette(palette)

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
