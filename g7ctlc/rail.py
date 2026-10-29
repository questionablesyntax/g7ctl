"""Rail, A3 of the redesign. The left navigation column: the four-slot
profile switch, the "Profile N settings" and "Shared by all profiles"
groups, and the footer (Read, Snapshots, Help, App preferences) --
`DIRECTION-A.md` section 3's IA, grouped by scope rather than by module.

Layout only (`IMPLEMENTATION-PLAN.md` A3): this file owns navigation and
scope grouping, nothing about what a page shows once selected, and
nothing about the device-facing confirmation/gating logic -- MainWindow
still owns that, this just gives it new widgets to drive.

Nav items are one exclusive `QButtonGroup` across both scope groups --
there is exactly one current page at a time regardless of which group it
belongs to, the same "which tab is open" semantics the old `QTabWidget`
had, just laid out by scope instead of in one flat row.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from g7ctlc.icon_loader import LucideIconLoader
from g7ctlc.palette import Palette
from g7ctlc.segmented_control import SegmentedControl

# Page keys, in rail order. "shift" and "dock" are the shared-scope pair;
# everything else is per-profile. Kept as plain strings, not an enum --
# MainWindow's QStackedWidget indexes pages by these same keys via a dict,
# and nothing outside this module needs to branch on a closed type.
PROFILE_PAGE_KEYS = ("buttons", "sticks", "triggers", "motion", "vibration", "profile_settings")
SHARED_PAGE_KEYS = ("shift", "dock")

_PROFILE_PAGE_LABELS = {
    "buttons": "Buttons", "sticks": "Sticks", "triggers": "Triggers",
    "motion": "Motion", "vibration": "Vibration", "profile_settings": "Profile settings",
}
_SHARED_PAGE_LABELS = {"shift": "Shift layer", "dock": "Dock"}


class Rail(QWidget):
    profileChanged = pyqtSignal(object)  # 1-4
    pageRequested = pyqtSignal(str)      # one of PROFILE_PAGE_KEYS/SHARED_PAGE_KEYS
    readRequested = pyqtSignal()
    importRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    appPreferencesRequested = pyqtSignal()

    def __init__(self, palette: Palette, icon_loader: LucideIconLoader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rail")
        self.setAccessibleName("Navigation")
        self._icon_loader = icon_loader

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        layout.addWidget(self._build_profile_heading(palette, icon_loader))
        self.profile_switch = SegmentedControl([(str(n), str(n)) for n in (1, 2, 3, 4)])
        self.profile_switch.selectionChanged.connect(self._on_profile_switch_changed)
        layout.addWidget(self.profile_switch)
        self.on_controller_marker = self._build_marker(icon_loader, palette)
        layout.addWidget(self.on_controller_marker)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}

        self.profile_heading = QLabel("Profile 1 settings", self)
        self.profile_heading.setProperty("role", "rail-heading")
        layout.addWidget(self.profile_heading)
        for key in PROFILE_PAGE_KEYS:
            layout.addWidget(self._build_nav_button(key, _PROFILE_PAGE_LABELS[key]))

        shared_heading = self._build_shared_heading(icon_loader, palette)
        layout.addWidget(shared_heading)
        for key in SHARED_PAGE_KEYS:
            layout.addWidget(self._build_nav_button(key, _SHARED_PAGE_LABELS[key]))

        layout.addStretch(1)
        layout.addLayout(self._build_footer(icon_loader, palette))

        self._nav_buttons["buttons"].setChecked(True)

    # -- profile switch ---------------------------------------------------

    def _build_profile_heading(self, palette: Palette, icon_loader: LucideIconLoader) -> QWidget:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        icon = icon_loader.icon("gamepad-2", 16, "text_secondary", palette)
        self._profile_heading_icon_label = QLabel(row)
        self._profile_heading_icon_label.setPixmap(icon.pixmap(16, 16))
        row_layout.addWidget(self._profile_heading_icon_label)
        label = QLabel("Profile", row)
        label.setProperty("role", "rail-heading")
        row_layout.addWidget(label)
        row_layout.addStretch(1)
        return row

    def _build_marker(self, icon_loader: LucideIconLoader, palette: Palette) -> QWidget:
        """"on controller" marker, never colour alone (`DIRECTION-A.md`
        section 5's `ProfileSwitch`). One line beneath the whole switch
        rather than positioned under the exact active segment -- the
        latter needs per-segment overlay geometry this phase doesn't
        build; the fact itself (which slot, if any, is physically active)
        is carried either way. Hidden until `set_active_profile()` is
        told."""
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        icon = icon_loader.icon("gamepad-2", 16, "text_secondary", palette)
        self._marker_icon_label = QLabel(row)
        self._marker_icon_label.setPixmap(icon.pixmap(16, 16))
        row_layout.addWidget(self._marker_icon_label)
        self._marker_label = QLabel("", row)
        self._marker_label.setProperty("role", "secondary")
        row_layout.addWidget(self._marker_label)
        row_layout.addStretch(1)
        row.setVisible(False)
        return row

    def set_active_profile(self, slot: int | None) -> None:
        if slot is None:
            self.on_controller_marker.setVisible(False)
            return
        self._marker_label.setText(f"Profile {slot} is on the controller")
        self.on_controller_marker.setVisible(True)

    def _on_profile_switch_changed(self, value: object) -> None:
        if value is None:
            return
        slot = int(value)
        self.profile_heading.setText(f"Profile {slot} settings")
        self.profileChanged.emit(slot)

    def set_profile(self, slot: int) -> None:
        """Reflect a profile chosen elsewhere (e.g. the Shift page
        returning to a real profile) without re-emitting profileChanged --
        same loading-guard reasoning `main_window.py` already used for the
        combo this replaces."""
        self.profile_switch.selectionChanged.disconnect(self._on_profile_switch_changed)
        try:
            self.profile_switch.set_value(str(slot))
        finally:
            self.profile_switch.selectionChanged.connect(self._on_profile_switch_changed)
        self.profile_heading.setText(f"Profile {slot} settings")

    # -- nav ---------------------------------------------------------------

    def _build_shared_heading(self, icon_loader: LucideIconLoader, palette: Palette) -> QWidget:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        icon = icon_loader.icon("layers", 16, "text_secondary", palette)
        self._shared_heading_icon_label = QLabel(row)
        self._shared_heading_icon_label.setPixmap(icon.pixmap(16, 16))
        row_layout.addWidget(self._shared_heading_icon_label)
        label = QLabel("Shared by all profiles", row)
        label.setProperty("role", "rail-heading")
        row_layout.addWidget(label)
        row_layout.addStretch(1)
        return row

    def _build_nav_button(self, key: str, label: str) -> QPushButton:
        button = QPushButton(label, self)
        button.setCheckable(True)
        button.setProperty("role", "rail-item")
        button.setAccessibleName(label)
        self._nav_group.addButton(button)
        self._nav_buttons[key] = button
        button.clicked.connect(lambda _checked=False, k=key: self.pageRequested.emit(k))
        return button

    def set_page_visible(self, key: str, visible: bool) -> None:
        """Hides a nav entry entirely, same intent as the old
        `QTabWidget.setTabVisible` this replaces -- used while the Shift
        layer is selected, matching today's exact behaviour
        (`_apply_view()`'s comment: those categories have no profile
        number that addresses the Shift blob, so they're hidden rather
        than shown and quietly ignored)."""
        self._nav_buttons[key].setVisible(visible)

    def is_page_visible(self, key: str) -> bool:
        """`isHidden()`, not `isVisible()`: this rail is never `.show()`n
        in most tests, and `isVisible()` answers false for every child of
        an unshown top-level regardless of `setVisible()` -- `isHidden()`
        is the one that reflects `set_page_visible()`'s own explicit call."""
        return not self._nav_buttons[key].isHidden()

    def set_edit_count(self, key: str, count: int) -> None:
        """Rail edit count (S6, DESIGN-SPEC.md 10.2 item 2). Appended to
        the nav button's own label text rather than a separate badge
        widget -- `setAccessibleName()` at construction already mirrors
        the same label, so updating both here keeps them in sync without
        a second place to maintain it."""
        label = _PROFILE_PAGE_LABELS.get(key) or _SHARED_PAGE_LABELS.get(key)
        button = self._nav_buttons[key]
        text = f"{label} ({count})" if count else label
        button.setText(text)
        button.setAccessibleName(text)

    def set_current_page(self, key: str) -> None:
        self._nav_buttons[key].setChecked(True)

    def current_page(self) -> str:
        for key, button in self._nav_buttons.items():
            if button.isChecked():
                return key
        return "buttons"

    def set_palette(self, palette: Palette) -> None:
        """Real bug, found in A6's code review (2026-10-22): MainWindow's
        _on_palette_changed() refreshes its QPainter-driven widgets on a
        live theme switch but never called this -- because this never
        existed. Every icon here is a baked palette-tinted pixmap/QIcon,
        same as TrayIcon's own, so a regenerated stylesheet alone (QSS,
        which the text labels do pick up) never reaches them; they kept
        the old palette's tint through a live dark<->light toggle."""
        loader = self._icon_loader
        self._profile_heading_icon_label.setPixmap(
            loader.icon("gamepad-2", 16, "text_secondary", palette).pixmap(16, 16))
        self._marker_icon_label.setPixmap(
            loader.icon("gamepad-2", 16, "text_secondary", palette).pixmap(16, 16))
        self._shared_heading_icon_label.setPixmap(
            loader.icon("layers", 16, "text_secondary", palette).pixmap(16, 16))
        self.read_button.setIcon(loader.icon("refresh-cw", 16, "text_primary", palette))
        self.snapshots_button.setIcon(loader.icon("file-down", 16, "text_primary", palette))
        self.help_button.setIcon(loader.icon("circle-help", 16, "text_primary", palette))
        self._import_action.setIcon(loader.icon("file-up", 16, "text_primary", palette))
        self._export_action.setIcon(loader.icon("file-down", 16, "text_primary", palette))

    def set_nav_enabled(self, enabled: bool) -> None:
        """Gates every nav button together -- mid-sync/read, same as the
        profile switch, Read, Snapshots: a click through any of them must
        not be able to race the in-flight job."""
        for button in self._nav_buttons.values():
            button.setEnabled(enabled)
        self.profile_switch.setEnabled(enabled)

    # -- footer -------------------------------------------------------------

    def _build_footer(self, icon_loader: LucideIconLoader, palette: Palette) -> QVBoxLayout:
        footer = QVBoxLayout()
        footer.setSpacing(4)

        self.read_button = QPushButton("Read from controller", self)
        self.read_button.setIcon(icon_loader.icon("refresh-cw", 16, "text_primary", palette))
        self.read_button.setEnabled(False)
        self.read_button.setToolTip(
            "Read the controller's actual current settings back from it, "
            "overwriting every page here."
        )
        self.read_button.clicked.connect(self.readRequested.emit)
        footer.addWidget(self.read_button)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.snapshots_button = self._build_menu_button(
            "Snapshots", self._build_snapshots_menu(icon_loader, palette),
            icon_loader.icon("file-down", 16, "text_primary", palette))
        row.addWidget(self.snapshots_button)
        self.help_button = self._build_menu_button(
            "Help", QMenu(self), icon_loader.icon("circle-help", 16, "text_primary", palette))
        row.addWidget(self.help_button)
        footer.addLayout(row)

        self.app_preferences_button = QPushButton("App preferences", self)
        self.app_preferences_button.setFlat(True)
        self.app_preferences_button.clicked.connect(self.appPreferencesRequested.emit)
        footer.addWidget(self.app_preferences_button)
        return footer

    def _build_menu_button(self, text: str, menu: QMenu, icon=None) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        if icon is not None:
            button.setIcon(icon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        return button

    def _build_snapshots_menu(self, icon_loader: LucideIconLoader, palette: Palette) -> QMenu:
        menu = QMenu(self)
        self._import_action = menu.addAction(icon_loader.icon("file-up", 16, "text_primary", palette), "Import…")
        self._import_action.setToolTip("Load a previously exported JSON snapshot file")
        self._import_action.triggered.connect(self.importRequested.emit)
        self._export_action = menu.addAction(icon_loader.icon("file-down", 16, "text_primary", palette), "Export…")
        self._export_action.setToolTip("Save the current state to a JSON snapshot file")
        self._export_action.triggered.connect(self.exportRequested.emit)
        return menu

    def wire_help_menu(self, build: Callable[[QMenu], None]) -> None:
        """MainWindow builds the actual About/On-Device Features/Report an
        Issue actions (it owns their handlers) -- this just hands back the
        menu this rail already created, so there's one Help menu, not two."""
        build(self.help_button.menu())
