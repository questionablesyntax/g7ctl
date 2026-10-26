"""Main window: ownership bar, rail navigation, Import/Export, Sync Now,
Read from Device.

A3 of the redesign (`IMPLEMENTATION-PLAN.md` track A): the shell is new
(`OwnershipBar`, `Rail`, a `QStackedWidget` replacing the old
`QTabWidget`), but the confirmation/gating/race-fix logic below is
"re-wired to the new widgets, not redesigned" -- every method that used
to poke `self.tabs`/`self.profile_combo`/`self.import_export_btn` etc.
still exists with the same name and the same bug-fix history in its
comments; only which widget it reaches has changed. Pages themselves
(Buttons/Sticks/Triggers/Motion/Vibration/Dock) are still today's
un-reskinned views -- that's A4's job.
"""
import copy
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, QEvent, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QHideEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7 import state as state_mod
from pyg7.field_spec import REPORT_RATE_FIELD, Intent

from . import help_content
from .draft import DesiredDraft, ObservedSnapshot
from .empty_state import EmptyState
from .hatch_overlay import HatchOverlay
from .inline_notice import InlineNotice
from .modal_overlay import ModalOverlayBase
from .ownership_bar import OwnershipBar
from .qss import generate_stylesheet
from .rail import PROFILE_PAGE_KEYS, SHARED_PAGE_KEYS, Rail
from .review_sheet import ReviewSheet
from .segmented_control import SegmentedControl
from .theme_runtime import ThemeController
from .views.buttons_view import ButtonsView
from .views.motion_view import MotionView
from .views.overview_view import OverviewView
from .views.settings_view import SettingsView
from .views.sticks_view import SticksView
from .views.triggers_view import TriggersView
from .views.vibration_view import VibrationView

_GEOMETRY_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "window_geometry.dat"
)

# Sentinel for the Shift layer's rail entry. Deliberately not 5: the
# Shift layer is not a fifth profile, and anything that mistakes it for
# one would send profile=5 somewhere that expects 1-4.
SHIFT_VIEW = "shift"

_LEGACY_PROFILES_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "profiles"
)

# How long the window has to stay unfocused before the controller is handed
# back. Debounce, not politeness: a modal QMessageBox (the Sync Now / Read
# confirmations) deactivates its parent window, so releasing the instant
# focus drops would release the device exactly while the user is confirming
# a write. The delay plus the "is any window of ours active" check in
# _auto_release_if_still_unfocused() covers that, and stops a quick
# alt-tab-and-back from costing a full release/reconnect cycle.
_AUTO_RELEASE_DELAY_MS = 400

# Human scope labels for ReviewSheet's own subtitle line -- the one
# place a scope string needs a reader-facing name rather than a dict key.
_SCOPE_LABELS = {
    "vibration": "Vibration", "dock": "Dock (shared by every profile)",
    "triggers": "Triggers", "sticks": "Sticks", "motion": "Motion",
    "buttons": "Buttons", "profile_settings": "Profile Settings",
}


class MainWindow(QMainWindow):
    release_toggled = pyqtSignal(bool)  # True = release to XInput, False = reconnect
    sync_requested = pyqtSignal(dict)   # the state dict to push to the device
    # the controller_slot to read bindings back from, and whether to force a
    # real dock-settings read regardless of DeviceWatcher's own _dock_known
    # optimization -- see request_read_from_device()'s own comment.
    read_requested = pyqtSignal(int, bool)
    # Emitted every time self._syncing changes -- so anything outside this
    # class (the tray icon's own Release Device action, currently) can stay
    # in step without reaching into a private attribute.
    syncing_changed = pyqtSignal(bool)
    # S6's fast path (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track
    # S/DESIGN-SPEC.md 10.3): approved intents, the baseline state dict they
    # were drafted against, and the connection generation captured when
    # they were. DeviceWatcher.request_execute() is this signal's one
    # connection (app.py) -- same "plain closure, not a bound method"
    # reasoning as sync_requested/read_requested.
    execute_requested = pyqtSignal(list, dict, int)
    # The ReviewSheet's own Write action, after needs_review() escalated
    # -- DeviceWatcher.request_execute_reviewed() is this signal's one
    # connection, same reasoning as execute_requested above. Carries the
    # (possibly narrower, if rows were reverted on their own page while
    # the sheet was open) PreparedJob straight through -- no second
    # read/prepare.
    execute_reviewed_requested = pyqtSignal(object, int, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("G7 Control Center")
        self.resize(1120, 760)  # DIRECTION-A.md section 3's default shell size
        self._restore_geometry()

        self._theme = ThemeController(self)
        self._apply_stylesheet()
        self._theme.paletteChanged.connect(self._on_palette_changed)

        self._state = state_mod.default_state_dict("Current State")
        self._dirty = False
        self._connection_state = "disconnected"
        self._firmware = None
        self._active_profile = None
        self._syncing = False  # true while either a sync-to or read-from-device job is in flight
        # Set only when *we* released the device because the window lost
        # focus, so refocusing knows to reconnect. Kept distinct from the
        # Release Device button: an explicit release has to survive the
        # window being focused again, and this must never undo one.
        self._auto_released = False
        self._auto_release_timer = QTimer(self)
        self._auto_release_timer.setSingleShot(True)
        self._auto_release_timer.setInterval(_AUTO_RELEASE_DELAY_MS)
        self._auto_release_timer.timeout.connect(self._auto_release_if_still_unfocused)
        # True only once self._state has been confirmed against real hardware
        # (a successful Read from Device) or an explicit user Import -- never
        # true for the untouched default_state_dict() scaffold. Gates Sync
        # Now: without this, a freshly-launched app (or one where every read
        # attempt has failed) could push entirely untested blank Sticks/
        # Triggers/Vibration defaults straight to the device on an accidental
        # click, with no prior safety net -- exactly what happened once
        # already (2026-07-27) after ProfileStore's "always start from a
        # previously-synced real profile" guarantee was removed with nothing
        # in its place.
        self._state_confirmed = False
        # S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S):
        # Vibration's four levels are this app's first page on the real
        # per-field draft model -- see draft.py's own module docstring.
        # One DesiredDraft here, not one per page yet; every other page
        # still writes only through the old whole-state Sync Now path.
        self._vibration_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Dock's draft -- the first SHARED-scope one (not per-profile).
        # DESIGN-SPEC.md 10.1 #5: "shared Shift and Dock draft rows survive
        # a profile switch" -- unlike self._vibration_draft, nothing here
        # resets this on a profile switch; only on a real read/import with
        # nothing outstanding, or a reconnect (see set_read_finished()'s
        # own guard and set_connection_generation()).
        self._dock_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Triggers' draft -- the first PER-SIDE one, but still per-profile
        # scope like Vibration's (not shared like Dock's): a profile switch
        # discards it, same reasoning _reset_vibration_draft() documents.
        self._triggers_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Sticks' draft -- same per-side/per-profile shape as Triggers'.
        self._sticks_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Motion's draft -- same per-side/per-profile shape as Sticks'/
        # Triggers'. One of the two categories Track S's own ordering
        # flagged as most irregular (see motion_view.py's module
        # docstring for what's deliberately still deferred).
        self._motion_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Buttons' draft -- per-profile scope too, covering both layers
        # (default/shift) and the two D-pad options under one ledger, same
        # as every other per-side/multi-field slice. The hardest fit: no
        # per-field widget exists on this page at all (see
        # buttons_view.py's own module docstring) -- its touch/revert UI
        # lives inside KeycodePicker's own was/Revert row instead of a
        # wrapped form field.
        self._buttons_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Profile Settings' draft -- the eighth and last S6 page, per-
        # profile scope too, one field (report_rate_hz). No view class of
        # its own holds this one -- _build_profile_settings_page() builds
        # the whole page inline, so the mark/revert row and touch
        # tracking live directly on MainWindow (see that method's own
        # docstring).
        self._profile_draft = DesiredDraft(ObservedSnapshot(None, confirmed=False))
        # Which draft a currently-in-flight execute_requested belongs to --
        # "vibration", "dock", "triggers", "sticks", "motion", "buttons",
        # or "profile_settings". All seven write buttons are disabled
        # while self._syncing is true (same as Sync Now/Read), so only
        # one job is ever in flight, but set_execute_finished() still
        # needs to know which draft's bookkeeping to update when the
        # response comes back.
        self._pending_execute_scope: Optional[str] = None
        # Bumped by DeviceWatcher.connection_generation_changed every time a
        # connection is freshly (re-)established -- captured into any
        # execute_requested emission so _do_execute() can refuse to write
        # against a connection the draft wasn't reviewed against
        # (FEASIBILITY.md: "reject stale preparation after... reconnect").
        self._connection_generation = 0
        self._loading_profile_switch = False
        self._loading_report_rate_combo = False
        # True only while the Shift layer's single screen is showing. The
        # only reliable source of this -- rail.profile_switch.value() ==
        # SHIFT_VIEW was tried and is wrong, since _select_shift_view()
        # actually sets that control to None (off-scale), not "shift": a
        # real bug found in A6's code review, 2026-10-22, that made the
        # Shift-layer sync warning never show and let a background read
        # silently re-check a numbered profile segment while Shift was
        # still on screen. Set once, in _apply_view(), the one place that
        # actually decides this.
        self._viewing_shift = False
        self.setWindowIcon(self._app_icon())

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_ownership_bar())
        outer.addWidget(self._build_connection_alarm())
        content_row = QHBoxLayout()
        content_row.setContentsMargins(14, 10, 14, 10)
        content_row.setSpacing(14)
        content_row.addWidget(self._build_rail())
        content_column = QVBoxLayout()
        content_column.setSpacing(8)
        content_column.addWidget(self._build_unconfirmed_banner())
        content_column.addWidget(self._build_content_area(), 1)
        content_column.addLayout(self._build_write_action_row())
        content_row.addLayout(content_column, 1)
        outer.addLayout(content_row, 1)
        outer.addLayout(self._build_status_bar())

        self._load_views_from_state()
        self._refresh_confirmed_display()

    def _app_icon(self):
        from .tray import _state_icon
        # Static regardless of connection state -- only the tray icon
        # reflects state with colour. Reuses the "disconnected" icon
        # rather than a dedicated static asset, so the taskbar entry
        # stays state-neutral (see tray.py's own TrayIcon).
        return _state_icon("icon_black.png")

    def _apply_stylesheet(self) -> None:
        # `QApplication.setStyleSheet()` re-polishes every existing
        # top-level widget on every call, regardless of whether the text
        # actually changed -- a real cost in the live app only once (there
        # is only ever one MainWindow), but a construction-count-squared
        # one in a test suite that builds a fresh MainWindow per test
        # without closing the last (every one of them reaching this same
        # code, same palette, same generated string). Found by timing
        # MainWindow() construction directly: 0.8s/1.7s/2.8s/4.2s... for
        # the 1st/2nd/3rd/4th instance in one process, climbing without
        # bound. Guarding on the generated text actually changing fixes
        # both: the hot path here is a no-op, and a real theme change
        # (different palette) still re-polishes exactly once.
        app = QApplication.instance()
        if app is None:
            return
        stylesheet = generate_stylesheet(self._theme.palette)
        if stylesheet != app.styleSheet():
            app.setStyleSheet(stylesheet)

    def _on_palette_changed(self, palette) -> None:
        self._apply_stylesheet()
        # CurveEditor paints directly with QPainter, not QSS (DESIGN-SPEC.md
        # 10.2 item 5) -- it needs this explicit repaint call on a theme
        # change, a regenerated stylesheet alone doesn't reach it.
        self.sticks_view.set_palette(palette)
        self.triggers_view.set_palette(palette)
        self._hatch_overlay.set_palette(palette)
        # Real bug, found in A6's code review (2026-10-22): rail and
        # _connection_alarm (InlineNotice) are the other baked-pixmap-icon
        # widgets this method missed entirely -- both had no set_palette()
        # to call until now (see each one's own docstring).
        self.rail.set_palette(palette)
        self._connection_alarm.set_palette(palette)
        self.overview_view.set_palette(palette)
        self.buttons_view.set_palette(palette)

    @property
    def theme(self) -> ThemeController:
        """Public read path for app.py, which owns the tray icon -- a
        sibling of this window, not a child, so it needs this window's
        ThemeController from the outside rather than reaching into a
        private attribute."""
        return self._theme

    # --- Construction helpers ----------------------------------------------

    def _build_ownership_bar(self) -> QWidget:
        self.ownership_bar = OwnershipBar(self._theme.palette, self._theme.icons, self)
        self.ownership_bar.releaseRequested.connect(self._on_release_clicked)
        # Aliases: tests and the rest of this class reach these by the name
        # they've always had -- only where they physically live has moved.
        self.playability_label = self.ownership_bar.playability_label
        self.battery_label = self.ownership_bar.battery_label
        return self.ownership_bar

    def _build_connection_alarm(self) -> QWidget:
        """The alarm inline notice CRITIC.md #7 accepted but left unwired --
        DESIGN-SPEC.md 10.1 #7: "the bar stays Holding and an alarm inline
        notice sits directly beneath it", for a connection-level problem
        (lost connection, a USB error, an unreachable identity -- see
        watcher.py's own `_emit_error()` call sites) as distinct from an
        ordinary failed Sync/Read, which already gets its own blocking
        QMessageBox. error_label (the status bar's small text) stays as
        today's quieter, persistent record of the same message; this is
        the prominent one the bar's own docstring already pointed at.
        """
        self._connection_alarm = InlineNotice(
            "alarm", "", self._theme.palette, self._theme.icons, parent=self
        )
        self._connection_alarm.hide()
        return self._connection_alarm

    def _build_rail(self) -> QWidget:
        self.rail = Rail(self._theme.palette, self._theme.icons, self)
        self.rail.profileChanged.connect(self._on_profile_changed)
        self.rail.pageRequested.connect(self._on_page_requested)
        self.rail.readRequested.connect(lambda: self.request_read_from_device(force_dock_read=True))
        self.rail.importRequested.connect(self._on_import)
        self.rail.exportRequested.connect(self._on_export)
        self.rail.appPreferencesRequested.connect(self._on_app_preferences)
        self.rail.wire_help_menu(self._build_help_menu)
        # Aliases, same reasoning as the ownership bar above.
        self.read_btn = self.rail.read_button
        self.import_export_btn = self.rail.snapshots_button
        self.help_btn = self.rail.help_button
        return self.rail

    def _build_help_menu(self, menu) -> None:
        about_action = QAction("About", self)
        about_action.triggered.connect(self._on_about)
        menu.addAction(about_action)
        ondevice_action = QAction("On-Device Features", self)
        ondevice_action.setToolTip(
            "The controller's own button combos (profile switch, on-the-fly "
            "paddle remap, hair-trigger toggle, calibration) -- these work "
            "with no software at all."
        )
        ondevice_action.triggered.connect(self._on_ondevice_features)
        menu.addAction(ondevice_action)
        menu.addSeparator()
        report_issue_action = QAction("Report an Issue…", self)
        report_issue_action.triggered.connect(self._on_report_issue)
        menu.addAction(report_issue_action)

    def _build_unconfirmed_banner(self) -> QLabel:
        # Roadmap: "the GUI displays unread state as if it were real" -- a
        # freshly-launched window, or one where a read just failed, painted
        # default_state_dict()'s scaffold or the previous profile's real
        # values with nothing distinguishing them from a confirmed reading.
        # Sync Now being disabled was the only signal, and it is easy to
        # miss since nobody is trying to sync yet. This banner plus the
        # disabled-control styling from _refresh_confirmed_display() puts
        # the same fact where it can't be missed: on the values themselves.
        self.unconfirmed_banner = QLabel(
            "Not yet confirmed against the device -- these are placeholder "
            "values. Read from Device once connected."
        )
        self.unconfirmed_banner.setProperty("role", "caution")
        return self.unconfirmed_banner

    def _build_pages(self) -> QStackedWidget:
        """One stacked page per rail nav entry. Settings is last and
        deliberately apart from the rest: everything before it is
        per-profile, while the dock settings it holds are device-wide.
        """
        self.pages = QStackedWidget()
        self.overview_view = OverviewView(self._theme.palette, icon_loader=self._theme.icons)
        self.overview_view.reportRateChanged.connect(self._on_report_rate_changed)
        self.buttons_view = ButtonsView(self._theme.palette)
        self.buttons_view.fieldTouched.connect(self._on_buttons_field_touched)
        self.buttons_view.fieldReverted.connect(self._on_buttons_field_reverted)
        self.sticks_view = SticksView(self._theme.palette)
        self.sticks_view.fieldTouched.connect(self._on_sticks_field_touched)
        self.sticks_view.fieldReverted.connect(self._on_sticks_field_reverted)
        self.triggers_view = TriggersView(self._theme.palette)
        self.motion_view = MotionView()
        self.motion_view.fieldTouched.connect(self._on_motion_field_touched)
        self.motion_view.fieldReverted.connect(self._on_motion_field_reverted)
        self.vibration_view = VibrationView()
        self.vibration_view.fieldTouched.connect(self._on_vibration_field_touched)
        self.vibration_view.fieldReverted.connect(self._on_vibration_field_reverted)
        self.triggers_view.fieldTouched.connect(self._on_triggers_field_touched)
        self.triggers_view.fieldReverted.connect(self._on_triggers_field_reverted)
        self.settings_view = SettingsView()  # Dock, device-wide
        self.settings_view.fieldTouched.connect(self._on_dock_field_touched)
        self.settings_view.fieldReverted.connect(self._on_dock_field_reverted)
        self._profile_settings_page = self._build_profile_settings_page()
        self._page_widgets = {
            "overview": self.overview_view,
            "buttons": self.buttons_view,
            "sticks": self.sticks_view,
            "triggers": self.triggers_view,
            "motion": self.motion_view,
            "vibration": self.vibration_view,
            "profile_settings": self._profile_settings_page,
            "shift": self.buttons_view,  # same widget, set_layer("shift") below
            "dock": self.settings_view,
        }
        for key in (*PROFILE_PAGE_KEYS, *SHARED_PAGE_KEYS):
            widget = self._page_widgets[key]
            if self.pages.indexOf(widget) < 0:
                self.pages.addWidget(widget)
            # buttons_view/_profile_settings_page wire their own dirty
            # signal elsewhere (buttons_view.changed below; report rate's
            # combo is a plain QComboBox with no `changed` signal of its
            # own, wired straight to _on_report_rate_changed instead).
            if widget in (self.buttons_view, self._profile_settings_page):
                continue
            widget.changed.connect(self._on_dirty)
        self.buttons_view.changed.connect(self._on_dirty)
        # Real bug, found adding the Overview page (D2, 2026-10-22):
        # QStackedWidget.currentWidget() defaults to whichever widget was
        # added *first*, which had only ever been buttons_view by accident
        # of PROFILE_PAGE_KEYS' own ordering -- rail.py's default-checked
        # nav button ("buttons") and the actual visible page content would
        # have silently diverged the moment anything else led that tuple.
        # Set explicitly so the two can never drift apart again regardless
        # of iteration order.
        self.pages.setCurrentWidget(self.buttons_view)
        return self.pages

    def _build_content_area(self) -> QStackedWidget:
        """Wraps self.pages with the "no controller" EmptyState
        (DIRECTION-A.md section 5's component inventory) and the unread
        HatchOverlay (section 6's "unread to read reveal"), A5 of the
        redesign. self.pages itself is unchanged by this -- still built,
        still addressable, still what every page-navigation method and
        test reaches into; only what MainWindow shows on top of it is new.

        The hatch sits over self.pages only, not the EmptyState -- unread
        placeholder data and "there is no data, nothing is connected" are
        different facts, and hatching the empty state would muddy an
        already-honest "nothing here" screen.
        """
        self._content_area = QStackedWidget()

        # setCurrentWidget() below needs this wrapper, not self.pages --
        # self.pages is only an indirect child now (nested inside its own
        # QStackedLayout alongside the hatch), not a direct child of
        # self._content_area the way addWidget() would need to find it.
        self._pages_with_hatch = QWidget()
        pages_stack = QStackedLayout(self._pages_with_hatch)
        pages_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        pages_stack.addWidget(self._build_pages())
        self._hatch_overlay = HatchOverlay(self._theme.palette)
        pages_stack.addWidget(self._hatch_overlay)
        self._content_area.addWidget(self._pages_with_hatch)

        self._empty_state = EmptyState(
            "No controller connected",
            "Connect a GameSir G7 Pro to configure it. "
            "Already connected? It may still be enumerating.",
            self._theme.fonts,
        )
        self._content_area.addWidget(self._empty_state)
        return self._content_area

    def _refresh_content_area(self) -> None:
        """Shows the EmptyState in place of the page content only when
        there is genuinely nothing to show yet -- no controller at all,
        and nothing ever confirmed. Connecting (a controller IS present,
        a read is imminent) and an already-confirmed reading both keep
        showing today's page content, just as before this phase."""
        show_empty = self._connection_state in ("disconnected", "no_controller") and not self._state_confirmed
        self._content_area.setCurrentWidget(self._empty_state if show_empty else self._pages_with_hatch)
        # The empty state already says "no controller" on its own --
        # the unconfirmed banner on top of it would just repeat that.
        if show_empty:
            self.unconfirmed_banner.setVisible(False)

    def _build_profile_settings_page(self) -> QWidget:
        """Report rate, CRITIC.md #9's fix: it had no rail home at all
        before (built into the old top selector bar, outside self.tabs
        entirely -- the exact structural gap that let it slip through
        _refresh_confirmed_display()'s QScrollArea sweep, a code review
        2026-09-17). Wrapped in a QScrollArea like every other page, so it
        is now reached by that same generic sweep instead of needing its
        own special-cased line.

        S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S): the
        eighth and last S6 page, and the shortest -- one field, already a
        plain `FieldSpec` since S3 (`REPORT_RATE_FIELD`), with no view
        class of its own to hold a `fieldTouched` signal (this whole page
        is built inline here), so the mark/revert row and the touch
        tracking both live directly on MainWindow instead of being
        forwarded through a view. Overview's own independent report-rate
        combo (D2, 2026-10-22) is unaffected -- it's a convenience mirror
        of the same value, not a second editing surface with its own
        revert affordance; `_sync_report_rate_combo()` already keeps it
        showing whatever this page's own draft/state currently holds.
        """
        content = QWidget()
        form = QFormLayout(content)
        # A3-style SegmentedControl, A4's re-skin -- "report_rate_combo"
        # keeps its pre-redesign name (MainWindow/tests address it that
        # way; same precedent as VibrationView's `sliders`), not because
        # it's still a QComboBox.
        self.report_rate_combo = SegmentedControl([(str(hz), f"{hz} Hz") for hz in (250, 500, 1000)])
        self.report_rate_combo.setToolTip(
            "Per-profile polling rate. Note: GameSir Nexus disables native "
            "trigger vibration when this is set to 1000 Hz -- likely a real "
            "bandwidth constraint, not a bug."
        )
        # Display default, signals blocked -- see sticks_view.py's
        # SegmentedControl off-scale fix for why a fresh control needs one.
        self.report_rate_combo.blockSignals(True)
        self.report_rate_combo.set_value("1000")
        self.report_rate_combo.blockSignals(False)
        self.report_rate_combo.selectionChanged.connect(self._on_report_rate_changed)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.report_rate_combo)
        self._report_rate_was_label = QLabel("")
        self._report_rate_was_label.setProperty("role", "muted")
        self._report_rate_was_label.setVisible(False)
        row.addWidget(self._report_rate_was_label)
        self._report_rate_revert_btn = QPushButton("Revert")
        self._report_rate_revert_btn.setProperty("role", "link")
        self._report_rate_revert_btn.setVisible(False)
        self._report_rate_revert_btn.clicked.connect(self._revert_report_rate)
        row.addWidget(self._report_rate_revert_btn)
        row.addStretch(1)
        form.addRow("Report Rate:", row_widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _build_write_action_row(self) -> QHBoxLayout:
        """Sync Now: the one control in wave 1 that actually writes to the
        controller, so -- per CRITIC.md #1's closed list -- it is the one
        non-rail, non-live use of the signal colour. Occupies the same row
        wave 2's DraftBar lands in later; this phase keeps today's direct
        confirm-then-write contract (DESIGN-SPEC.md 10.2 item 1), just
        restyled.
        """
        row = QHBoxLayout()
        row.addStretch(1)
        # S6's fast path (DESIGN-SPEC.md 10.3): shown only while Vibration's
        # draft has unwritten touches, next to (not replacing) Sync Now --
        # the full draft bar/review sheet this is a down payment on doesn't
        # exist yet, so this is the one place a fast-path write can start.
        # role="write" is the one other button CRITIC.md #1's closed signal
        # list allows, same as Sync Now.
        self.vibration_write_btn = QPushButton("Write 1 change")
        self.vibration_write_btn.setProperty("role", "write")
        self.vibration_write_btn.setVisible(False)
        self.vibration_write_btn.setToolTip(
            "Write only the Vibration levels changed since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.vibration_write_btn.clicked.connect(self._on_write_vibration_clicked)
        row.addWidget(self.vibration_write_btn)
        self.dock_write_btn = QPushButton("Write 1 change")
        self.dock_write_btn.setProperty("role", "write")
        self.dock_write_btn.setVisible(False)
        self.dock_write_btn.setToolTip(
            "Write only the Dock settings changed since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.dock_write_btn.clicked.connect(self._on_write_dock_clicked)
        row.addWidget(self.dock_write_btn)
        self.triggers_write_btn = QPushButton("Write 1 change")
        self.triggers_write_btn.setProperty("role", "write")
        self.triggers_write_btn.setVisible(False)
        self.triggers_write_btn.setToolTip(
            "Write only the Trigger settings changed since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.triggers_write_btn.clicked.connect(self._on_write_triggers_clicked)
        row.addWidget(self.triggers_write_btn)
        self.sticks_write_btn = QPushButton("Write 1 change")
        self.sticks_write_btn.setProperty("role", "write")
        self.sticks_write_btn.setVisible(False)
        self.sticks_write_btn.setToolTip(
            "Write only the Stick settings changed since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.sticks_write_btn.clicked.connect(self._on_write_sticks_clicked)
        row.addWidget(self.sticks_write_btn)
        self.motion_write_btn = QPushButton("Write 1 change")
        self.motion_write_btn.setProperty("role", "write")
        self.motion_write_btn.setVisible(False)
        self.motion_write_btn.setToolTip(
            "Write only the Motion settings changed since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.motion_write_btn.clicked.connect(self._on_write_motion_clicked)
        row.addWidget(self.motion_write_btn)
        self.buttons_write_btn = QPushButton("Write 1 change")
        self.buttons_write_btn.setProperty("role", "write")
        self.buttons_write_btn.setVisible(False)
        self.buttons_write_btn.setToolTip(
            "Write only the button bindings and D-pad options changed "
            "since the last read -- re-reads the controller first and "
            "refuses if something else changed there since."
        )
        self.buttons_write_btn.clicked.connect(self._on_write_buttons_clicked)
        row.addWidget(self.buttons_write_btn)
        self.profile_write_btn = QPushButton("Write 1 change")
        self.profile_write_btn.setProperty("role", "write")
        self.profile_write_btn.setVisible(False)
        self.profile_write_btn.setToolTip(
            "Write only the Report Rate change since the last read -- "
            "re-reads the controller first and refuses if something else "
            "changed there since."
        )
        self.profile_write_btn.clicked.connect(self._on_write_profile_clicked)
        row.addWidget(self.profile_write_btn)
        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.setProperty("role", "write")
        self.sync_btn.setEnabled(False)
        self.sync_btn.setToolTip(
            "Push the current state to the connected controller. Disabled "
            "until the state has been confirmed against real hardware, via "
            "a successful Read from Device or an explicit Import."
        )
        self.sync_btn.clicked.connect(self.request_sync_now)
        row.addWidget(self.sync_btn)
        return row

    def _build_status_bar(self) -> QHBoxLayout:
        """Job progress and local errors -- connection state, battery and
        release now live in the ownership bar instead.

        Three separate labels rather than one shared message area, so a
        sync progress update can't wipe out an error the user hasn't read.
        """
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 4, 14, 8)
        bottom.setSpacing(12)
        self.error_label = QLabel("")
        self.error_label.setProperty("role", "alarm")
        bottom.addWidget(self.error_label)
        bottom.addStretch(1)
        self.sync_status_label = QLabel("")
        self.sync_status_label.setProperty("role", "muted")
        bottom.addWidget(self.sync_status_label)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "muted")
        bottom.addWidget(self.status_label)
        return bottom

    def set_battery(self, percent: int, charging: bool) -> None:
        """Show a charge reading. Called on the GUI thread via a queued
        connection from DeviceWatcher.battery_changed."""
        self.ownership_bar.set_battery(percent, charging)

    def set_active_profile(self, slot: int) -> None:
        """Mark which profile the controller is physically using.

        The rail's switch chooses what you *edit*; this shows what you are
        *playing*. They are independent -- every category targets a
        profile explicitly, so editing Profile 2 while playing Profile 1
        works correctly.
        """
        self._active_profile = slot
        self.rail.set_active_profile(slot)
        self._sync_overview_scope()

    def _sync_overview_scope(self) -> None:
        """Push the viewed profile slot and the physically-active one into
        Overview's scope line -- pushed directly rather than read from
        `self._state` inside `OverviewView.load_state()`, so the profile
        number updates the instant either one changes, not lagging behind
        a device read (OverviewView's own module docstring)."""
        self.overview_view.set_profile_scope(
            self._state.get("controller_slot") or 1, self._active_profile)

    def set_firmware(self, version: str) -> None:
        """Record the controller's firmware version, read once per
        connection -- goes in the ownership bar's tooltip, reference
        information someone looks up when filing a bug, not something
        worth spending bar width on every session."""
        self._firmware = version
        self.ownership_bar.set_firmware_tooltip(f"Controller firmware v{version}")

    def clear_battery(self) -> None:
        """No reading available -- hide rather than show a stale number."""
        self.ownership_bar.clear_battery()

    # --- Window geometry ----------------------------------------------------

    def _restore_geometry(self) -> None:
        try:
            data = _GEOMETRY_PATH.read_bytes()
        except OSError:
            return
        self.restoreGeometry(QByteArray(data))

    def save_geometry(self) -> None:
        """Persist window position/size so it's remembered across both
        hide/show (tray minimize) and full app restarts. Called from
        closeEvent (covers the tray-app "close = hide" path) and from
        app.py's aboutToQuit (redundant safety net for other quit paths)."""
        try:
            _GEOMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _GEOMETRY_PATH.write_bytes(bytes(self.saveGeometry()))
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_geometry()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """Hand the controller back while the window isn't focused.

        Holding the device keeps its gamepad interface claimed, detaching
        the kernel driver -- so tabbing away to actually play would
        otherwise find a dead controller until Release Device was clicked
        by hand. GameSir Nexus releases on unfocus for the same reason.
        Hiding to the tray deactivates the window too, so that path is
        covered by this one.
        """
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow() and self.isVisible():
                self._auto_release_timer.stop()
                self._reconnect_after_auto_release()
            else:
                self._auto_release_timer.start()
        super().changeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        """Closing to the tray releases too.

        Hooked directly rather than left to changeEvent: whether a window
        being hidden gets an ActivationChange at all is platform-dependent
        (it does under the offscreen platform these tests run on, it does
        not reliably under a real compositor), and closing the window is a
        clearer "I'm done with it" than losing focus is.
        """
        self._auto_release_timer.start()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        """Counterpart to hideEvent -- coming back from the tray reconnects
        without waiting to also be activated, for the same reason."""
        self._auto_release_timer.stop()
        self._reconnect_after_auto_release()
        super().showEvent(event)

    def _auto_release_if_still_unfocused(self) -> None:
        if self.isActiveWindow() or QApplication.activeWindow() is not None:
            # Focus came back, or it only ever went to one of our own windows
            # -- a modal confirmation dialog, not the user leaving.
            return
        if self._connection_state != "connected":
            return
        if self._syncing:
            # Mid sync-to or read-from-device. Dropping the session here
            # would abort a write to persistent device config, so wait and
            # re-check rather than skipping the release entirely.
            self._auto_release_timer.start()
            return
        self._auto_released = True
        self.release_toggled.emit(True)

    def _reconnect_after_auto_release(self) -> None:
        """Only undoes this class's own release -- an explicit Release Device
        leaves _auto_released false, so refocusing won't silently reconnect.
        See set_connection_state() for the other half of this fix (self-
        correcting a too-fast refocus).
        """
        if not self._auto_released or self._connection_state != "paused":
            return
        self._auto_released = False
        self.release_toggled.emit(False)

    def set_connection_state(self, state: str) -> None:
        self.ownership_bar.set_state(state)
        was_connected = self._connection_state == "connected"
        self._connection_state = state
        if state == "connected":
            self.ownership_bar.set_release_enabled(not self._syncing)
            self._refresh_sync_btn()
            self.rail.read_button.setEnabled(not self._syncing)
            self.set_error("")  # a successful (re)connect supersedes any earlier error
            if not was_connected:
                self._auto_read_on_connect()
        elif state == "paused":
            self.ownership_bar.set_release_enabled(True)
            self.sync_btn.setEnabled(False)
            self.rail.read_button.setEnabled(False)
            # If a focus event already tried to undo an auto-release before
            # this "paused" confirmation arrived (see
            # _reconnect_after_auto_release()'s own comment), don't wait
            # for another focus change to notice -- act on it now that
            # _connection_state has actually caught up.
            self._reconnect_after_auto_release()
        else:
            self.ownership_bar.set_release_enabled(False)
            self.sync_btn.setEnabled(False)
            self.rail.read_button.setEnabled(False)
        self._refresh_content_area()

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self._connection_alarm.set_text(message)
        self._connection_alarm.setVisible(bool(message))

    def _confirm(self, title: str, text: str) -> bool:
        """One seam for every "are you sure" prompt in this window -- a
        thin wrapper, not inlined at each call site, so a test can
        monkeypatch just this method instead of dealing with a real blocking
        modal dialog."""
        reply = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _sync_allowed(self) -> bool:
        return (self._connection_state == "connected" and not self._syncing
                and self._state_confirmed)

    def _refresh_sync_btn(self) -> None:
        self.sync_btn.setEnabled(self._sync_allowed())

    def _refresh_confirmed_display(self) -> None:
        """Make an unconfirmed self._state look inert, not just un-syncable.

        Disables every QScrollArea's *contained widget*, not self.pages and
        not the QScrollAreas themselves -- Qt's disabled state cascades
        downward with no way for a child to opt back out (confirmed: a
        QScrollArea explicitly re-enabled still reports its own scrollbar
        as disabled if any ancestor is disabled), so disabling self.pages
        directly would take the scrollbars down with every actual control.
        Scrolling and switching pages are navigation, not an edit -- a user
        should be able to look at an unconfirmed page's full content
        without that being mistaken for permission to change it. Every
        category view wraps its real content in a QScrollArea (see
        TriggersView/VibrationView/SettingsView's own comments, and
        _build_profile_settings_page() above for report rate's), so this
        still reaches every control with one flag, not a per-view "is this
        real" plumbing job.

        Must be called every time self._state_confirmed OR self._syncing
        changes: on construction, after every read attempt (success or
        failure), on Import, on a profile switch (whose value it turns
        False again -- see _on_profile_changed for why that has to happen
        even before the resulting read comes back), and around every
        sync-to/read-from-device job.
        """
        editable = self._state_confirmed and not self._syncing
        for scroll in self.pages.findChildren(QScrollArea):
            content = scroll.widget()
            if content is not None:
                content.setEnabled(editable)
        self.unconfirmed_banner.setVisible(not self._state_confirmed)
        self._hatch_overlay.set_unread(not self._state_confirmed)
        self._refresh_content_area()

    def _on_release_clicked(self) -> None:
        self.release_toggled.emit(self._connection_state != "paused")

    def _auto_read_on_connect(self) -> None:
        """Pull live state from the device the moment we (re)connect, so the
        GUI never sits there showing stale in-memory state while the real
        device has since changed (e.g. edited via GameSir Nexus). Skipped
        if there are unsynced local edits -- an automatic read would otherwise
        silently discard them; the user can still hit "Read from Device" by
        hand to discard on purpose."""
        if self._dirty:
            self.sync_status_label.setText(
                "Connected -- pending changes not synced; Sync Now or "
                "Read from Device to discard them."
            )
            return
        self.request_read_from_device()

    def request_sync_now(self) -> None:
        if not self._sync_allowed():
            return
        slot = self._state.get("controller_slot") or 1
        if self._viewing_shift:
            message = ("Push the current settings to the connected controller? The Shift "
                       f"layer is shared by all four profiles, so this changes it for every "
                       f"profile — and anything else edited since the last sync still goes to "
                       f"Profile {slot}.")
        else:
            message = (f"Push the current settings to Profile {slot} on the connected "
                       "controller? This overwrites that profile's stored settings.")
        if not self._confirm("Sync to controller?", message):
            return
        self._syncing = True
        self.syncing_changed.emit(True)
        self.sync_btn.setEnabled(False)
        self.rail.read_button.setEnabled(False)
        self.rail.set_nav_enabled(False)
        self.ownership_bar.set_release_enabled(False)
        # Real gap, found 2026-09-01: Import/Export were never gated on
        # _syncing at all, unlike every other state-affecting control here.
        # Export reads self._state while the watcher thread is iterating
        # that same dict object mid-sync (see _refresh_confirmed_display()'s
        # docstring); Import replaces self._state outright, so a sync that
        # finishes after an Import lands calls set_sync_finished() -> the
        # dirty flag clears as if the *imported* state had just been synced,
        # when the device actually still holds whatever was pushed before
        # the import.
        self.import_export_btn.setEnabled(False)
        self._refresh_confirmed_display()  # locks every page for the duration
        self.sync_status_label.setText("Syncing…")
        self.sync_requested.emit(self._state)

    def set_sync_progress(self, step: int, total: int, label: str) -> None:
        if total == 0:
            self.sync_status_label.setText(label)  # e.g. "Reading current device state…", no step count yet
        else:
            self.sync_status_label.setText(f"Syncing ({step}/{total}): {label}")

    def set_sync_finished(self, success: bool, message: str) -> None:
        self._syncing = False
        self.syncing_changed.emit(False)
        self.sync_status_label.setText(message)
        self._refresh_sync_btn()
        self._refresh_confirmed_display()  # unlocks the pages request_sync_now() locked
        self.rail.read_button.setEnabled(self._connection_state == "connected")
        self.ownership_bar.set_release_enabled(self._connection_state == "connected")
        self.rail.set_nav_enabled(True)
        self.import_export_btn.setEnabled(True)
        if success:
            self._set_dirty(False)  # the device now matches what we just pushed
            # Sync Now just wrote the whole state, including any Vibration
            # or Dock touches -- discard both drafts too, or the rail
            # count/fast-path buttons would keep claiming unwritten edits
            # that were, in fact, just written.
            self._reset_vibration_draft()
            self._reset_dock_draft()
            self._reset_triggers_draft()
            self._reset_sticks_draft()
            self._reset_motion_draft()
            self._reset_buttons_draft()
            self._reset_profile_draft()
        else:
            QMessageBox.warning(self, "Sync failed", message)

    # --- S6's fast path (DesiredDraft / prepare-execute) --------------------

    def _on_vibration_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._vibration_draft.touch(path, field, desired, profile)
        self._refresh_vibration_draft_ui()

    def _on_vibration_field_reverted(self, path: tuple) -> None:
        self._vibration_draft.untouch(path)
        self._refresh_vibration_draft_ui()

    def _refresh_vibration_draft_ui(self) -> None:
        count = self._vibration_draft.edit_count
        self.rail.set_edit_count("vibration", count)
        self.vibration_write_btn.setVisible(count > 0)
        self.vibration_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.vibration_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_vibration_draft(self, imported: bool = False) -> None:
        """A fresh ObservedSnapshot -- a real Read from Device, an Import,
        or a profile switch discarding whatever was there (DESIGN-SPEC.md
        10.1 #5: "the switch dialog says plainly that shared edits are
        discarded too" -- Vibration is per-profile, not shared, so unlike
        `_dock_draft` it IS always discarded on a switch; see this
        method's own callers).

        A real `copy.deepcopy()`, not `self._state` itself -- REAL BUG,
        caught by tests/test_gui_main_window_fast_path.py before this ever
        ran on hardware: VibrationView's still-active old-path `_on_edit()`
        mutates `self._state["vibration"]` in place on every edit, so an
        `ObservedSnapshot` sharing that same dict object would silently
        drift to show the just-drafted value as its own "baseline" the
        moment a level was moved -- exactly the baseline-contamination
        `prepare()` exists to compare against, defeating its own
        three-way classification before a single write happens.
        """
        self._vibration_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_vibration_draft_ui()

    def _on_dock_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._dock_draft.touch(path, field, desired, profile)
        self._refresh_dock_draft_ui()

    def _on_dock_field_reverted(self, path: tuple) -> None:
        self._dock_draft.untouch(path)
        self._refresh_dock_draft_ui()

    def _refresh_dock_draft_ui(self) -> None:
        count = self._dock_draft.edit_count
        self.rail.set_edit_count("dock", count)
        self.dock_write_btn.setVisible(count > 0)
        self.dock_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.dock_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_dock_draft(self, imported: bool = False) -> None:
        """Same shape as `_reset_vibration_draft()`, but called from fewer
        places: a profile switch must NOT reset this one (DESIGN-SPEC.md
        10.1 #5 -- Dock is shared scope, its draft survives a switch).
        See `set_read_finished()`'s own guard for the other half of that:
        a switch-triggered read must not silently overwrite a pending Dock
        edit in `self._state` either, or there'd be nothing left for this
        draft's own marks to mean anything about."""
        self._dock_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_dock_draft_ui()

    def _on_triggers_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._triggers_draft.touch(path, field, desired, profile)
        self._refresh_triggers_draft_ui()

    def _on_triggers_field_reverted(self, path: tuple) -> None:
        self._triggers_draft.untouch(path)
        self._refresh_triggers_draft_ui()

    def _refresh_triggers_draft_ui(self) -> None:
        count = self._triggers_draft.edit_count
        self.rail.set_edit_count("triggers", count)
        self.triggers_write_btn.setVisible(count > 0)
        self.triggers_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.triggers_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_triggers_draft(self, imported: bool = False) -> None:
        """Same shape/reasoning as `_reset_vibration_draft()` -- Triggers
        is per-profile scope too, so this IS discarded on a profile
        switch (see `_on_profile_changed()`), unlike `_dock_draft`."""
        self._triggers_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_triggers_draft_ui()

    def _on_sticks_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._sticks_draft.touch(path, field, desired, profile)
        self._refresh_sticks_draft_ui()

    def _on_sticks_field_reverted(self, path: tuple) -> None:
        self._sticks_draft.untouch(path)
        self._refresh_sticks_draft_ui()

    def _refresh_sticks_draft_ui(self) -> None:
        count = self._sticks_draft.edit_count
        self.rail.set_edit_count("sticks", count)
        self.sticks_write_btn.setVisible(count > 0)
        self.sticks_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.sticks_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_sticks_draft(self, imported: bool = False) -> None:
        """Same shape/reasoning as `_reset_triggers_draft()` -- Sticks is
        per-profile scope too, discarded on a profile switch."""
        self._sticks_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_sticks_draft_ui()

    def _on_motion_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._motion_draft.touch(path, field, desired, profile)
        self._refresh_motion_draft_ui()

    def _on_motion_field_reverted(self, path: tuple) -> None:
        self._motion_draft.untouch(path)
        self._refresh_motion_draft_ui()

    def _refresh_motion_draft_ui(self) -> None:
        count = self._motion_draft.edit_count
        self.rail.set_edit_count("motion", count)
        self.motion_write_btn.setVisible(count > 0)
        self.motion_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.motion_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_motion_draft(self, imported: bool = False) -> None:
        """Same shape/reasoning as `_reset_sticks_draft()` -- Motion is
        per-profile scope too, discarded on a profile switch."""
        self._motion_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_motion_draft_ui()

    def _on_buttons_field_touched(self, path: tuple, field: object, desired: object, profile: int) -> None:
        self._buttons_draft.touch(path, field, desired, profile)
        self._refresh_buttons_draft_ui()

    def _on_buttons_field_reverted(self, path: tuple) -> None:
        self._buttons_draft.untouch(path)
        self._refresh_buttons_draft_ui()

    def _refresh_buttons_draft_ui(self) -> None:
        count = self._buttons_draft.edit_count
        self.rail.set_edit_count("buttons", count)
        self.buttons_write_btn.setVisible(count > 0)
        self.buttons_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.buttons_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_buttons_draft(self, imported: bool = False) -> None:
        """Same shape/reasoning as `_reset_motion_draft()` -- Buttons is
        per-profile scope too, discarded on a profile switch."""
        self._buttons_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self._refresh_buttons_draft_ui()

    def _mark_report_rate_touched(self, value: int) -> None:
        baseline = self._profile_draft.observed.get(("report_rate_hz",))
        if baseline is not None and value == baseline:
            # Same implicit-revert fix every other S6 slice needed
            # (2026-10-26, the hardware test): manually
            # dialing this back to its loaded value, not clicking
            # Revert, must act exactly like a real revert.
            self._profile_draft.untouch(("report_rate_hz",))
            self.report_rate_combo.set_edited(False)
            self._report_rate_was_label.setVisible(False)
            self._report_rate_revert_btn.setVisible(False)
            self._refresh_profile_draft_ui()
            return
        profile = self._state.get("controller_slot") or 1
        self._profile_draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, value, profile)
        self.report_rate_combo.set_edited(True)
        self._report_rate_was_label.setText("was Unknown" if baseline is None else f"was {baseline} Hz")
        self._report_rate_was_label.setVisible(True)
        self._report_rate_revert_btn.setVisible(True)
        self._refresh_profile_draft_ui()

    def _revert_report_rate(self) -> None:
        baseline = self._profile_draft.observed.get(("report_rate_hz",))
        if baseline is None:
            return
        self._profile_draft.untouch(("report_rate_hz",))
        self._state["report_rate_hz"] = baseline
        self._sync_report_rate_combo()  # guarded by _loading_report_rate_combo -- won't re-mark touched
        self.report_rate_combo.set_edited(False)
        self._report_rate_was_label.setVisible(False)
        self._report_rate_revert_btn.setVisible(False)
        self._refresh_profile_draft_ui()
        self._on_dirty()

    def _refresh_profile_draft_ui(self) -> None:
        count = self._profile_draft.edit_count
        self.rail.set_edit_count("profile_settings", count)
        self.profile_write_btn.setVisible(count > 0)
        self.profile_write_btn.setText("Write 1 change" if count == 1 else f"Write {count} changes")
        self.profile_write_btn.setEnabled(
            count > 0 and self._connection_state == "connected" and not self._syncing)

    def _reset_profile_draft(self, imported: bool = False) -> None:
        """Same shape/reasoning as `_reset_buttons_draft()` -- Profile
        Settings is per-profile scope too, discarded on a profile
        switch."""
        self._profile_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed, imported=imported))
        self.report_rate_combo.set_edited(False)
        self._report_rate_was_label.setVisible(False)
        self._report_rate_revert_btn.setVisible(False)
        self._refresh_profile_draft_ui()

    def _rebuild_draft_snapshot(self, draft: DesiredDraft) -> DesiredDraft:
        """Refresh a draft's own `ObservedSnapshot` to the current
        `self._state`, re-touching whatever marks still remain against it
        -- called after a fast-path write, NOT a plain reset. Shared by
        both `_vibration_draft` and `_dock_draft`.

        REAL BUG, found live on hardware 2026-10-26 (hardware test): writing
        Left Grip to 75% succeeded; moving it back to 50% and writing again
        failed with "Something changed on the controller," even though
        nothing external had. Cause: a successful write only called
        `untouch()` on the written path -- the draft's `ObservedSnapshot`
        itself, taken when the page was last loaded, still held the
        PRE-write value. The next `prepare()` compared the real post-write
        value (75, correct) against that stale baseline (the original
        pre-first-write value, not 75) -- same value, different number --
        and correctly, by its own rules, called that a conflict: it had no
        way to know this app's own prior write was *why* they differed. The
        fix is this app keeping its own baseline current, not loosening
        prepare()'s own classification, which is doing exactly its job.

        Marks that are NOT part of the write just finished (none exist yet,
        single-page/single-job today, but kept general) are re-touched
        against the fresh snapshot rather than dropped -- same desired
        value, but now compared against a baseline that reflects reality.
        """
        new_draft = DesiredDraft(
            ObservedSnapshot(copy.deepcopy(self._state), self._state_confirmed,
                              imported=draft.observed.imported))
        for mark in draft.marks:
            new_draft.touch(mark.path, mark.field, mark.desired, mark.profile)
        return new_draft

    def set_connection_generation(self, generation: int) -> None:
        """Called from DeviceWatcher.connection_generation_changed. A new
        generation means any draft reviewed against the old connection is
        stale (FEASIBILITY.md: "reject stale preparation after... a
        reconnect") -- discarding here, rather than letting a fast-path
        write proceed and rely on _do_execute()'s own generation check to
        refuse it, keeps the rail count/button honest about what a write
        right now would actually do. Both drafts, including the shared-
        scope Dock one -- a reconnect, unlike a profile switch, means this
        app genuinely doesn't know what the device has anymore."""
        self._connection_generation = generation
        self._reset_vibration_draft()
        self._reset_dock_draft()
        self._reset_triggers_draft()
        self._reset_sticks_draft()
        self._reset_motion_draft()
        self._reset_buttons_draft()
        self._reset_profile_draft()

    def _on_write_vibration_clicked(self) -> None:
        if self._vibration_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "vibration"
        intents = self._vibration_draft.to_approved_intents()
        baseline = self._vibration_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _on_write_dock_clicked(self) -> None:
        if self._dock_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "dock"
        intents = self._dock_draft.to_approved_intents()
        baseline = self._dock_draft.observed.state or {}
        # Dock is shared scope, but that alone no longer forces the
        # sheet (tried 2026-10-26, dropped the same day -- see
        # watcher._do_execute()'s own docstring): same escalation rule
        # as every other page, conflict or >3 rows only.
        self._start_execute(intents, baseline)

    def _on_write_triggers_clicked(self) -> None:
        if self._triggers_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "triggers"
        intents = self._triggers_draft.to_approved_intents()
        baseline = self._triggers_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _on_write_sticks_clicked(self) -> None:
        if self._sticks_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "sticks"
        intents = self._sticks_draft.to_approved_intents()
        baseline = self._sticks_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _on_write_motion_clicked(self) -> None:
        if self._motion_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "motion"
        intents = self._motion_draft.to_approved_intents()
        baseline = self._motion_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _on_write_buttons_clicked(self) -> None:
        if self._buttons_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "buttons"
        intents = self._buttons_draft.to_approved_intents()
        baseline = self._buttons_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _on_write_profile_clicked(self) -> None:
        if self._profile_draft.edit_count == 0 or self._syncing:
            return
        self._pending_execute_scope = "profile_settings"
        intents = self._profile_draft.to_approved_intents()
        baseline = self._profile_draft.observed.state or {}
        self._start_execute(intents, baseline)

    def _lock_write_ui(self) -> None:
        """Disables everything a write/review must not race against --
        shared by `_start_execute()` and `set_needs_review()`'s own
        re-lock once the sheet is approved."""
        self._syncing = True
        self.syncing_changed.emit(True)
        self.sync_btn.setEnabled(False)
        self.vibration_write_btn.setEnabled(False)
        self.dock_write_btn.setEnabled(False)
        self.triggers_write_btn.setEnabled(False)
        self.sticks_write_btn.setEnabled(False)
        self.motion_write_btn.setEnabled(False)
        self.buttons_write_btn.setEnabled(False)
        self.profile_write_btn.setEnabled(False)
        self.rail.read_button.setEnabled(False)
        self.rail.set_nav_enabled(False)
        self.ownership_bar.set_release_enabled(False)
        self.import_export_btn.setEnabled(False)
        self._refresh_confirmed_display()

    def _unlock_write_ui(self) -> None:
        """The other half of `_lock_write_ui()` -- shared by
        `set_execute_finished()` and `set_needs_review()`'s own unlock
        while the sheet is open (a modal `exec()` already blocks input
        to the rest of the app, so this isn't a new race, just not
        leaving the chrome visibly disabled behind the sheet for no
        reason)."""
        self._syncing = False
        self.syncing_changed.emit(False)
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self.rail.read_button.setEnabled(self._connection_state == "connected")
        self.ownership_bar.set_release_enabled(self._connection_state == "connected")
        self.rail.set_nav_enabled(True)
        self.import_export_btn.setEnabled(True)

    def _start_execute(self, intents: list, baseline: dict) -> None:
        self._lock_write_ui()
        self.sync_status_label.setText("Writing…")
        self.execute_requested.emit(intents, baseline, self._connection_generation)

    def set_execute_finished(self, success: bool, message: str, read_back: Optional[object]) -> None:
        scope = self._pending_execute_scope
        self._pending_execute_scope = None
        self._unlock_write_ui()
        self.sync_status_label.setText(message)
        if success and read_back is not None:
            # Update self._state with every confirmed value FIRST, then
            # rebuild the draft's own baseline from it -- the fix
            # _rebuild_draft_snapshot()'s own docstring describes. Only
            # after that do already-satisfied paths get dropped from the
            # draft; a read-back mismatch keeps its field touched/marked
            # rather than being silently accepted as written
            # (FEASIBILITY.md M1: "read-back mismatch => draft retained").
            for outcome in read_back.ok:
                path = outcome.intent.path
                written = None if outcome.intent.desired is Intent.CLEAR else outcome.intent.desired
                self._apply_path(self._state, path, written)
            if scope == "vibration":
                self._vibration_draft = self._rebuild_draft_snapshot(self._vibration_draft)
                for outcome in read_back.ok:
                    self._vibration_draft.untouch(outcome.intent.path)
                self.vibration_view.load_state(self._state)
                self._refresh_vibration_draft_ui()
            elif scope == "dock":
                self._dock_draft = self._rebuild_draft_snapshot(self._dock_draft)
                for outcome in read_back.ok:
                    self._dock_draft.untouch(outcome.intent.path)
                self.settings_view.load_state(self._state)
                self._refresh_dock_draft_ui()
            elif scope == "triggers":
                self._triggers_draft = self._rebuild_draft_snapshot(self._triggers_draft)
                for outcome in read_back.ok:
                    self._triggers_draft.untouch(outcome.intent.path)
                self.triggers_view.load_state(self._state)
                self._refresh_triggers_draft_ui()
            elif scope == "sticks":
                self._sticks_draft = self._rebuild_draft_snapshot(self._sticks_draft)
                for outcome in read_back.ok:
                    self._sticks_draft.untouch(outcome.intent.path)
                self.sticks_view.load_state(self._state)
                self._refresh_sticks_draft_ui()
            elif scope == "motion":
                self._motion_draft = self._rebuild_draft_snapshot(self._motion_draft)
                for outcome in read_back.ok:
                    self._motion_draft.untouch(outcome.intent.path)
                self.motion_view.load_state(self._state)
                self._refresh_motion_draft_ui()
            elif scope == "buttons":
                self._buttons_draft = self._rebuild_draft_snapshot(self._buttons_draft)
                for outcome in read_back.ok:
                    self._buttons_draft.untouch(outcome.intent.path)
                self.buttons_view.load_state(self._state)
                self._refresh_buttons_draft_ui()
            elif scope == "profile_settings":
                self._profile_draft = self._rebuild_draft_snapshot(self._profile_draft)
                for outcome in read_back.ok:
                    self._profile_draft.untouch(outcome.intent.path)
                self._sync_report_rate_combo()
                if self._profile_draft.edit_count == 0:
                    self.report_rate_combo.set_edited(False)
                    self._report_rate_was_label.setVisible(False)
                    self._report_rate_revert_btn.setVisible(False)
                self._refresh_profile_draft_ui()
        elif not success:
            self._refresh_vibration_draft_ui()
            self._refresh_dock_draft_ui()
            self._refresh_triggers_draft_ui()
            self._refresh_sticks_draft_ui()
            self._refresh_motion_draft_ui()
            self._refresh_buttons_draft_ui()
            self._refresh_profile_draft_ui()
            QMessageBox.warning(self, "Write failed", message)

    @staticmethod
    def _apply_path(state: dict, path: tuple, value: object) -> None:
        """Write `value` into `state` at an arbitrary-depth path, e.g.
        `("dock_led_brightness",)` or `("triggers", "left", "deadzone",
        "initial")` -- generalizes the old `len(path) == 1`/`== 2`
        branching (which only ever covered Dock's flat keys and
        Vibration's one level of nesting) to any depth, for Triggers'
        3-4-deep paths."""
        d = state
        for key in path[:-1]:
            d = d.setdefault(key, {})
        d[path[-1]] = value

    def set_needs_review(self, job: object, fresh_state: dict) -> None:
        """DeviceWatcher.needs_review() -- fires when `_do_execute()`
        finds a real conflict or more than three rows (see its own
        docstring for why shared scope alone no longer escalates on its
        own, dropped 2026-10-26). `self._pending_execute_scope`
        (set by whichever `_on_write_*_clicked()` started this job) is
        still valid here -- only `set_execute_finished()` clears it, and
        only once this method decides NOT to proceed to an actual write.

        Unlocks the UI chrome `_start_execute()` locked (same as
        `set_execute_finished()` would) while the sheet is open -- a
        modal `exec()` call already blocks input to the rest of the app,
        so this isn't "the user can click Write on a different page
        mid-review," it's "the rail/Sync/Read buttons don't sit visibly
        disabled behind the sheet for no reason."
        """
        scope = self._pending_execute_scope
        self._unlock_write_ui()
        self.sync_status_label.setText("Reviewing…")

        scope_label = _SCOPE_LABELS.get(scope, scope or "This change")
        sheet = ReviewSheet(job, scope_label, self._theme.palette, self._theme.fonts, self)
        result = sheet.exec()

        if result == QDialog.DialogCode.Accepted and job.writable:
            # Keep self._pending_execute_scope set -- the eventual
            # set_execute_finished() for THIS write still needs it.
            self._lock_write_ui()
            self.sync_status_label.setText("Writing…")
            # force_conflicts=True: reaching this sheet at all means the
            # user has already seen any conflicting row clearly (this
            # pass has no per-row revert -- see review_sheet.py's own
            # module docstring), so an explicit Write click here is the
            # informed consent execute()'s own flag exists to require.
            self.execute_reviewed_requested.emit(job, self._connection_generation, True)
        else:
            self._pending_execute_scope = None
            self.sync_status_label.setText("Kept editing." if result != QDialog.DialogCode.Accepted
                                            else "Nothing left to write.")

    def request_read_from_device(self, force_dock_read: bool = False) -> None:
        """`force_dock_read`: DeviceWatcher skips the dock-settings blob
        after the first read per connection (a real, deliberate
        optimization -- dock settings don't change mid-connection). That's
        fine for the automatic callers below (profile switch, auto-read-
        on-connect), but the explicit "Read from controller" BUTTON's
        whole promised contract is "discard my edits, show me the
        controller's actual truth". Only the button's own connection
        passes True; both automatic callers keep the optimization.
        """
        if self._connection_state != "connected" or self._syncing:
            return
        if self._dirty and not self._confirm(
            "Discard unsynced changes?",
            "Reading from the device will overwrite unsaved edits in every "
            "page with the controller's actual current settings. Continue?",
        ):
            return
        self._syncing = True
        self.syncing_changed.emit(True)
        self.sync_btn.setEnabled(False)
        self.rail.read_button.setEnabled(False)
        self.rail.set_nav_enabled(False)
        self.ownership_bar.set_release_enabled(False)  # same reasoning as request_sync_now()
        self.import_export_btn.setEnabled(False)  # same reasoning as request_sync_now()
        self._refresh_confirmed_display()  # locks every page for the duration
        self.sync_status_label.setText("Reading from device…")
        slot = self._state.get("controller_slot") or 1
        self.read_requested.emit(slot, force_dock_read)

    def set_read_finished(self, success: bool, message: str, device_state: Optional[dict]) -> None:
        self._syncing = False
        self.syncing_changed.emit(False)
        self.sync_status_label.setText(message)
        if success and device_state is not None:
            self._state_confirmed = True
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self.rail.read_button.setEnabled(self._connection_state == "connected")
        self.ownership_bar.set_release_enabled(self._connection_state == "connected")
        self.rail.set_nav_enabled(True)
        self.import_export_btn.setEnabled(True)
        if not success or device_state is None:
            if not success:
                QMessageBox.warning(self, "Read from device failed", message)
            return
        # Merge key-by-key rather than replacing the layer dict wholesale --
        # read_state() coverage isn't exhaustive, so replace-the-whole-dict
        # isn't safe to bet user data on.
        for layer in ("default", "shift"):
            self._state["buttons"].setdefault(layer, {}).update(device_state["buttons"].get(layer, {}))
        self._state["dpad_diagonal_lock"] = device_state["dpad_diagonal_lock"]
        self._state["swap_stick_dpad"] = device_state["swap_stick_dpad"]
        # Continuous Trigger. Must land BEFORE the Buttons view repaints on
        # the next line, or the checkboxes are painted from the previous
        # state and the device's values arrive too late to show. Replaced
        # wholesale, not merged: decode_continuous_triggers() returns every
        # button-table slot on every read.
        self._state["continuous_trigger"] = device_state.get("continuous_trigger", {})
        self.buttons_view.load_state(self._state)
        self.overview_view.load_state(self._state)

        self._state["sticks"] = device_state["sticks"]
        self._state["triggers"] = device_state["triggers"]
        self._state["motion"] = device_state["motion"]
        self._state["vibration"] = device_state["vibration"]
        self._state["report_rate_hz"] = device_state["report_rate_hz"]
        # None means "not read this call" (the watcher skips this
        # device-global blob after the first read per connection), not
        # "read back empty" -- keep whatever value is already showing.
        #
        # Also guarded on self._dock_draft having nothing outstanding --
        # Dock is the shared-scope page (DESIGN-SPEC.md 10.1 #5: its draft
        # survives a profile switch), and this read can be exactly that
        # switch's own triggered read. Applying a fresh dock value over a
        # pending, unwritten Dock edit here would silently discard it --
        # the same class of bug B2 exists to prevent, just at the GUI
        # layer instead of the write layer. settings_view.load_state() is
        # skipped for the same reason: it would reset the view's own
        # mark/revert UI for a field this app just decided NOT to
        # overwrite.
        if self._dock_draft.edit_count == 0:
            if device_state["dock_led_brightness"] is not None:
                self._state["dock_led_brightness"] = device_state["dock_led_brightness"]
            if device_state["dock_auto_on_off"] is not None:
                self._state["dock_auto_on_off"] = device_state["dock_auto_on_off"]
            self.settings_view.load_state(self._state)
            self._reset_dock_draft()
        self._sync_report_rate_combo()
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.motion_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self._reset_vibration_draft()  # a real Read -- a fresh, confirmed ObservedSnapshot
        self._reset_triggers_draft()
        self._reset_sticks_draft()
        self._reset_motion_draft()
        self._reset_buttons_draft()
        self._reset_profile_draft()

        self._set_dirty(False)  # local state now matches the device, not a pending change

    def _load_views_from_state(self, imported: bool = False) -> None:
        self._sync_profile_switch()
        self._sync_report_rate_combo()
        self.buttons_view.load_state(self._state)
        self.overview_view.load_state(self._state)
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.motion_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)
        self._reset_vibration_draft(imported=imported)
        self._reset_dock_draft(imported=imported)
        self._reset_triggers_draft(imported=imported)
        self._reset_sticks_draft(imported=imported)
        self._reset_motion_draft(imported=imported)
        self._reset_buttons_draft(imported=imported)
        self._reset_profile_draft(imported=imported)
        self._set_dirty(False)

    def _sync_profile_switch(self) -> None:
        """Reflect self._state["controller_slot"] in the rail switch without
        re-triggering _on_profile_changed (which would otherwise fire a
        redundant read/no-op write for a value that just came FROM state,
        not from the user picking a new one)."""
        if self._viewing_shift:
            # A read finishing must not yank the user out of the Shift view
            # back to whichever profile it happened to target. The Shift
            # layer came back with that read anyway -- it is global.
            return
        self._loading_profile_switch = True
        try:
            self.rail.set_profile(self._state.get("controller_slot") or 1)
        finally:
            self._loading_profile_switch = False
        self._sync_overview_scope()

    def _on_profile_changed(self, slot: object) -> None:
        if self._loading_profile_switch:
            return
        self._apply_view(slot)
        self._state["controller_slot"] = slot
        self._sync_overview_scope()
        # The values on screen right now were confirmed (if ever) against
        # whichever profile was selected before, not this one -- they say
        # nothing about this profile until a read of it succeeds. Clearing
        # here, not only on read failure, is what stops a failed OR declined
        # read from leaving the previous profile's real values on screen
        # looking exactly like a confirmed reading of the new selection.
        self._state_confirmed = False
        # Vibration's, Triggers', Sticks', Motion's, Buttons', and
        # Profile Settings' drafts are all per-profile scope, not shared
        # (DESIGN-SPEC.md 10.1 #5) -- a switch discards them, same as
        # every other page's unsynced edits, until scoped intents exist
        # to do better.
        self._reset_vibration_draft()
        self._reset_triggers_draft()
        self._reset_sticks_draft()
        self._reset_motion_draft()
        self._reset_buttons_draft()
        self._reset_profile_draft()
        self._refresh_confirmed_display()
        self._refresh_sync_btn()
        if self._connection_state == "connected" and not self._syncing:
            self.request_read_from_device()

    def _on_page_requested(self, key: str) -> None:
        if key == "shift":
            self._select_shift_view()
            return
        if key == "buttons" and self._viewing_shift:
            # Both "buttons" and "shift" route to the same buttons_view
            # widget, so a plain setCurrentWidget() here was a no-op: the
            # rail's exclusive button group checks "Buttons" purely from
            # the click, but nothing told buttons_view to leave shift mode
            # or restored the profile switch -- real bug, found in A6's
            # code review, 2026-10-22. Treat it exactly like picking the
            # current profile, since that's genuinely what "Buttons" means
            # once you're not on Shift.
            self._apply_view(self._state.get("controller_slot") or 1)
            self._sync_profile_switch()
            return
        self.pages.setCurrentWidget(self._page_widgets[key])

    def _select_shift_view(self) -> None:
        """Choosing Shift never changes `controller_slot` -- it is one
        layer shared by all four profiles, not addressed by a profile
        number at all (see `_apply_view`'s own comment)."""
        self._apply_view(SHIFT_VIEW)
        self.rail.profile_switch.set_value(None)  # off-scale: Shift isn't one of the 4 slots

    def _apply_view(self, selected) -> None:
        """Show the Shift layer's single screen, or the full per-profile
        set. The Shift blob carries stick/trigger/vibration bytes only
        because every one of the five blobs shares a 480-byte layout --
        their values are plain factory defaults and Nexus never exposes
        them, and nothing can write them (the Sticks/Triggers/Vibration/
        Report Rate prefixes carry a plain profile number, and there is no
        profile number that addresses the Shift blob). So those rail
        entries are hidden here rather than shown and quietly ignored --
        same behaviour as the old per-tab hiding this replaces, including
        hiding Dock, which is also shared/device-wide: not fixed here,
        A3 is layout only.
        """
        shift_view = selected == SHIFT_VIEW
        self._viewing_shift = shift_view
        self.buttons_view.set_layer("shift" if shift_view else "default")
        for key in PROFILE_PAGE_KEYS:
            if key == "buttons":
                continue  # Buttons stays reachable -- it's the Shift screen itself
            self.rail.set_page_visible(key, not shift_view)
        self.rail.set_page_visible("dock", not shift_view)
        if shift_view:
            self.rail.set_current_page("shift")
            self.pages.setCurrentWidget(self.buttons_view)
        else:
            self.rail.set_page_visible("shift", True)
            if self.rail.current_page() in ("shift",):
                self.rail.set_current_page("buttons")
                self.pages.setCurrentWidget(self.buttons_view)

    def _sync_report_rate_combo(self) -> None:
        """Reflect self._state["report_rate_hz"] in every control that
        shows it -- the Settings page's own combo (same loading-guard
        reasoning as _sync_profile_switch()) and Overview's independent
        instance (D2's Overview work, 2026-10-22), which guards its own
        signal via blockSignals() rather than this flag."""
        hz = self._state.get("report_rate_hz") or 1000
        self._loading_report_rate_combo = True
        try:
            # Falls back to 1000 Hz -- default_state_dict()'s own confirmed
            # default, not just "whatever happens to be last."
            value = str(hz) if hz in (250, 500, 1000) else "1000"
            self.report_rate_combo.set_value(value)
        finally:
            self._loading_report_rate_combo = False
        self.overview_view.set_report_rate(hz)

    def _on_report_rate_changed(self, value: object) -> None:
        if self._loading_report_rate_combo or value is None:
            return
        self._state["report_rate_hz"] = int(value)
        # Keeps whichever combo the user did NOT just touch in sync --
        # two independent SegmentedControl instances now show this value
        # (Settings page, Overview), not one.
        self._sync_report_rate_combo()
        self._on_dirty()
        self._mark_report_rate_touched(int(value))

    def _default_snapshot_dir(self) -> str:
        return str(_LEGACY_PROFILES_DIR if _LEGACY_PROFILES_DIR.is_dir() else Path.home())

    def _on_export(self) -> None:
        # Also guarded by import_export_btn being disabled during a sync/read
        # -- checked here too, same belt-and-suspenders reasoning as
        # request_read_from_device()'s own self._syncing check. self._state
        # is the exact dict object the watcher thread may be iterating
        # mid-sync; reading it concurrently here would be a data race.
        if self._syncing:
            return
        # Declining "Discard unsynced changes?" after picking a different
        # profile leaves self._state["controller_slot"] pointing at the
        # NEWLY selected profile while self._state itself still holds the
        # PREVIOUS profile's real, dirty values -- exactly the case
        # _state_confirmed=False exists to flag (see _on_profile_changed).
        if not self._state_confirmed:
            QMessageBox.warning(
                self, "Export unavailable",
                "The current settings haven't been confirmed against the controller "
                "(or an import) yet -- read from the device or import a snapshot first.",
            )
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export State", self._default_snapshot_dir(), "JSON files (*.json)",
        )
        if not path:
            return
        try:
            state_mod.save_state(path, self._state)
        except (state_mod.StateError, OSError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_label.setText(f"Exported to {Path(path).name}")

    def _on_import(self) -> None:
        # Same guard as _on_export(): replacing self._state mid-sync would
        # leave the in-flight job's set_sync_finished()/set_read_finished()
        # clearing the dirty flag against the *imported* state once it
        # lands, as if the imported state -- not what was actually pushed
        # -- had just been synced.
        if self._syncing:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import State", self._default_snapshot_dir(), "JSON files (*.json)",
        )
        if not path:
            return
        try:
            imported = state_mod.load_state(path)
        except (state_mod.StateError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self._state = imported
        self._state_confirmed = True
        self._load_views_from_state(imported=True)
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self._set_dirty(True)
        self.status_label.setText(f"Imported {Path(path).name} -- not yet synced")

    # --- Help menu -----------------------------------------------------

    def _on_about(self) -> None:
        QMessageBox.about(self, "About G7 Control Center", help_content.ABOUT_HTML)

    def _on_ondevice_features(self) -> None:
        QMessageBox.information(self, "On-Device Features", help_content.ON_DEVICE_FEATURES_HTML)

    def _on_report_issue(self) -> None:
        QDesktopServices.openUrl(QUrl(help_content.ISSUES_URL))

    def _on_app_preferences(self) -> None:
        # Content is A4's job (DESIGN-SPEC.md section 3's decision table:
        # its own rail-footer entry, not under Help). This phase gives it
        # the entry and a real, honest placeholder rather than a dead
        # click or an invented "Reduce motion" checkbox that does nothing.
        dialog = ModalOverlayBase(self._theme.palette, self)
        dialog.setWindowTitle("App preferences")
        label = QLabel(
            "No preferences yet -- Reduce motion and other app-level "
            "settings land in a later phase.", dialog)
        label.setWordWrap(True)
        dialog.content_layout.addWidget(label)
        close_button = QPushButton("Close", dialog)
        close_button.clicked.connect(dialog.accept)
        dialog.content_layout.addWidget(close_button)
        dialog.exec()

    def _on_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self.status_label.setText("Unsynced changes")
        else:
            self.status_label.setText("")
