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
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

BRIGHTNESS_OPTIONS = [(0, "Off"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]


def _nearest_brightness_index(value: Optional[int]) -> int:
    """Which of BRIGHTNESS_OPTIONS a value is closest to, for display --
    mirrors vibration_view.py's _nearest_level_index() for the identical
    problem: pyg7/dock_settings.py and the CLI's `dock-set brightness`
    accept any 0-100 value, but this combo only offers five discrete
    stops. Display only: doesn't touch the state dict, so an off-scale
    value stays exactly what it was until this control is actually
    edited."""
    if value is None:
        value = 100
    return min(
        range(len(BRIGHTNESS_OPTIONS)),
        key=lambda i: abs(BRIGHTNESS_OPTIONS[i][0] - value),
    )


class SettingsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._state = None
        # True once the user has genuinely picked a brightness -- see
        # _on_edit()'s own comment for why this can't just be "whatever
        # the combo currently shows."
        self._brightness_touched = False
        # Modest content today, but QTabWidget sizes the whole main window's
        # minimum height to fit the LARGEST tab page, not just whichever is
        # visible -- wrapped for consistency with every other tab so this
        # can't quietly become the new bottleneck as it grows. See
        # TriggersView's __init__ for the incident that made this explicit.
        page = QWidget()
        outer = QVBoxLayout(page)
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
        # Order matters: Qt fires same-signal slots in connection order, and
        # _on_edit() below only writes brightness into state when
        # _brightness_touched is already True. REAL BUG, found 2026-09-18
        # (Sol's bug-sweep): this used to connect _on_edit first, so the
        # FIRST edit after a load ran it while the flag was still False --
        # the combo showed the new value but state silently kept the old
        # one until a second edit. _mark_brightness_touched must run first.
        self.brightness.currentIndexChanged.connect(self._mark_brightness_touched)
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
            self.brightness.setCurrentIndex(_nearest_brightness_index(state.get("dock_led_brightness")))
            self.auto_on_off.setChecked(bool(state.get("dock_auto_on_off")))
        finally:
            self._loading = False
        # Reset AFTER loading, not before -- a fresh load's own display
        # selection (however it landed) must never count as "the user
        # touched it." currentIndexChanged fires during the setCurrentIndex()
        # above too, but _mark_brightness_touched() already ignores that
        # under the _loading guard; this reset also covers a stale True
        # left over from a previous load/edit cycle on this same widget.
        self._brightness_touched = False

    def _mark_brightness_touched(self, *_args: object) -> None:
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): _on_edit() used to
        # unconditionally re-derive dock_led_brightness from
        # self.brightness.currentData() on ANY edit, including toggling
        # auto_on_off, which has nothing to do with brightness. The combo
        # only offers five coarse stops (_nearest_brightness_index() picks
        # the closest one for DISPLAY), but pyg7/dock_settings.py and the
        # CLI accept any 0-100 value -- so an off-scale exact value (e.g.
        # 43%) got silently rounded to its nearest stop (e.g. 50%) the
        # moment an unrelated checkbox was toggled, even though the
        # combo's own tooltip and _nearest_brightness_index()'s own
        # docstring both promise it stays exact "until this control is
        # actually edited." This flag is what actually keeps that promise:
        # only set when brightness's own signal fires for a real reason
        # (guarded by _loading, same as load()'s own guard elsewhere in
        # this codebase), not on every edit anywhere in this tab.
        if not self._loading:
            self._brightness_touched = True

    def _on_edit(self, *_: object) -> None:
        if self._loading or self._state is None:
            return
        if self._brightness_touched:
            self._state["dock_led_brightness"] = self.brightness.currentData()
        self._state["dock_auto_on_off"] = self.auto_on_off.isChecked()
        self.changed.emit()
