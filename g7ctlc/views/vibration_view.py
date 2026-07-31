"""Vibrations tab: grip/trigger levels and per-side trigger force/sync flags."""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

LEVEL_SETTINGS = [
    ("left_grip", "Left Grip"), ("right_grip", "Right Grip"),
    ("left_trigger", "Left Trigger"), ("right_trigger", "Right Trigger"),
]


def _level_row() -> tuple[QSlider, QWidget]:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    value_label = QLabel("50")
    value_label.setFixedWidth(30)
    value_label.setStyleSheet("font-weight: 600;")
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        levels_box = QGroupBox("Vibration Levels")
        form = QFormLayout(levels_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        self.sliders = {}
        for key, label in LEVEL_SETTINGS:
            slider, container = _level_row()
            slider.setToolTip(f"{label} rumble intensity, 0-100.")
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

    def load_state(self, state: dict) -> None:
        self._state = state
        self._loading = True
        try:
            vib = state["vibration"]
            for key, slider in self.sliders.items():
                slider.setValue(vib.get(key) if vib.get(key) is not None else 50)
            for key, check in self.checks.items():
                check.setChecked(bool(vib.get(key)))
        finally:
            self._loading = False

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        vib = self._state["vibration"]
        for key, slider in self.sliders.items():
            vib[key] = slider.value()
        for key, check in self.checks.items():
            vib[key] = check.isChecked()
        self.changed.emit()
