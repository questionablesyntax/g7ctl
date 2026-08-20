"""Vibrations tab: grip/trigger levels and per-side trigger force/sync flags."""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pyg7.vibration import LEVELS

LEVEL_SETTINGS = [
    ("left_grip", "Left Grip"), ("right_grip", "Right Grip"),
    ("left_trigger", "Left Trigger"), ("right_trigger", "Right Trigger"),
]


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


def _level_row() -> tuple[QSlider, QWidget]:
    # Range is an INDEX into LEVELS, not the level itself -- the only way to
    # make a slider land on exactly five stops is to give it exactly five
    # positions, rather than a 0-100 range with drag snapped after the
    # fact (which still lets a fast drag release land in between on some
    # Qt styles). See LEVELS' own comment for why five and not 101: below
    # 25 nothing was felt on hardware, and 25/50/75/100 are each distinctly
    # stronger with no plateau -- matches what GameSir Nexus itself offers.
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, len(LEVELS) - 1)
    slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    slider.setTickInterval(1)
    slider.setPageStep(1)
    value_label = QLabel(str(LEVELS[0]))
    value_label.setFixedWidth(30)
    value_label.setStyleSheet("font-weight: 600;")
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda i: value_label.setText(str(LEVELS[i])))
    row = QHBoxLayout()
    row.addWidget(slider, 1)
    row.addWidget(value_label)
    container = QWidget()
    container.setLayout(row)
    return slider, container


class VibrationView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
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
        self.sliders = {}
        for key, label in LEVEL_SETTINGS:
            slider, container = _level_row()
            slider.setToolTip(
                f"{label} rumble intensity: {', '.join(str(lvl) for lvl in LEVELS)} -- "
                "the same five values GameSir Nexus offers. Not arbitrary: "
                "felt-tested on hardware, values below 25 produced no "
                "detectable vibration."
            )
            slider.valueChanged.connect(self._on_edit)
            form.addRow(label, container)
            self.sliders[key] = slider
        outer.addWidget(levels_box)

        flags_box = QGroupBox("Trigger Vibration Flags")
        flags_form = QFormLayout(flags_box)
        flags_form.setVerticalSpacing(10)
        flags_form.setHorizontalSpacing(14)
        self.checks = {}
        for side in ("left", "right"):
            force = QCheckBox("Force")
            force.setToolTip(
                "GameSir Nexus's own trigger vibration flags -- the exact "
                "behavioral difference between Force and Sync isn't "
                "independently confirmed."
            )
            sync = QCheckBox("Sync")
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
            for key, slider in self.sliders.items():
                slider.setValue(_nearest_level_index(vib.get(key)))
            for key, check in self.checks.items():
                check.setChecked(bool(vib.get(key)))
        finally:
            self._loading = False

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        vib = self._state["vibration"]
        for key, slider in self.sliders.items():
            vib[key] = LEVELS[slider.value()]
        for key, check in self.checks.items():
            vib[key] = check.isChecked()
        self.changed.emit()
