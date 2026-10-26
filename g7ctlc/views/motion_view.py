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

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): the sixth
S6 slice onto the real per-field draft model, one of the two categories
Track S's own ordering flagged as most irregular. Migrated: all 11-12 of
`pyg7.field_spec.MOTION_FIELDS`' "simple" settings per side
(`activate_method`, `x_axis_output_mode`, `curve` preset,
`deadzone_initial/max`, `anti_deadzone_initial/max`, `invert_y`,
`invert_yaw`, `sensitivity_scale`, `output`, `overlap_area`, plus
`invert_roll` on Aim only), plus a second pass adding `activate_button`
and the four `direction_up/down/left/right` zone bindings -- the first
keycode-binding fields on the per-field draft model anywhere in the
app. Traced all the way through before building: these use plain
`FieldSpec` + `Intent.CLEAR`, not `ButtonFieldSpec`, so `prepare()`/
`execute()` already round-trip them correctly with no engine change
needed (unlike Buttons' own `ButtonFieldSpec`, which needed a real
signature fix -- see `pyg7/field_spec.py`'s `ButtonFieldSpec` docstring).
The only new work was GUI-side: `KeycodePicker`'s existing "(Default)"
choice already emits `None` for "unbind", so `_on_code_chosen()` now
maps that to `Intent.CLEAR` (not raw `None`) when marking a field
touched, and the "was X" row shows `keycode_display_text()`'s own
"Not remapped" wording for a `None` baseline -- the same label the
field itself already shows, not a new one invented for this slice.
`curve_points` has no write-side UI at all in this view to migrate (see
this docstring's own first paragraph) and remains the one field still
write-only through the old whole-side Sync Now path.
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7.buttons import KNOWN_KEYCODES
from pyg7.field_spec import MOTION_FIELDS, Intent

from ..binding_field import BindingField
from ..checkbox import Checkbox
from ..keycode_picker import KeycodePicker
from ..number_field import NumberField
from ..segmented_control import SegmentedControl
from ..widgets import CategorySideWidget, keycode_display_text
from ..widgets import (
    set_row_visible as _set_row_visible,
)
from .sticks_view import OUTPUT_MODE_OPTIONS

X_AXIS_OUTPUT_MODE_OPTIONS = [("yaw", "Yaw"), ("yaw_roll", "Yaw + Roll")]
# Confirmed 2026-08-18, reading Nexus's own dropdown directly -- see
# pyg7/motion.py's ACTIVATE_METHODS.
ACTIVATE_METHOD_OPTIONS = [
    ("off", "Off"), ("hold_to_activate", "Hold to Activate"),
    ("press_to_activate", "Press to Activate"), ("always_on", "Always On"),
]
_CURVE_SEGMENTS = [("standard", "Standard"), ("concave", "Concave"),
                   ("s_curve", "S-curve"), ("custom", "Custom")]

# Mirrors field_spec.py's own `_MOTION_SIMPLE_SETTINGS` path tuples
# exactly (minus the leading `("motion", side)`, which this view prepends
# itself) -- same duplication reasoning as sticks_view.py/
# triggers_view.py's identical tables. `invert_roll` isn't here -- it's
# Aim-only, handled separately wherever this table is used.
_SIMPLE_SETTING_PATHS = {
    "activate_method": ("activate_method",),
    "x_axis_output_mode": ("x_axis_output_mode",),
    "curve": ("curve", "preset"),
    "deadzone_initial": ("deadzone", "initial"),
    "deadzone_max": ("deadzone", "max"),
    "anti_deadzone_initial": ("anti_deadzone", "initial"),
    "anti_deadzone_max": ("anti_deadzone", "max"),
    "invert_y": ("invert_y",),
    "invert_yaw": ("invert_yaw",),
    "sensitivity_scale": ("sensitivity_scale",),
    "output": ("output",),
    "overlap_area": ("overlap_area",),
    "invert_roll": ("invert_roll",),
    # Keycode-binding settings -- same table, same path-building code at
    # every call site, but `_KEYCODE_SETTINGS` below marks these for the
    # CLEAR-mapping/"was X" differences their `None` actually needs.
    "activate_button": ("activate_button",),
    "direction_up": ("direction_bindings", "up"),
    "direction_down": ("direction_bindings", "down"),
    "direction_left": ("direction_bindings", "left"),
    "direction_right": ("direction_bindings", "right"),
}
# A keycode field's `None` is a real, confirmed "unbound" state (motion.py's
# own `_resolve_keycode_or_unbound()`) -- never a display fallback like
# every other field's `None` means, so these get their own `Intent.CLEAR`
# mapping and "was X" wording instead of `_SETTING_DEFAULTS`/`_format_was`'s
# generic path.
_KEYCODE_SETTINGS = frozenset(
    {"activate_button", "direction_up", "direction_down", "direction_left", "direction_right"})
# Confirmed factory defaults (same values `_load_fields` already falls
# back to for a `None` reading).
_SETTING_DEFAULTS = {
    "activate_method": "off", "x_axis_output_mode": "yaw", "curve": "standard",
    "deadzone_initial": 0, "deadzone_max": 100,
    "anti_deadzone_initial": 0, "anti_deadzone_max": 100,
    "invert_y": False, "invert_yaw": False, "invert_roll": False,
    "sensitivity_scale": 50, "output": "left_stick", "overlap_area": 50,
}
_ACTIVATE_METHOD_LABELS = dict(ACTIVATE_METHOD_OPTIONS)
_X_AXIS_LABELS = dict(X_AXIS_OUTPUT_MODE_OPTIONS)
_CURVE_LABELS = dict(_CURVE_SEGMENTS)
_OUTPUT_MODE_LABELS = dict(OUTPUT_MODE_OPTIONS)


class _MotionSideWidget(CategorySideWidget):
    # path, FieldSpec, desired value, profile -- same shape as
    # SticksView's/TriggersView's per-side signals; MainWindow's
    # per-profile `_motion_draft` listens to this, not to `changed`.
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(self, side: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.side = side
        self._profile = 1
        self._side_data: dict = {}
        self._touched: set = set()
        self._loaded: dict = {}
        self._was_labels: dict[str, QLabel] = {}
        self._revert_buttons: dict[str, QPushButton] = {}
        self._row_widgets: dict[str, QWidget] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        basic_box = QGroupBox("Basic")
        self.form = QFormLayout(basic_box)
        self.form.setVerticalSpacing(10)
        self.form.setHorizontalSpacing(14)

        # One shared KeycodePicker for this side's picker-backed fields
        # (Activate Button plus the four direction bindings below) -- same
        # reasoning as ButtonsView's/SticksView's single picker.
        self._picker = KeycodePicker(self)
        self._picker.codeChosen.connect(self._on_code_chosen)
        self._active_field: Optional[BindingField] = None
        # Maps a BindingField instance back to its own setting name --
        # _on_code_chosen() is one shared callback for every keycode field
        # on this side, so it needs this to know which one to mark
        # touched once the picker returns.
        self._field_to_setting: dict[BindingField, str] = {}

        self.activate_method = QComboBox()
        for value, label in ACTIVATE_METHOD_OPTIONS:
            self.activate_method.addItem(label, value)
        self.activate_method.setToolTip("How motion input gets activated.")
        self.activate_button = BindingField()
        self.activate_button.setAccessibleName("Activate Button")
        self.activate_button.setToolTip("Which button, held or pressed, activates motion input.")
        self.activate_button.clicked.connect(lambda: self._open_picker(self.activate_button))
        self._field_to_setting[self.activate_button] = "activate_button"
        self.x_axis_output_mode = QComboBox()
        for value, label in X_AXIS_OUTPUT_MODE_OPTIONS:
            self.x_axis_output_mode.addItem(label, value)
        self.x_axis_output_mode.setToolTip(
            "Yaw + Roll reveals an extra invert control below; plain Yaw does not."
        )
        self.curve = SegmentedControl(_CURVE_SEGMENTS)
        self.curve.setToolTip(
            "The input-to-output response curve shape. Custom curves can be "
            "selected but their control points aren't editable here yet -- "
            "not captured on the wire for Motion (see pyg7/motion.py)."
        )
        # Display default, signals blocked -- see sticks_view.py's
        # SegmentedControl off-scale fix for the full reasoning (no
        # preset_points() call here to crash on None, but an always-real
        # field left genuinely off-scale is still the wrong display).
        self.curve.blockSignals(True)
        self.curve.set_value("standard")
        self.curve.blockSignals(False)
        self.dz_initial = NumberField.percent()
        self.dz_initial.setToolTip("Motion below this percent of the stick's travel range is ignored.")
        self.dz_max = NumberField.percent()
        self.dz_max.setToolTip("Percent of travel at which motion reports full output.")
        self.adz_initial = NumberField.percent()
        self.adz_initial.setToolTip(
            "Same Initial/Max shape as Deadzone above, but boosts output near center instead of ignoring it."
        )
        self.adz_max = NumberField.percent()
        self.adz_max.setToolTip(self.adz_initial.toolTip())
        self.sensitivity_scale = NumberField.percent()
        self.sensitivity_scale.setToolTip("X/Y sensitivity scale, 0-100 (50 = balanced).")

        self._controls = {
            "activate_method": self.activate_method, "x_axis_output_mode": self.x_axis_output_mode,
            "curve": self.curve, "deadzone_initial": self.dz_initial, "deadzone_max": self.dz_max,
            "anti_deadzone_initial": self.adz_initial, "anti_deadzone_max": self.adz_max,
            "sensitivity_scale": self.sensitivity_scale, "activate_button": self.activate_button,
        }

        self.form.addRow("Activate Method", self._wrap_with_mark_revert("activate_method", self.activate_method))
        self.form.addRow("Activate Button", self._wrap_with_mark_revert("activate_button", self.activate_button))
        self.form.addRow(
            "X-Axis Output Mode", self._wrap_with_mark_revert("x_axis_output_mode", self.x_axis_output_mode))
        self.form.addRow("Curve preset", self._wrap_with_mark_revert("curve", self.curve))
        self.form.addRow("Deadzone (initial)", self._wrap_with_mark_revert("deadzone_initial", self.dz_initial))
        self.form.addRow("Deadzone (max)", self._wrap_with_mark_revert("deadzone_max", self.dz_max))
        self.form.addRow(
            "Anti-Deadzone (initial)", self._wrap_with_mark_revert("anti_deadzone_initial", self.adz_initial))
        self.form.addRow("Anti-Deadzone (max)", self._wrap_with_mark_revert("anti_deadzone_max", self.adz_max))
        self.form.addRow(
            "X/Y Sensitivity Scale", self._wrap_with_mark_revert("sensitivity_scale", self.sensitivity_scale))

        self.invert_y = Checkbox("Invert Y")
        self.invert_y.setToolTip("Reverses this sub-tab's Y axis.")
        self._controls["invert_y"] = self.invert_y
        self.form.addRow("", self._wrap_with_mark_revert("invert_y", self.invert_y))
        self.invert_yaw = Checkbox("Invert Yaw")
        self.invert_yaw.setToolTip(
            "Only shown by Nexus when X-Axis Output Mode is Yaw + Roll and "
            "Output is not Button Binds. Address confirmed on the wire; "
            "whether Nexus still calls this \"Invert Yaw\" on the Tilt "
            "sub-tab specifically is not (see pyg7/motion.py)."
        )
        self._controls["invert_yaw"] = self.invert_yaw
        self.form.addRow("", self._wrap_with_mark_revert("invert_yaw", self.invert_yaw))
        if side == "aim":
            self.invert_roll = Checkbox("Invert Roll")
            self.invert_roll.setToolTip(
                "Aim only -- Tilt has no equivalent control. Only shown by "
                "Nexus when X-Axis Output Mode is Yaw + Roll and Output is "
                "Button Binds."
            )
            self._controls["invert_roll"] = self.invert_roll
            self.form.addRow("", self._wrap_with_mark_revert("invert_roll", self.invert_roll))
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
        self.overlap_area = NumberField.percent()
        self.overlap_area.setToolTip(
            "How much the diagonal zones overlap between adjacent directional buttons (Button Binds only)."
        )
        self._controls["output"] = self.output
        self._controls["overlap_area"] = self.overlap_area
        self.adv_form.addRow("Output", self._wrap_with_mark_revert("output", self.output))
        self.adv_form.addRow(
            "Overlap area (Button Binds only)", self._wrap_with_mark_revert("overlap_area", self.overlap_area))

        self.direction_combos: dict[str, BindingField] = {}
        self.direction_box = QGroupBox("Direction Bindings (Button Binds only)")
        dir_form = QFormLayout(self.direction_box)
        dir_form.setVerticalSpacing(10)
        dir_form.setHorizontalSpacing(14)
        # No "ring" zone here, unlike Sticks' direction_bindings -- Motion
        # has no stick click to bind (see pyg7/motion.py).
        for zone in ("up", "down", "left", "right"):
            field = BindingField()
            field.setAccessibleName(zone.capitalize())
            field.setToolTip(f"Keycode sent while motion is held toward {zone.capitalize()} (Button Binds only).")
            field.clicked.connect(lambda _checked=False, f=field: self._open_picker(f))
            setting = f"direction_{zone}"
            self._controls[setting] = field
            self._field_to_setting[field] = setting
            dir_form.addRow(zone.capitalize(), self._wrap_with_mark_revert(setting, field))
            self.direction_combos[zone] = field
        self.adv_form.addRow(self.direction_box)
        outer.addWidget(adv_box)
        outer.addStretch(1)

        for setting, w in (("activate_method", self.activate_method), ("x_axis_output_mode", self.x_axis_output_mode)):
            w.currentIndexChanged.connect(lambda _i, s=setting: self._mark_touched(s))
            w.currentIndexChanged.connect(self._emit_changed)
        self.curve.selectionChanged.connect(lambda _v: self._mark_touched("curve"))
        self.curve.selectionChanged.connect(self._emit_changed)
        for setting, w in (("deadzone_initial", self.dz_initial), ("deadzone_max", self.dz_max),
                           ("anti_deadzone_initial", self.adz_initial), ("anti_deadzone_max", self.adz_max),
                           ("sensitivity_scale", self.sensitivity_scale), ("overlap_area", self.overlap_area)):
            w.valueChanged.connect(lambda _v, s=setting: self._mark_touched(s))
            w.valueChanged.connect(self._emit_changed)
        for setting, w in (("invert_y", self.invert_y), ("invert_yaw", self.invert_yaw)):
            w.toggled.connect(lambda _v, s=setting: self._mark_touched(s))
            w.toggled.connect(self._emit_changed)
        if self.invert_roll is not None:
            self.invert_roll.toggled.connect(lambda _v: self._mark_touched("invert_roll"))
            self.invert_roll.toggled.connect(self._emit_changed)
        self.output.currentIndexChanged.connect(lambda _i: self._mark_touched("output"))
        self.output.currentIndexChanged.connect(self._update_visibility)
        self.output.currentIndexChanged.connect(self._emit_changed)
        self.x_axis_output_mode.currentIndexChanged.connect(self._update_visibility)

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
        return control.value()  # SegmentedControl (str) / NumberField (int) / BindingField (keycode name or None)

    def _set_value(self, setting: str, value) -> None:
        control = self._controls[setting]
        if isinstance(control, QComboBox):
            idx = control.findData(value)
            control.setCurrentIndex(idx if idx >= 0 else 0)
        elif isinstance(control, Checkbox):
            control.setChecked(bool(value))
        elif isinstance(control, SegmentedControl):
            control.set_value(value)
        elif isinstance(control, BindingField):
            control.set_value(value, known=value is None or value in KNOWN_KEYCODES)
        else:
            control.setValue(value)

    def _effective(self, setting: str, raw):
        """The value to show in a "was X" row and to restore on revert.
        A keycode field's `None` IS the real baseline (genuinely unbound,
        not a missing default) -- every other field's `None` instead
        means "never read/configured," which falls back to
        `_SETTING_DEFAULTS` the same way `_load_fields` already does."""
        if setting in _KEYCODE_SETTINGS:
            return raw
        return raw if raw is not None else _SETTING_DEFAULTS[setting]

    def _format_was(self, setting: str, value) -> str:
        if setting in _KEYCODE_SETTINGS:
            # Same wording the field itself already shows for this value
            # (BindingField._refresh_text()) -- not a new label invented
            # for this row.
            return f"was {keycode_display_text(value)}"
        if setting == "activate_method":
            return f"was {_ACTIVATE_METHOD_LABELS.get(value, value)}"
        if setting == "x_axis_output_mode":
            return f"was {_X_AXIS_LABELS.get(value, value)}"
        if setting == "curve":
            return f"was {_CURVE_LABELS.get(value, value)}"
        if setting == "output":
            return f"was {_OUTPUT_MODE_LABELS.get(value, value)}"
        if setting in ("invert_y", "invert_yaw", "invert_roll"):
            return f"was {'On' if value else 'Off'}"
        return f"was {value}%"

    def _mark_touched(self, setting: str) -> None:
        if self._loading:
            return
        control = self._controls[setting]
        value = self._get_value(setting)
        effective = self._effective(setting, self._loaded.get(setting))
        path = ("motion", self.side) + _SIMPLE_SETTING_PATHS[setting]
        if value == effective:
            # REAL BUG, found 2026-10-26 (hardware test):
            # manually dialing a field back to its originally-loaded
            # value (not clicking Revert) left the mark/revert row and
            # the draft ledger both still claiming an outstanding edit,
            # even though Write correctly found nothing left to do.
            # Treat landing back on the baseline as an implicit revert --
            # including a keycode field picked back to "(Default)" when
            # that genuinely was the loaded baseline (both sides None).
            self._touched.discard(setting)
            if hasattr(control, "set_edited"):
                control.set_edited(False)
            self._was_labels[setting].setVisible(False)
            self._revert_buttons[setting].setVisible(False)
            self.fieldReverted.emit(path)
            return
        self._touched.add(setting)
        if hasattr(control, "set_edited"):
            control.set_edited(True)
        self._was_labels[setting].setText(self._format_was(setting, effective))
        self._was_labels[setting].setVisible(True)
        self._revert_buttons[setting].setVisible(True)
        field = MOTION_FIELDS[self.side][setting]
        # A keycode field's chosen None means "declared: unbind this,"
        # Intent.CLEAR -- not Intent.PRESERVE (which DesiredDraft.touch()
        # rejects) and not raw None, which FieldSpec.plan_operation()
        # would not recognise as the CLEAR sentinel.
        desired = Intent.CLEAR if (setting in _KEYCODE_SETTINGS and value is None) else value
        self.fieldTouched.emit(path, field, desired, self._profile)

    def _revert_setting(self, setting: str) -> None:
        effective = self._effective(setting, self._loaded.get(setting))
        self._loading = True
        try:
            self._set_value(setting, effective)
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
        d[suffix[-1]] = effective
        self._update_visibility()
        path = ("motion", self.side) + suffix
        self.fieldReverted.emit(path)
        self._emit_changed()

    def _open_picker(self, field: BindingField) -> None:
        self._active_field = field
        self._picker.open_for(field, field.value(), known=field.is_known())

    def _on_code_chosen(self, value) -> None:
        if self._active_field is None:
            return
        self._active_field.set_value(value, known=value is None or value in KNOWN_KEYCODES)
        setting = self._field_to_setting.get(self._active_field)
        self._active_field = None
        self._emit_changed()
        if setting is not None:
            self._mark_touched(setting)

    def _update_visibility(self) -> None:
        directional = self.output.currentData() == "directional"
        yaw_roll = self.x_axis_output_mode.currentData() == "yaw_roll"
        _set_row_visible(self.adv_form, self._row_widgets["overlap_area"], directional)
        self.direction_box.setVisible(directional)
        _set_row_visible(self.form, self._row_widgets["invert_yaw"], yaw_roll and not directional)
        if self.invert_roll is not None:
            _set_row_visible(self.form, self._row_widgets["invert_roll"], yaw_roll and directional)

    def _load_fields(self, side_data: dict) -> None:
        self._side_data = side_data
        am_idx = self.activate_method.findData(side_data.get("activate_method") or "off")
        self.activate_method.setCurrentIndex(am_idx if am_idx >= 0 else 0)
        self.activate_button.set_value(side_data.get("activate_button"))
        idx = self.x_axis_output_mode.findData(side_data.get("x_axis_output_mode") or "yaw")
        self.x_axis_output_mode.setCurrentIndex(idx if idx >= 0 else 0)
        curve = side_data.get("curve") or {}
        self.curve.set_value(curve.get("preset") or "standard")
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
        for zone, field in self.direction_combos.items():
            field.set_value(db.get(zone))

        self._touched = set()
        self._loaded = {
            "activate_method": side_data.get("activate_method"),
            "x_axis_output_mode": side_data.get("x_axis_output_mode"),
            "curve": curve.get("preset"),
            "deadzone_initial": dz.get("initial"), "deadzone_max": dz.get("max"),
            "anti_deadzone_initial": adz.get("initial"), "anti_deadzone_max": adz.get("max"),
            "invert_y": side_data.get("invert_y"), "invert_yaw": side_data.get("invert_yaw"),
            "invert_roll": side_data.get("invert_roll"),
            "sensitivity_scale": side_data.get("sensitivity_scale"),
            "output": side_data.get("output"), "overlap_area": side_data.get("overlap_area"),
            "activate_button": side_data.get("activate_button"),
            "direction_up": db.get("up"), "direction_down": db.get("down"),
            "direction_left": db.get("left"), "direction_right": db.get("right"),
        }
        for setting, control in self._controls.items():
            if hasattr(control, "set_edited"):
                control.set_edited(False)
            self._was_labels[setting].setVisible(False)
            self._revert_buttons[setting].setVisible(False)

    def _after_load(self) -> None:
        self._update_visibility()

    def save_into(self, side_data: dict) -> None:
        side_data["activate_method"] = self.activate_method.currentData()
        side_data["activate_button"] = self.activate_button.value()
        side_data["x_axis_output_mode"] = self.x_axis_output_mode.currentData()
        curve = side_data.setdefault("curve", {})
        curve["preset"] = self.curve.value()
        # REAL BUG, found 2026-09-18 (Sol's bug-sweep): this used to set
        # curve["points"] = None unconditionally on every edit, actively
        # discarding real custom points that a device read may have
        # successfully decoded (pyg7.motion.decode_settings() does return
        # them when the block is configured -- only the WRITE side has no
        # curve_points setting yet, see this module's own docstring and
        # motion.py's). This widget has no point-editor UI and so has no
        # in-memory copy of its own to write back -- but it must not erase
        # points that were already there just because an unrelated field on
        # this same side (activate_method, deadzone, ...) was edited.
        # setdefault(), not an unconditional assignment: leaves whatever's
        # already in state untouched, only defaulting to None for a
        # brand-new curve dict that never had any -- same reasoning
        # Sticks' own curve_points editor has for a state it never wrote.
        curve.setdefault("points", None)
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
                zone: field.value() for zone, field in self.direction_combos.items()
            }


class MotionView(QWidget):
    changed = pyqtSignal()
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

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
            widget.fieldTouched.connect(self.fieldTouched)
            widget.fieldReverted.connect(self.fieldReverted)
            self.tabs.addTab(scroll, side.capitalize())
        layout.addWidget(self.tabs)

    def load_state(self, state: dict) -> None:
        self._state = state
        # Additive section (see pyg7/state.py's validate_state()) -- an
        # older imported state dict may not have "motion" at all.
        motion = state.setdefault("motion", {"aim": {}, "tilt": {}})
        profile = state.get("controller_slot") or 1
        for side, widget in self.sides.items():
            widget.set_profile(profile)
            widget.load(motion.setdefault(side, {}))

    def _on_edit(self) -> None:
        if self._state is None:
            return
        motion = self._state.setdefault("motion", {"aim": {}, "tilt": {}})
        for side, widget in self.sides.items():
            widget.save_into(motion.setdefault(side, {}))
        self.changed.emit()
