"""Sticks tab: Left/Right stick trajectory/curve/deadzone/advanced-mapping.

Right Stick shares the exact same shape as Left (see pyg7/sticks.py);
this view just instantiates the same widget twice.

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): the fourth
S6 slice onto the real per-field draft model, same per-side/per-profile
shape as triggers_view.py. Migrated: all 13 of
`pyg7.field_spec.STICK_FIELDS`' "simple" settings (`trajectory`, `curve`
preset, `deadzone_initial/max`, `anti_deadzone_initial/max`,
`resolution_bits`, `output_mode`, `invert_x`, `invert_y`, `sensitivity`,
`overlap_area`, `dpi`). **Deliberately not migrated**: `curve_points`
(same reasoning as Triggers' identical field) and `direction_bindings`
(the five-zone Directional Buttons binding -- like `curve_points`, it's
built from several widgets (`direction_combos`) combined into one
comma-joined `FieldSpec` value, not one widget's own signal, and is only
relevant in one Output mode out of four; a real design question
deserving its own pass, same reasoning as every other deferred
multi-widget field this track has left alone). Still writes through the
old whole-side Sync Now path only.

Output mode's `_output_mode_configured` guard (see its own long comment
below) predates this slice and is unchanged by it: a touch on
`output_mode` always carries a concrete value (the combo always has one
selected), never `Intent.PRESERVE` -- that flag only matters to the OLD
whole-side `save_into()` path, deciding whether THIS write should send a
real value or leave the field undeclared. `_revert_setting("output_mode")`
restores both the display and that flag together, since reverting to
"never configured" means exactly that again.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7.buttons import KNOWN_KEYCODES
from pyg7.curves import preset_points
from pyg7.field_spec import STICK_FIELDS

from ..binding_field import BindingField
from ..checkbox import Checkbox
from ..curve_editor import CurveEditor
from ..keycode_picker import KeycodePicker
from ..number_field import NumberField
from ..palette import DARK_PALETTE, Palette
from ..segmented_control import SegmentedControl
from ..widgets import (
    CategorySideWidget,
    CurvePointsEditor,
)
from ..widgets import (
    set_row_visible as _set_row_visible,
)

_TRAJECTORY_SEGMENTS = [("circle", "Circle"), ("raw", "Raw")]
_CURVE_SEGMENTS = [("standard", "Standard"), ("concave", "Concave"),
                   ("s_curve", "S-curve"), ("custom", "Custom")]

OUTPUT_MODE_OPTIONS = [
    ("left_stick", "Left Stick"), ("right_stick", "Right Stick"),
    ("directional", "Directional Buttons"), ("mouse", "Simulate Mouse"),
]

# Mirrors field_spec.py's own `_STICK_SIMPLE_SETTINGS` path tuples
# exactly (minus the leading `("sticks", side)`, which this view
# prepends itself) -- same duplication reasoning as triggers_view.py's
# identical table.
_SIMPLE_SETTING_PATHS = {
    "trajectory": ("trajectory",),
    "curve": ("curve", "preset"),
    "deadzone_initial": ("deadzone", "initial"),
    "deadzone_max": ("deadzone", "max"),
    "anti_deadzone_initial": ("anti_deadzone", "initial"),
    "anti_deadzone_max": ("anti_deadzone", "max"),
    "resolution_bits": ("resolution_bits",),
    "output_mode": ("advanced_mapping", "output_mode"),
    "invert_x": ("advanced_mapping", "invert_x"),
    "invert_y": ("advanced_mapping", "invert_y"),
    "sensitivity": ("advanced_mapping", "sensitivity"),
    "overlap_area": ("advanced_mapping", "overlap_area"),
    "dpi": ("advanced_mapping", "dpi"),
}
# Confirmed factory defaults (same values `_load_fields` already falls
# back to for a `None` reading) -- `output_mode` isn't here, its default
# is side-aware (see `_StickSideWidget._effective_default`).
_SETTING_DEFAULTS = {
    "trajectory": "circle", "curve": "standard",
    "deadzone_initial": 0, "deadzone_max": 100,
    "anti_deadzone_initial": 0, "anti_deadzone_max": 100,
    "resolution_bits": 12,
    "invert_x": False, "invert_y": False,
    "sensitivity": 50, "overlap_area": 50, "dpi": 50,
}
_TRAJECTORY_LABELS = dict(_TRAJECTORY_SEGMENTS)
_CURVE_LABELS = dict(_CURVE_SEGMENTS)
_OUTPUT_MODE_LABELS = dict(OUTPUT_MODE_OPTIONS)
_PERCENT_SETTINGS = {"deadzone_initial", "deadzone_max", "anti_deadzone_initial",
                     "anti_deadzone_max", "sensitivity", "overlap_area", "dpi"}


class _StickSideWidget(CategorySideWidget):
    # path, FieldSpec, desired value, profile -- same shape as
    # TriggersView's per-side signals; MainWindow's per-profile
    # `_sticks_draft` listens to this, not to `changed`.
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(
        self, side: str, palette: Palette = DARK_PALETTE, parent: Optional[QWidget] = None,
    ) -> None:
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): this widget used
        # to have no idea which side it represented at all, and
        # _load_fields()'s output_mode fallback was hardcoded to
        # "left_stick" unconditionally -- correct for the left instance,
        # wrong for the right one. Since SticksView._on_edit() sweeps BOTH
        # side widgets' save_into() on any single edit (matching this
        # codebase's general "any edit re-derives the whole section"
        # pattern), editing only the left stick still called save_into() on
        # the right widget too, which read back its currently-DISPLAYED
        # (wrongly-defaulted) output_mode -- so a real
        # "Right Stick: output_mode=left_stick" write got scheduled from an
        # edit that never touched the right stick at all. `side` lets the
        # fallback be correct for whichever instance this is.
        self.side = side
        self._profile = 1
        self._side_data: dict = {}
        self._touched: set = set()
        self._loaded: dict = {}
        self._was_labels: dict[str, QLabel] = {}
        self._revert_buttons: dict[str, QPushButton] = {}
        self._row_widgets: dict[str, QWidget] = {}
        # True once the user has genuinely picked an output_mode -- see
        # save_into()'s own comment for why this can't just be "whatever
        # the combo currently shows."
        self._output_mode_configured = False
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        basic_box = QGroupBox("Basic")
        form = QFormLayout(basic_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        self.trajectory = SegmentedControl(_TRAJECTORY_SEGMENTS)
        self.trajectory.setToolTip(
            "Circle: normalizes diagonal stick travel to a circular range. "
            "Raw: passes the physical X/Y axis values through unshaped."
        )
        self.curve = SegmentedControl(_CURVE_SEGMENTS)
        self.curve.setToolTip("The input-to-output response curve shape.")
        # Real bug, found while re-skinning onto SegmentedControl: unlike
        # QComboBox (which always auto-selects its first item), a fresh
        # SegmentedControl is off-scale -- value() is None until something
        # calls set_value(). _load_fields() does that on a real load(), but
        # a widget that's merely constructed (every test that builds one
        # directly, and this widget's own first instant before load_state()
        # is ever called) is not "loaded" yet. curve.value() reaching
        # preset_points(None) as an unhandled AttributeError inside a Qt
        # signal callback is fatal, not a catchable Python exception --
        # PyQt6 can't unwind a Python exception through the C++ signal
        # machinery that invoked it, so it aborts the whole process.
        # Signals blocked: this is a display default, not a user edit or a
        # load, and nothing downstream (curve_points/curve_editor) exists
        # yet at this point in __init__ for _update_curve_points_enabled()
        # to touch even if it did fire.
        self.trajectory.blockSignals(True)
        self.trajectory.set_value("circle")
        self.trajectory.blockSignals(False)
        self.curve.blockSignals(True)
        self.curve.set_value("standard")
        self.curve.blockSignals(False)
        self.dz_initial = NumberField.percent()
        self.dz_initial.setToolTip(
            "Stick movement below this percent of travel from center is ignored."
        )
        self.dz_max = NumberField.percent()
        self.dz_max.setToolTip(
            "Percent of travel from center at which the stick reports full output."
        )
        self.adz_initial = NumberField.percent()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts the output "
            "curve near center instead of ignoring it -- compensates for a "
            "stick that has a real mechanical dead zone."
        )
        self.adz_max = NumberField.percent()
        self.adz_max.setToolTip(self.adz_initial.toolTip())
        self.resolution_bits = QSpinBox()
        self.resolution_bits.setRange(8, 12)
        self.resolution_bits.setToolTip(
            "ADC resolution the stick reports at, 8-12 bits. Lower values "
            "coarsen precision."
        )

        self._controls = {
            "trajectory": self.trajectory, "curve": self.curve,
            "deadzone_initial": self.dz_initial, "deadzone_max": self.dz_max,
            "anti_deadzone_initial": self.adz_initial, "anti_deadzone_max": self.adz_max,
            "resolution_bits": self.resolution_bits,
        }

        form.addRow("Trajectory", self._wrap_with_mark_revert("trajectory", self.trajectory))
        form.addRow("Curve preset", self._wrap_with_mark_revert("curve", self.curve))
        self.curve_points = CurvePointsEditor()
        self.curve_points.changed.connect(self._emit_changed)
        self.curve_points.changed.connect(self._sync_curve_editor)
        # Own group: these are 0-255 while every field around them is a
        # percentage, and they only apply to a Custom curve.
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
        form.addRow("Deadzone (initial)", self._wrap_with_mark_revert("deadzone_initial", self.dz_initial))
        form.addRow("Deadzone (max)", self._wrap_with_mark_revert("deadzone_max", self.dz_max))
        form.addRow("Anti-Deadzone (initial)", self._wrap_with_mark_revert("anti_deadzone_initial", self.adz_initial))
        form.addRow("Anti-Deadzone (max)", self._wrap_with_mark_revert("anti_deadzone_max", self.adz_max))
        form.addRow("Resolution (bits)", self._wrap_with_mark_revert("resolution_bits", self.resolution_bits))
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
        self.invert_x = Checkbox("Invert X")
        self.invert_x.setToolTip("Reverses this stick's X axis.")
        self.invert_y = Checkbox("Invert Y")
        self.invert_y.setToolTip("Reverses this stick's Y axis.")
        self.sensitivity = NumberField.percent()
        self.sensitivity.setToolTip("X/Y sensitivity scale, 0-100 (50 = balanced).")
        self.overlap_area = NumberField.percent()
        self.overlap_area.setToolTip(
            "How much the diagonal zones overlap between adjacent directional "
            "buttons (Directional output mode only)."
        )
        self.dpi = NumberField.percent()
        self.dpi.setToolTip("Mouse movement speed (Simulate Mouse output mode only).")
        self._controls.update({
            "output_mode": self.output_mode, "invert_x": self.invert_x, "invert_y": self.invert_y,
            "sensitivity": self.sensitivity, "overlap_area": self.overlap_area, "dpi": self.dpi,
        })
        self.adv_form.addRow("Output mode", self._wrap_with_mark_revert("output_mode", self.output_mode))
        self.adv_form.addRow("", self._wrap_with_mark_revert("invert_x", self.invert_x))
        self.adv_form.addRow("", self._wrap_with_mark_revert("invert_y", self.invert_y))
        self.adv_form.addRow("Sensitivity", self._wrap_with_mark_revert("sensitivity", self.sensitivity))
        self.adv_form.addRow(
            "Overlap area (Directional only)", self._wrap_with_mark_revert("overlap_area", self.overlap_area))
        self.adv_form.addRow("DPI (Simulate Mouse only)", self._wrap_with_mark_revert("dpi", self.dpi))

        # One shared KeycodePicker for this side's five direction fields,
        # same reasoning as ButtonsView's single picker -- they're never
        # open at once, so there's no reason to build five popovers.
        self._direction_picker = KeycodePicker(self)
        self._direction_picker.codeChosen.connect(self._on_direction_code_chosen)
        self._active_direction_field: Optional[BindingField] = None
        self.direction_combos: dict[str, BindingField] = {}
        self.direction_box = QGroupBox("Direction Bindings (Directional Buttons only)")
        dir_form = QFormLayout(self.direction_box)
        dir_form.setVerticalSpacing(10)
        dir_form.setHorizontalSpacing(14)
        for zone in ("up", "down", "left", "right", "ring"):
            field = BindingField()
            field.setAccessibleName(zone.capitalize())
            field.setToolTip(
                f"Keycode sent while the stick is held toward {zone.capitalize()} "
                "(Directional output mode only)."
            )
            field.clicked.connect(lambda _checked=False, z=zone: self._open_direction_picker(z))
            dir_form.addRow(zone.capitalize(), field)
            self.direction_combos[zone] = field
        self.adv_form.addRow(self.direction_box)
        outer.addWidget(adv_box)
        outer.addStretch(1)

        self.trajectory.selectionChanged.connect(lambda _v: self._mark_touched("trajectory"))
        self.trajectory.selectionChanged.connect(self._emit_changed)
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
        self.curve.selectionChanged.connect(lambda _v: self._mark_touched("curve"))
        self.curve.selectionChanged.connect(self._update_curve_points_enabled)
        self.curve.selectionChanged.connect(self._emit_changed)
        for setting, w in (("deadzone_initial", self.dz_initial), ("deadzone_max", self.dz_max),
                           ("anti_deadzone_initial", self.adz_initial), ("anti_deadzone_max", self.adz_max),
                           ("resolution_bits", self.resolution_bits), ("sensitivity", self.sensitivity),
                           ("overlap_area", self.overlap_area), ("dpi", self.dpi)):
            w.valueChanged.connect(lambda _v, s=setting: self._mark_touched(s))
            w.valueChanged.connect(self._emit_changed)
        for w in (self.dz_initial, self.dz_max, self.adz_initial, self.adz_max):
            w.valueChanged.connect(self._sync_curve_editor)
        for setting, w in (("invert_x", self.invert_x), ("invert_y", self.invert_y)):
            w.toggled.connect(lambda _v, s=setting: self._mark_touched(s))
            w.toggled.connect(self._emit_changed)
        self.output_mode.currentIndexChanged.connect(self._update_visibility)
        self.output_mode.currentIndexChanged.connect(self._emit_changed)
        self.output_mode.currentIndexChanged.connect(self._mark_output_mode_configured)
        self.output_mode.currentIndexChanged.connect(lambda _i: self._mark_touched("output_mode"))

    def _wrap_with_mark_revert(self, setting: str, control: QWidget) -> QWidget:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(control)
        was_label = QLabel("")
        was_label.setProperty("role", "muted")
        was_label.setVisible(False)
        row.addWidget(was_label)
        revert_btn = QPushButton("Revert")
        revert_btn.setProperty("role", "link")
        revert_btn.setVisible(False)
        revert_btn.clicked.connect(lambda _c=False, s=setting: self._revert_setting(s))
        row.addWidget(revert_btn)
        row.addStretch(1)
        self._was_labels[setting] = was_label
        self._revert_buttons[setting] = revert_btn
        self._row_widgets[setting] = row_widget
        return row_widget

    def set_profile(self, profile: int) -> None:
        self._profile = profile

    def _get_value(self, setting: str):
        control = self._controls[setting]
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, Checkbox):
            return control.isChecked()
        return control.value()  # SegmentedControl (str) / NumberField, QSpinBox (int)

    def _set_value(self, setting: str, value) -> None:
        control = self._controls[setting]
        if isinstance(control, QComboBox):
            idx = control.findData(value)
            control.setCurrentIndex(idx if idx >= 0 else 0)
        elif isinstance(control, Checkbox):
            control.setChecked(bool(value))
        elif isinstance(control, SegmentedControl):
            control.set_value(value)
        else:
            control.setValue(value)

    def _effective_default(self, setting: str):
        if setting == "output_mode":
            # The confirmed factory default is "this stick controls
            # itself", not universally "left_stick" -- see __init__'s own
            # comment on `self.side` for the bug this side-awareness fixes.
            return f"{self.side}_stick"
        return _SETTING_DEFAULTS[setting]

    def _format_was(self, setting: str, value) -> str:
        if setting == "trajectory":
            return f"was {_TRAJECTORY_LABELS.get(value, value)}"
        if setting == "curve":
            return f"was {_CURVE_LABELS.get(value, value)}"
        if setting == "output_mode":
            return f"was {_OUTPUT_MODE_LABELS.get(value, value)}"
        if setting in ("invert_x", "invert_y"):
            return f"was {'On' if value else 'Off'}"
        if setting == "resolution_bits":
            return f"was {value} bits"
        return f"was {value}%"

    def _mark_touched(self, setting: str) -> None:
        if self._loading:
            return
        self._touched.add(setting)
        control = self._controls[setting]
        if hasattr(control, "set_edited"):
            control.set_edited(True)
        raw = self._loaded.get(setting)
        effective = raw if raw is not None else self._effective_default(setting)
        self._was_labels[setting].setText(self._format_was(setting, effective))
        self._was_labels[setting].setVisible(True)
        self._revert_buttons[setting].setVisible(True)
        field = STICK_FIELDS[self.side][setting]
        path = ("sticks", self.side) + _SIMPLE_SETTING_PATHS[setting]
        self.fieldTouched.emit(path, field, self._get_value(setting), self._profile)

    def _revert_setting(self, setting: str) -> None:
        raw = self._loaded.get(setting)
        effective = raw if raw is not None else self._effective_default(setting)
        self._loading = True
        try:
            self._set_value(setting, effective)
            if setting == "output_mode":
                self._output_mode_configured = raw is not None
                self._update_visibility()
        finally:
            self._loading = False
        self._touched.discard(setting)
        control = self._controls[setting]
        if hasattr(control, "set_edited"):
            control.set_edited(False)
        self._was_labels[setting].setVisible(False)
        self._revert_buttons[setting].setVisible(False)
        suffix = _SIMPLE_SETTING_PATHS[setting]
        d = self._side_data
        for key in suffix[:-1]:
            d = d.setdefault(key, {})
        d[suffix[-1]] = effective if setting != "output_mode" else (effective if self._output_mode_configured else None)
        path = ("sticks", self.side) + suffix
        self.fieldReverted.emit(path)
        self._emit_changed()

    def _open_direction_picker(self, zone: str) -> None:
        field = self.direction_combos[zone]
        self._active_direction_field = field
        self._direction_picker.open_for(field, field.value(), known=field.is_known())

    def _on_direction_code_chosen(self, value) -> None:
        if self._active_direction_field is None:
            return
        self._active_direction_field.set_value(value, known=value is None or value in KNOWN_KEYCODES)
        self._active_direction_field = None
        self._emit_changed()

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
            # REAL BUG, found 2026-09-17 (Astra's bug-sweep): this branch
            # used to only update _last_preset bookkeeping -- switching
            # between two NAMED presets (e.g. Standard -> Concave) never
            # touched curve_points/curve_editor at all, so the graph kept
            # showing whatever shape was last displayed while the combo
            # correctly said "Concave." A user who then started
            # customizing was actually editing the stale, wrong points.
            # Reload to the NEWLY selected preset's real shape every time
            # -- load() doesn't emit its own `changed` (blockSignals), so
            # this can't loop back into save_into() before _emit_changed
            # fires next on this same signal (connection order, see the
            # comment above this one).
            self._last_preset = self.curve.value()
            self.curve_points.load(preset_points(self._last_preset))
            self._sync_curve_editor()
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
        # blockSignals() above means valueChanged (and therefore
        # _mark_touched) never fires for a graphical-editor drag -- see
        # triggers_view.py's identical fix/comment.
        if not self._loading:
            for setting in ("deadzone_initial", "deadzone_max", "anti_deadzone_initial", "anti_deadzone_max"):
                self._mark_touched(setting)
        self._emit_changed()


    def _update_visibility(self) -> None:
        self._update_curve_points_enabled()
        mode = self.output_mode.currentData()
        _set_row_visible(self.adv_form, self._row_widgets["sensitivity"], mode in ("left_stick", "right_stick", "mouse"))
        _set_row_visible(self.adv_form, self._row_widgets["overlap_area"], mode == "directional")
        _set_row_visible(self.adv_form, self._row_widgets["dpi"], mode == "mouse")
        self.direction_box.setVisible(mode == "directional")

    def _load_fields(self, side_data: dict) -> None:
        self._side_data = side_data
        self.trajectory.set_value(side_data.get("trajectory") or "circle")
        curve = side_data.get("curve") or {}
        self.curve.set_value(curve.get("preset") or "standard")
        self.curve_points.load(curve.get("points"))
        dz = side_data.get("deadzone") or {}
        self.dz_initial.setValue(dz.get("initial") if dz.get("initial") is not None else 0)
        self.dz_max.setValue(dz.get("max") if dz.get("max") is not None else 100)
        adz = side_data.get("anti_deadzone") or {}
        self.adz_initial.setValue(adz.get("initial") if adz.get("initial") is not None else 0)
        self.adz_max.setValue(adz.get("max") if adz.get("max") is not None else 100)
        self.resolution_bits.setValue(side_data.get("resolution_bits") or 12)

        am = side_data.get("advanced_mapping") or {}
        # Side-aware fallback -- see __init__'s comment for the bug this
        # fixes. The confirmed factory default is "this stick controls
        # itself", not universally "left_stick". The combo needs SOME item
        # selected (it can't visually show "None"), but that's a display
        # decision only -- _output_mode_configured (set right after, and
        # updated only by a genuine user edit via
        # _mark_output_mode_configured) is what save_into() actually
        # trusts, so this fallback never leaks into a real write on its own.
        default_output_mode = f"{self.side}_stick"
        idx = self.output_mode.findData(am.get("output_mode") or default_output_mode)
        self.output_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._output_mode_configured = am.get("output_mode") is not None
        self.invert_x.setChecked(bool(am.get("invert_x")))
        self.invert_y.setChecked(bool(am.get("invert_y")))
        self.sensitivity.setValue(am.get("sensitivity") if am.get("sensitivity") is not None else 50)
        self.overlap_area.setValue(am.get("overlap_area") if am.get("overlap_area") is not None else 50)
        self.dpi.setValue(am.get("dpi") if am.get("dpi") is not None else 50)
        db = am.get("direction_bindings") or {}
        for zone, field in self.direction_combos.items():
            field.set_value(db.get(zone))

        self._touched = set()
        self._loaded = {
            "trajectory": side_data.get("trajectory"), "curve": curve.get("preset"),
            "deadzone_initial": dz.get("initial"), "deadzone_max": dz.get("max"),
            "anti_deadzone_initial": adz.get("initial"), "anti_deadzone_max": adz.get("max"),
            "resolution_bits": side_data.get("resolution_bits"),
            "output_mode": am.get("output_mode"),
            "invert_x": am.get("invert_x"), "invert_y": am.get("invert_y"),
            "sensitivity": am.get("sensitivity"), "overlap_area": am.get("overlap_area"), "dpi": am.get("dpi"),
        }
        for setting, control in self._controls.items():
            if hasattr(control, "set_edited"):
                control.set_edited(False)
            self._was_labels[setting].setVisible(False)
            self._revert_buttons[setting].setVisible(False)

    def _after_load(self) -> None:
        self._update_visibility()
        self._sync_curve_editor()

    def _mark_output_mode_configured(self, *_args: object) -> None:
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep), root cause traced
        # further here after the first, insufficient fix attempt: making
        # the DISPLAY fallback side-aware (right stick shows "right_stick"
        # instead of "left_stick" when unconfigured) stopped the WRONG
        # value from being written, but not the write itself -- save_into()
        # unconditionally read back self.output_mode.currentData(), which
        # is a display concern, and stored whatever that happened to be
        # even when nothing about output_mode was ever actually touched.
        # SticksView._on_edit() sweeps BOTH side widgets' save_into() on
        # any single edit anywhere (this codebase's general pattern), so
        # editing the left stick's sensitivity still converted the right
        # stick's genuinely-unconfigured (None) output_mode into a real,
        # concrete stored value -- just now a semantically-neutral one
        # instead of a wrong-side one. Still a real, unrequested write.
        #
        # This flag is the actual fix: it only becomes True when THIS
        # combo's own index changes for a real reason, guarded by the same
        # `_loading` flag load() already uses -- so a programmatic
        # setCurrentIndex() during _load_fields() never sets it, and a
        # genuine user selection always does. save_into() trusts this flag,
        # not the combo's raw display value.
        if not self._loading:
            self._output_mode_configured = True

    def save_into(self, side_data: dict) -> None:
        side_data["trajectory"] = self.trajectory.value()
        # Merge rather than replace: a plain assignment here dropped the
        # "points" a device read had brought back, so any unrelated edit
        # silently discarded them.
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.value()
        curve["points"] = self.curve_points.points() if self.curve.value() == "custom" else None
        side_data["deadzone"] = {"initial": self.dz_initial.value(), "max": self.dz_max.value()}
        side_data["anti_deadzone"] = {"initial": self.adz_initial.value(), "max": self.adz_max.value()}
        side_data["resolution_bits"] = self.resolution_bits.value()
        am = side_data.setdefault("advanced_mapping", {})
        am["output_mode"] = self.output_mode.currentData() if self._output_mode_configured else None
        am["invert_x"] = self.invert_x.isChecked()
        am["invert_y"] = self.invert_y.isChecked()
        am["sensitivity"] = self.sensitivity.value()
        am["overlap_area"] = self.overlap_area.value()
        am["dpi"] = self.dpi.value()
        if am["output_mode"] == "directional":
            am["direction_bindings"] = {
                zone: field.value() for zone, field in self.direction_combos.items()
            }


class SticksView(QWidget):
    changed = pyqtSignal()
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(self, palette: Palette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.sides = {
            "left": _StickSideWidget("left", palette), "right": _StickSideWidget("right", palette),
        }
        for side, widget in self.sides.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            widget.changed.connect(self._on_edit)
            widget.fieldTouched.connect(self.fieldTouched)
            widget.fieldReverted.connect(self.fieldReverted)
            self.tabs.addTab(scroll, f"{side.capitalize()} Stick")
        layout.addWidget(self.tabs)

    def set_palette(self, palette: Palette) -> None:
        """Repaints both sides' CurveEditor on a theme change -- it paints
        with QPainter, not QSS, so it needs this explicit call rather than
        picking up a regenerated stylesheet on its own."""
        for widget in self.sides.values():
            widget.curve_editor.set_palette(palette)

    def load_state(self, state: dict) -> None:
        self._state = state
        profile = state.get("controller_slot") or 1
        for side, widget in self.sides.items():
            widget.set_profile(profile)
            widget.load(state["sticks"].setdefault(side, {}))

    def _on_edit(self) -> None:
        if self._state is None:
            return
        for side, widget in self.sides.items():
            widget.save_into(self._state["sticks"].setdefault(side, {}))
        self.changed.emit()
