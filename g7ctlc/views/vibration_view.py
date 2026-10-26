"""Vibrations tab: grip/trigger levels and per-side trigger force/sync flags.

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): the four
levels are this page's vertical slice onto the real per-field draft
model -- `fieldTouched`/`fieldReverted` replace this view's own private
`_sliders_touched` set as the thing MainWindow's `DesiredDraft` ledger
listens to, and each row gets a real "was X%" mark plus a revert
button, not just the `SegmentedControl.set_edited()` dynamic property
(still wired, for its accessible-name suffix and as a future paint
hook, but on its own it isn't the visible mark DESIGN-SPEC.md section 4
item 5 asks for). **Deliberately not migrated yet**: the Force/Sync
flag checkboxes. They're a `CoupledFieldSpec` (one wire byte, two
state-dict fields) and `pyg7.workflow`'s prepare/execute pair -- tested
and committed this session -- only exercises plain `FieldSpec`/
`ButtonFieldSpec` intents; teaching it to group two `ApprovedIntent`s
into one coupled write is a real design question (same shape Track S's
own S3 flagged for `CoupledFieldSpec` itself) that deserves its own
pass, not a rushed addition on top of code that was just hardened.
Checkboxes still write through the old whole-state Sync Now path only.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyg7.field_spec import VIBRATION_LEVEL_FIELDS
from pyg7.vibration import LEVELS

from ..checkbox import Checkbox
from ..segmented_control import SegmentedControl

LEVEL_SETTINGS = [
    ("left_grip", "Left Grip"), ("right_grip", "Right Grip"),
    ("left_trigger", "Left Trigger"), ("right_trigger", "Right Trigger"),
]

_LEVEL_SEGMENTS = [(str(lvl), str(lvl)) for lvl in LEVELS]


def _nearest_level_index(value: Optional[int]) -> int:
    """Which of LEVELS a value is closest to, for display -- used for both
    the ordinary default (None -> the middle level) and for a value read
    from state that isn't one of the five (an older export, hand-edited
    JSON, or CLI scripting predating this restriction). Display only:
    doesn't touch the state dict, so an off-scale value stays exactly what
    it was until this control is actually moved -- Sync then rejects it
    with a clear error (see pyg7.vibration._level) rather than the GUI
    silently rewriting a file it didn't create."""
    if value is None:
        value = LEVELS[len(LEVELS) // 2]
    return min(range(len(LEVELS)), key=lambda i: abs(LEVELS[i] - value))


class VibrationView(QWidget):
    changed = pyqtSignal()
    # path, FieldSpec, desired value, profile -- MainWindow's DesiredDraft
    # ledger listens to this, not to `changed` (S6: "touched-intent ledger
    # independent of widgets," DESIGN-SPEC.md 10.2 item 2). Only the four
    # plain levels emit this; see the module docstring for why the flags
    # don't yet.
    fieldTouched = pyqtSignal(tuple, object, object, int)
    fieldReverted = pyqtSignal(tuple)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
        # Keys whose level control has genuinely been changed since the
        # last load_state() -- see _on_edit()'s own comment for why this
        # can't just be "whatever every control currently shows."
        self._sliders_touched: set = set()
        # The level values as of the last load_state() -- purely for this
        # view's own "was X%" mark text; MainWindow's DesiredDraft (built
        # from an ObservedSnapshot) is the authoritative record, this is
        # just display convenience local to this page.
        self._loaded_levels: dict[str, Optional[int]] = {}
        self._was_labels: dict[str, QLabel] = {}
        self._revert_buttons: dict[str, QPushButton] = {}
        # Modest content today, but QTabWidget sizes the whole main window's
        # minimum height to fit the LARGEST tab page, not just whichever is
        # visible -- wrapped for consistency with every other tab so this
        # can't quietly become the new bottleneck as it grows. See
        # TriggersView's __init__ for the incident that made this explicit.
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        levels_box = QGroupBox("Vibration Levels")
        form = QFormLayout(levels_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        self.sliders: dict[str, SegmentedControl] = {}
        for key, label in LEVEL_SETTINGS:
            # The stepped-meter SegmentedControl variant (DIRECTION-A.md
            # section 5), not a QSlider: exactly five real stops, not a
            # continuous range snapped after the fact (which still lets a
            # fast drag release land in between on some Qt styles -- the
            # reason the old QSlider used an index range rather than 0-100
            # in the first place). `self.sliders` keeps its old name --
            # still "which control holds this level", regardless of widget
            # type; renaming it isn't this phase's job.
            control = SegmentedControl(_LEVEL_SEGMENTS, meter=True)
            control.setToolTip(
                f"{label} rumble intensity: {', '.join(str(lvl) for lvl in LEVELS)} -- "
                "the same five values GameSir Nexus offers. Not arbitrary: "
                "felt-tested on hardware, values below 25 produced no "
                "detectable vibration."
            )
            # Order matters -- see settings_view.py's identical fix/comment
            # for why the touched-marker must connect before _on_edit.
            control.selectionChanged.connect(lambda _v, k=key: self._mark_slider_touched(k))
            control.selectionChanged.connect(self._on_edit)
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
            revert_btn.clicked.connect(lambda _c=False, k=key: self._revert_level(k))
            row.addWidget(revert_btn)
            row.addStretch(1)
            form.addRow(label, row_widget)
            self.sliders[key] = control
            self._was_labels[key] = was_label
            self._revert_buttons[key] = revert_btn
        outer.addWidget(levels_box)

        flags_box = QGroupBox("Trigger Vibration Flags")
        flags_form = QFormLayout(flags_box)
        flags_form.setVerticalSpacing(10)
        flags_form.setHorizontalSpacing(14)
        self.checks = {}
        for side in ("left", "right"):
            force = Checkbox("Force")
            force.setToolTip(
                "GameSir Nexus's own trigger vibration flags -- the exact "
                "behavioral difference between Force and Sync isn't "
                "independently confirmed."
            )
            sync = Checkbox("Sync")
            sync.setToolTip(force.toolTip())
            force.toggled.connect(self._on_edit)
            sync.toggled.connect(self._on_edit)
            row = QHBoxLayout()
            row.addWidget(force)
            row.addWidget(sync)
            container = QWidget()
            container.setLayout(row)
            flags_form.addRow(f"{side.capitalize()} Trigger", container)
            self.checks[f"{side}_trigger_force"] = force
            self.checks[f"{side}_trigger_sync"] = sync
        outer.addWidget(flags_box)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def load_state(self, state: dict) -> None:
        self._state = state
        self._loading = True
        try:
            vib = state["vibration"]
            for key, control in self.sliders.items():
                control.set_value(str(LEVELS[_nearest_level_index(vib.get(key))]))
                control.set_edited(False)
                self._was_labels[key].setVisible(False)
                self._revert_buttons[key].setVisible(False)
            for key, check in self.checks.items():
                check.setChecked(bool(vib.get(key)))
        finally:
            self._loading = False
        # Reset AFTER loading, not before -- see settings_view.py's
        # identical fix/comment for the same reasoning.
        self._sliders_touched = set()
        self._loaded_levels = {key: vib.get(key) for key in self.sliders}

    def _mark_slider_touched(self, key: str) -> None:
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): _on_edit() used to
        # unconditionally re-derive EVERY vibration key from its control's
        # CURRENT position on any edit anywhere in this tab -- toggling an
        # unrelated Force/Sync checkbox (or moving a DIFFERENT level
        # control) rewrote every other control's exact loaded value with
        # its nearest of only five coarse stops, even though
        # _nearest_level_index()'s own docstring promises an off-scale
        # value "stays exactly what it was until this control is actually
        # moved." Only the control whose own signal fires for a real
        # reason (guarded by _loading) gets marked -- matches
        # settings_view.py's identical fix for the same pattern.
        if self._loading:
            return
        self._sliders_touched.add(key)
        control = self.sliders[key]
        control.set_edited(True)
        observed = self._loaded_levels.get(key)
        self._was_labels[key].setText("was Unknown" if observed is None else f"was {observed}%")
        self._was_labels[key].setVisible(True)
        self._revert_buttons[key].setVisible(True)
        profile = (self._state or {}).get("controller_slot") or 1
        self.fieldTouched.emit(("vibration", key), VIBRATION_LEVEL_FIELDS[key], int(control.value()), profile)

    def _revert_level(self, key: str) -> None:
        if self._state is None:
            return
        observed = self._loaded_levels.get(key)
        control = self.sliders[key]
        self._loading = True  # set_value() must not re-mark this touched
        try:
            control.set_value(str(LEVELS[_nearest_level_index(observed)]))
        finally:
            self._loading = False
        self._sliders_touched.discard(key)
        control.set_edited(False)
        self._was_labels[key].setVisible(False)
        self._revert_buttons[key].setVisible(False)
        self._state["vibration"][key] = observed
        self.fieldReverted.emit(("vibration", key))
        self.changed.emit()

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        vib = self._state["vibration"]
        for key, control in self.sliders.items():
            if key in self._sliders_touched:
                vib[key] = int(control.value())
        for key, check in self.checks.items():
            vib[key] = check.isChecked()
        self.changed.emit()
