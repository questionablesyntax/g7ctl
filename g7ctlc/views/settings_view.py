"""Settings tab: Dock LED Brightness and Auto On/Off -- genuinely global,
device-wide settings (not per-profile, see pyg7/dock_settings.py),
found in Nexus's own top-level "Settings" section rather than a
per-category tab.
"""
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

BRIGHTNESS_OPTIONS = [(0, "Off"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]


class SettingsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        dock_box = QGroupBox("Dock")
        form = QFormLayout(dock_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self.brightness = QComboBox()
        for percent, label in BRIGHTNESS_OPTIONS:
            self.brightness.addItem(label, percent)
        self.brightness.setToolTip(
            "Dock LED brightness. Device-wide -- not per-profile, unlike "
            "every other tab in this app."
        )
        self.brightness.currentIndexChanged.connect(self._on_edit)
        form.addRow("LED Brightness", self.brightness)

        self.auto_on_off = QCheckBox("Auto On/Off (with docking/undocking)")
        self.auto_on_off.setToolTip(
            "Automatically power the dock's LED on when a controller docks "
            "and off when it undocks. Device-wide -- not per-profile."
        )
        self.auto_on_off.toggled.connect(self._on_edit)
        form.addRow("", self.auto_on_off)

        outer.addWidget(dock_box)
        outer.addStretch(1)

    def load_state(self, state: dict) -> None:
        self._state = state
        self._loading = True
        try:
            idx = self.brightness.findData(state.get("dock_led_brightness") if state.get("dock_led_brightness") is not None else 100)
            # Falls back to the last item (100%) -- the confirmed factory
            # default (see PROTOCOL.md "Dock Settings"), not just "whatever
            # happens to be last in BRIGHTNESS_OPTIONS."
            self.brightness.setCurrentIndex(idx if idx >= 0 else self.brightness.count() - 1)
            self.auto_on_off.setChecked(bool(state.get("dock_auto_on_off")))
        finally:
            self._loading = False

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        self._state["dock_led_brightness"] = self.brightness.currentData()
        self._state["dock_auto_on_off"] = self.auto_on_off.isChecked()
        self.changed.emit()
