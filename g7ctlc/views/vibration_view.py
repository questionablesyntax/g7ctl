"""Vibrations tab: grip/trigger levels and per-side trigger force/sync flags."""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
        # Keys whose level control has genuinely been changed since the
        # last load_state() -- see _on_edit()'s own comment for why this
        # can't just be "whatever every control currently shows."
        self._sliders_touched: set = set()
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
            form.addRow(label, control)
            self.sliders[key] = control
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
            for key, check in self.checks.items():
                check.setChecked(bool(vib.get(key)))
        finally:
            self._loading = False
        # Reset AFTER loading, not before -- see settings_view.py's
        # identical fix/comment for the same reasoning.
        self._sliders_touched = set()

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
        if not self._loading:
            self._sliders_touched.add(key)

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
