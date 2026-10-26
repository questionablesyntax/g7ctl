"""Buttons page: per-button Default/Shift-layer keycode assignment, A4/D2
of the redesign.

The controller diagram (`controller_diagram.py`) is the only remapping
surface. Two cuts landed the same day, both decisions: the
always-visible 21-row table (D2's own rework, 2026-10-22) and, next, the
side panel that replaced it (also 2026-10-22, after a hands-on test
drive) -- "we drop the info tab... nest the latch checkbox inside the
button picker dropdown." `IMPLEMENTATION-PLAN.md`'s D2 section has the
full history of both.

There is no per-button widget at all now -- no `BindingRow`, no
`BindingField`, nothing to keep in sync with `self._state`. Clicking or
keyboard-activating a diagram hit region reads straight from
`self._state["buttons"][self._layer]` and opens `KeycodePicker` for that
one value; choosing a code or toggling the picker's own Latch checkbox
writes straight back. The old `_on_edit()`'s "sweep every row" shape
doesn't exist either -- there's nothing to sweep, so each edit writes
only the one key it actually changed. The invariant that mattered
(2026-09-17: a reset must store an explicit `None`, never pop the key)
still holds the same way, just via a direct assignment instead of a
defensive full sweep over now-nonexistent widgets.

Shift (shared) reference, previously a read-only column next to the
Base-layer field: dropped entirely, decision -- it's already
visible on the dedicated Shift layer page (`set_layer("shift")`, the
same `ButtonsView` instance). This page is Base-layer-only now, full
stop.

`_order` groups controls the way they're physically arranged on the
controller (face buttons, stick clicks, shoulder/paddle pairs,
trigger/paddle pairs, D-pad, misc) rather than KNOWN_BUTTON_IDS's
declaration order, and doubles as the diagram's own Tab order. The
D-pad options (Swap Left Stick and D-pad, D-Pad Diagonal Lock) sit in a
thin row below the diagram -- page-level settings, not per-button, so
they were never part of the picker rework.

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): the
seventh S6 slice, and the hardest fit yet -- this page has no per-field
widget at all (the whole point of the cuts above), so the "was X%"/
revert row every other slice wraps a widget in has nowhere to attach.
The picker popover is the one per-button editing surface that exists,
so that's where `KeycodePicker`'s own new `was_text`/`revertRequested`
row lives instead (see its module docstring) -- opening the picker for
an already-touched button shows "was X" and a Revert button right
there, and the diagram's existing callout text (the only other
per-button display surface) gets an " (unwritten)" suffix so a pending
edit is visible without opening the picker at all. The D-pad options,
being plain checkboxes, get the ordinary wrap-the-widget row every
other slice uses instead -- this page has two different per-field UI
shapes because it has two genuinely different kinds of fields, not one
mechanism invented to look wrong for the other.

Deliberately not migrated: Latch/Continuous Trigger. It's `CT_FIELDS`
in `pyg7.field_spec` (a plain `FieldSpec`), but it shares a wire record
with the button's own binding rather than being independently
addressable the way every other coupled-field deferral in this track
(Vibration's Force/Sync, Sticks'/Triggers'/Motion's curve_points) has
been -- its own pass, not assumed here. Still writes through the old
whole-state Sync Now path only, same as before this slice.
"""
import copy
import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from pyg7.buttons import BUTTON_TABLE_SLOTS, KNOWN_BUTTON_IDS
from pyg7.field_spec import BUTTON_FIELDS, DPAD_FIELDS, Intent

from ..checkbox import Checkbox
from ..controller_diagram import ControllerDiagram
from ..keycode_picker import KeycodePicker
from ..palette import DARK_PALETTE, Palette
from ..widgets import is_known_keycode, keycode_display_text

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

_LATCH_TOOLTIP = (
    "GameSir calls this Continuous Trigger. Press once and the button stays "
    "held until pressed again. It is not turbo/rapid-fire -- the button "
    "does not repeat, which is also why there is no rate setting.\n\n"
    "Independent of the binding: it doesn't change what the button sends, "
    "only how long it stays sent.\n\n"
    "Profile-scoped, and stored inside the button's own record, so it "
    "applies to the Base layer only."
)

# LT/RT are the exception: they have no record in the button table (their
# keycode is a lone byte inside the Triggers category's data), so there is
# no Continuous Trigger byte to derive for them -- see
# pyg7.buttons.continuous_trigger_offset(). The picker shows this reason
# as visible text instead of a checkbox that would silently do nothing.
_LATCH_UNSUPPORTED_REASON = "Triggers have no latch setting"

log = logging.getLogger(__name__)


class ButtonsView(QWidget):
    changed = pyqtSignal()
    # path, FieldSpec, desired value, profile -- same shape as every other
    # S6 slice's per-field signals. `path` is `("buttons", layer, button)`
    # for a binding or `(setting,)` for a D-pad option; MainWindow's
    # per-profile `_buttons_draft` listens to this, not to `changed`.
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(self, palette: Palette = DARK_PALETTE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = None
        self._layer = "default"
        self._active_button: str | None = None  # whichever button's picker is open
        self._profile = 1
        # (layer, button_id) tuples with an outstanding, unwritten touch,
        # and the per-layer baseline (as of the last load_state()) they're
        # compared/reverted against -- this view's own display bookkeeping,
        # same role VibrationView's _loaded_levels/_sliders_touched play;
        # MainWindow's DesiredDraft is the authoritative ledger.
        self._touched: set = set()
        self._loaded_buttons: dict = {"default": {}, "shift": {}}

        self._picker = KeycodePicker(self)
        self._picker.codeChosen.connect(self._on_code_chosen)
        self._picker.latchToggled.connect(self._on_latch_toggled)
        self._picker.revertRequested.connect(self._on_revert_requested)
        self._picker.latch_checkbox.setToolTip(_LATCH_TOOLTIP)
        self._picker.latch_reason_label.setToolTip(
            "The triggers have no Continuous Trigger setting -- they're "
            "stored differently from the other buttons, and whether the "
            "hardware supports it for them at all is unknown.")

        self._order = [b for group in _BUTTON_GROUPS for b in group]
        # Defensive check: a button present in KNOWN_BUTTON_IDS but missing
        # from _BUTTON_GROUPS would silently vanish from the diagram's own
        # Tab order -- exactly the L5/R5 bug from before this list existed.
        grouped = set(self._order)
        missing = [b for b in KNOWN_BUTTON_IDS if b not in grouped]
        assert not missing, f"buttons missing from _BUTTON_GROUPS: {missing}"

        self.diagram = ControllerDiagram(
            palette, labels=_BUTTON_LABELS, order=self._order, parent=self)
        self.diagram.activated.connect(self._on_diagram_activated)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.diagram, 1)

        # Page-level, not per-button -- a thin row below the (now primary,
        # full-size) diagram rather than sharing space with it. Still
        # wrapped in its own QScrollArea, matching every other page
        # (test_gui_views.py's cross-page invariant) and the same pattern
        # _build_profile_settings_page() already uses for its own single
        # row of controls.
        self.options_separator = QFrame()
        self.options_separator.setFrameShape(QFrame.Shape.HLine)
        self.options_separator.setProperty("role", "separator")
        outer.addWidget(self.options_separator)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        options_widget = QWidget()
        options_row = QHBoxLayout(options_widget)
        options_row.setContentsMargins(10, 8, 10, 8)

        self._dpad_controls: dict = {}
        self._dpad_was_labels: dict = {}
        self._dpad_revert_buttons: dict = {}
        self._dpad_row_widgets: dict = {}
        self._dpad_loaded: dict = {}
        self._dpad_touched: set = set()

        self.swap_stick_dpad = Checkbox("Swap Left Stick and D-pad")
        self.swap_stick_dpad.toggled.connect(lambda _v: self._mark_dpad_touched("swap_stick_dpad"))
        self.swap_stick_dpad.toggled.connect(self._on_dpad_option_changed)
        self.swap_stick_dpad.setToolTip(
            "Hardware-verified 2026-07-29: a full-blob diff of a real ON then "
            "OFF write changed exactly the two intended bytes each time, and "
            "the OFF blob came back byte-identical to the pre-write baseline. "
            "See pyg7/dpad_options.py."
        )
        self._dpad_controls["swap_stick_dpad"] = self.swap_stick_dpad
        options_row.addWidget(self._wrap_dpad_with_mark_revert("swap_stick_dpad", self.swap_stick_dpad))

        self.dpad_diagonal_lock = Checkbox("D-Pad Diagonal Lock")
        self.dpad_diagonal_lock.toggled.connect(lambda _v: self._mark_dpad_touched("dpad_diagonal_lock"))
        self.dpad_diagonal_lock.toggled.connect(self._on_dpad_option_changed)
        self._dpad_controls["dpad_diagonal_lock"] = self.dpad_diagonal_lock
        options_row.addWidget(self._wrap_dpad_with_mark_revert("dpad_diagonal_lock", self.dpad_diagonal_lock))
        options_row.addStretch(1)

        scroll.setWidget(options_widget)
        outer.addWidget(scroll)

        self.set_layer(self._layer)

    # -- the shared picker --------------------------------------------------

    def _value_for(self, button_id: str, layer: str) -> str | None:
        if self._state is None:
            return None
        return self._state["buttons"].get(layer, {}).get(button_id)

    def _on_diagram_activated(self, button_id: str) -> None:
        """A click or Enter/Space on a diagram hit region -- the diagram
        itself doesn't know about layers or pickers, just that this part
        was activated (see controller_diagram.py's module docstring)."""
        self.diagram.set_highlighted(button_id)
        self._active_button = button_id
        value = self._value_for(button_id, self._layer)

        latch = latch_reason = None
        if self._layer == "default":
            if button_id in BUTTON_TABLE_SLOTS:
                continuous = (self._state or {}).get("continuous_trigger", {})
                latch = bool(continuous.get(button_id))
            else:
                latch_reason = _LATCH_UNSUPPORTED_REASON

        was_text = None
        if (self._layer, button_id) in self._touched:
            baseline = self._loaded_buttons.get(self._layer, {}).get(button_id)
            was_text = f"was {keycode_display_text(baseline)}"

        self._picker.open_for(
            self.diagram.hotspot_for(button_id),
            value,
            known=is_known_keycode(value),
            latch=latch,
            latch_reason=latch_reason,
            was_text=was_text,
        )
        # The picker's Latch checkbox is one shared widget now, not one
        # per button -- without this it would keep announcing "Latch" with
        # no button context to a screen reader, where the old per-row
        # checkbox said "RB, Latch".
        label = _BUTTON_LABELS.get(button_id, button_id.upper())
        self._picker.latch_checkbox.setAccessibleName(f"{label}, Latch")

    def _on_code_chosen(self, value) -> None:
        if self._active_button is None or self._state is None:
            return
        layer_dict = self._state["buttons"].setdefault(self._layer, {})
        # Store the explicit value (including None for a deliberate reset)
        # rather than popping the key -- 2026-09-17's real bug, see the
        # module docstring.
        layer_dict[self._active_button] = value
        self._mark_button_touched(self._layer, self._active_button, value)
        self._refresh_diagram_bindings()
        self.changed.emit()

    def _mark_button_touched(self, layer: str, button_id: str, value: str | None) -> None:
        path = ("buttons", layer, button_id)
        baseline = self._loaded_buttons.get(layer, {}).get(button_id)
        if value == baseline:
            # REAL BUG, found 2026-10-26 (hardware test):
            # manually picking a button back to its originally-loaded
            # binding (not clicking Revert) left the diagram's
            # "(unwritten)" suffix and the draft ledger both still
            # claiming an outstanding edit, even though Write correctly
            # found nothing left to do. Treat landing back on the
            # baseline as an implicit revert -- including picking
            # "(Default)" back to a genuinely-already-unbound baseline
            # (both sides None).
            self._touched.discard((layer, button_id))
            self.fieldReverted.emit(path)
            return
        self._touched.add((layer, button_id))
        field = BUTTON_FIELDS[layer][button_id]
        # A chosen None means "declared: unbind this," Intent.CLEAR -- not
        # raw None, which ButtonFieldSpec.plan_operation() wouldn't
        # recognise as the clear sentinel (same mapping motion_view.py's
        # keycode fields use, same reasoning).
        desired = Intent.CLEAR if value is None else value
        self.fieldTouched.emit(path, field, desired, self._profile)

    def revert_path(self, path: tuple) -> bool:
        """ReviewSheet's own per-row Revert link -- see
        VibrationView.revert_path()'s identical reasoning. Covers both
        ledgers this page owns: `("buttons", layer, button_id)` for a
        binding, `(setting,)` for a D-pad option. Same "doesn't need
        self._active_button" reasoning as revert_all()."""
        if self._state is None:
            return False
        if len(path) == 3 and path[0] == "buttons":
            _, layer, button_id = path
            if (layer, button_id) not in self._touched:
                return False
            baseline = self._loaded_buttons.get(layer, {}).get(button_id)
            self._state["buttons"].setdefault(layer, {})[button_id] = baseline
            self._touched.discard((layer, button_id))
            self.fieldReverted.emit(path)
            self._refresh_diagram_bindings()
            self.changed.emit()
            return True
        if len(path) == 1 and path[0] in self._dpad_touched:
            self._revert_dpad_setting(path[0])
            return True
        return False

    def revert_all(self) -> None:
        """Scope-level "Discard changes": both ledgers this page owns
        (per-button bindings and the D-pad options), same reasoning as
        VibrationView.revert_all(). Unlike _on_revert_requested(), this
        doesn't go through self._active_button -- a touched button whose
        picker isn't currently open still needs reverting, and the
        picker (a modal popover) can't be open while this runs anyway."""
        if self._state is None:
            return
        for layer, button_id in list(self._touched):
            baseline = self._loaded_buttons.get(layer, {}).get(button_id)
            self._state["buttons"].setdefault(layer, {})[button_id] = baseline
            self._touched.discard((layer, button_id))
            self.fieldReverted.emit(("buttons", layer, button_id))
        for setting in list(self._dpad_touched):
            self._revert_dpad_setting(setting)
        self._refresh_diagram_bindings()
        self.changed.emit()

    def _on_revert_requested(self) -> None:
        if self._active_button is None or self._state is None:
            return
        layer, button_id = self._layer, self._active_button
        baseline = self._loaded_buttons.get(layer, {}).get(button_id)
        self._state["buttons"].setdefault(layer, {})[button_id] = baseline
        self._touched.discard((layer, button_id))
        self._refresh_diagram_bindings()
        self.fieldReverted.emit(("buttons", layer, button_id))
        self.changed.emit()

    def _on_latch_toggled(self, checked: bool) -> None:
        if self._active_button is None or self._state is None:
            return
        continuous = self._state.setdefault("continuous_trigger", {})
        continuous[self._active_button] = checked
        self.changed.emit()

    def _on_dpad_option_changed(self, *_: object) -> None:
        if self._state is None:
            return
        self._state["dpad_diagonal_lock"] = self.dpad_diagonal_lock.isChecked()
        self._state["swap_stick_dpad"] = self.swap_stick_dpad.isChecked()
        self.changed.emit()

    def _wrap_dpad_with_mark_revert(self, setting: str, control: QWidget) -> QWidget:
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
        revert_btn.clicked.connect(lambda _c=False, s=setting: self._revert_dpad_setting(s))
        row.addWidget(revert_btn)
        self._dpad_was_labels[setting] = was_label
        self._dpad_revert_buttons[setting] = revert_btn
        self._dpad_row_widgets[setting] = row_widget
        return row_widget

    def _mark_dpad_touched(self, setting: str) -> None:
        control = self._dpad_controls[setting]
        value = control.isChecked()
        baseline = bool(self._dpad_loaded.get(setting))
        if value == baseline:
            # Same implicit-revert fix as _mark_button_touched() above.
            self._dpad_touched.discard(setting)
            control.set_edited(False)
            self._dpad_was_labels[setting].setVisible(False)
            self._dpad_revert_buttons[setting].setVisible(False)
            self.fieldReverted.emit((setting,))
            return
        self._dpad_touched.add(setting)
        control.set_edited(True)
        self._dpad_was_labels[setting].setText(f"was {'On' if baseline else 'Off'}")
        self._dpad_was_labels[setting].setVisible(True)
        self._dpad_revert_buttons[setting].setVisible(True)
        self.fieldTouched.emit((setting,), DPAD_FIELDS[setting], value, self._profile)

    def _revert_dpad_setting(self, setting: str) -> None:
        effective = bool(self._dpad_loaded.get(setting))
        control = self._dpad_controls[setting]
        control.blockSignals(True)
        control.setChecked(effective)
        control.blockSignals(False)
        self._dpad_touched.discard(setting)
        control.set_edited(False)
        self._dpad_was_labels[setting].setVisible(False)
        self._dpad_revert_buttons[setting].setVisible(False)
        self._state[setting] = effective
        self.fieldReverted.emit((setting,))
        self.changed.emit()

    # -- public API -------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self.diagram.set_palette(palette)

    def set_layer(self, layer: str) -> None:
        """Base layer (editable here) or the shared Shift layer's own
        screen (`DIRECTION-A.md` section 3's "Shift layer page") -- the
        D-pad options are profile-scoped, so they have no meaning (and no
        way to be written) on the Shift screen."""
        self._layer = layer
        shift = layer == "shift"
        self.options_separator.setVisible(not shift)
        # Hide the whole wrapped row, not just the checkbox -- see
        # sticks_view.py's identical fix/comment for why hiding only the
        # raw control would leave its "was X"/revert row showing emptily
        # beside it.
        self._dpad_row_widgets["swap_stick_dpad"].setVisible(not shift)
        self._dpad_row_widgets["dpad_diagonal_lock"].setVisible(not shift)
        self._refresh_diagram_bindings()

    def _refresh_diagram_bindings(self) -> None:
        """Feed the diagram's callouts from whichever layer is showing.
        `keycode_display_text()` is the same read-only wording Overview's
        own callouts and the old Shift-reference column used -- a callout
        is inherently read-only now, there's no editable field it could
        drift from.

        S6: a touched-but-unwritten button gets an " (unwritten)" suffix
        -- including one whose desired value is None (a pending unbind),
        which the old `value is not None` filter alone would hide
        entirely, making a pending unbind look identical to an
        already-synced empty slot. KeycodePicker's own "was X"/Revert row
        is the only OTHER place this state is visible, so this suffix is
        what lets a pending edit be seen without opening every picker."""
        layer_values = (self._state or {}).get("buttons", {}).get(self._layer, {})
        bindings = {}
        for button_id, value in layer_values.items():
            touched = (self._layer, button_id) in self._touched
            if value is None and not touched:
                continue
            text = keycode_display_text(value)
            if touched:
                text += " (unwritten)"
            bindings[button_id] = text
        self.diagram.set_bindings(bindings)

    def load_state(self, state: dict) -> None:
        self._state = state
        self._profile = state.get("controller_slot") or 1
        self._touched = set()
        self._loaded_buttons = copy.deepcopy(state.get("buttons", {}))
        self._refresh_diagram_bindings()
        self.swap_stick_dpad.blockSignals(True)
        self.swap_stick_dpad.setChecked(bool(state.get("swap_stick_dpad")))
        self.swap_stick_dpad.blockSignals(False)
        self.dpad_diagonal_lock.blockSignals(True)
        self.dpad_diagonal_lock.setChecked(bool(state.get("dpad_diagonal_lock")))
        self.dpad_diagonal_lock.blockSignals(False)
        self._dpad_touched = set()
        self._dpad_loaded = {
            "swap_stick_dpad": state.get("swap_stick_dpad"),
            "dpad_diagonal_lock": state.get("dpad_diagonal_lock"),
        }
        for setting, control in self._dpad_controls.items():
            control.set_edited(False)
            self._dpad_was_labels[setting].setVisible(False)
            self._dpad_revert_buttons[setting].setVisible(False)
