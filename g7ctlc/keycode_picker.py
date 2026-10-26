"""KeycodePicker, A2 of the redesign (`DIRECTION-A.md` section 5):
"popover listbox... closed, open, filtered, empty search ('No key matches
'f13'.'), item hover, focus, selected, unconfirmed items labelled."

Reuses `g7ctlc.widgets.KEYCODE_GROUPS`/`KNOWN_KEYCODES` rather than
retyping the keycode list -- that file's own `_assert_keycode_coverage()`
is still the one guarantee that every known keycode is reachable from
somewhere; this widget would silently drift from it otherwise.

Raw/unrecognised codes are preserved exactly like `widgets.py`'s
`select_by_data`: a value that isn't in `KNOWN_KEYCODES` gets its own
"Raw: {value}" item instead of falling back to "(Default)" -- falling
back would misreport the device and then let the next unrelated edit drop
the binding entirely (`widgets.py` explains the full failure chain).

The optional Latch row (`open_for`'s `latch`/`latch_reason`), added for
the Buttons page's D2 rework (2026-10-22, decision: drop the
side-panel table entirely, fold Latch into the one place a button's
binding is already being edited rather than keep a second, separate
surface for it). Sticks' and Motion's own direction pickers never pass
either, so they keep getting no Latch row at all -- it was never
applicable there.

The optional "was X"/Revert row (`open_for`'s `was_text`), added for
Buttons' own S6 slice (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md,
Track S): the same "second optional row, shown conditionally" shape the
Latch row already established, not a new mechanism. Buttons has no
per-button widget to attach a "was X%" row to the way every other
page's form-row fields do (see buttons_view.py's own module docstring
for why that's a deliberate, hard-won design decision) -- this popover
is the one per-button editing surface that exists, so the touch/revert
affordance lives here instead.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from g7ctlc.checkbox import Checkbox
from g7ctlc.widgets import KEYCODE_GROUPS

_HEADER = "__header__"


class KeycodePicker(QWidget):
    """A popover listbox, not a modal dialog -- it closes on Escape or on
    losing focus, same as a combo box's own dropdown (`Qt.WindowType.Popup`
    gives this for free).
    """

    codeChosen = pyqtSignal(object)  # emits the keycode name (str), or None for "(Default)"
    # Latch doesn't close the popover (unlike choosing a code) -- a user
    # may want to toggle it and still pick a different key, or vice versa,
    # in the same visit.
    latchToggled = pyqtSignal(bool)
    # Unlike codeChosen, this carries no value -- the caller already knows
    # which field is open (the same thing codeChosen's own caller tracks)
    # and what its own loaded baseline is. Closes the popover, same as
    # choosing a code (not latchToggled's "stays open" behaviour): a revert
    # is a complete, decided edit, not a value you'd keep adjusting.
    revertRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search keys...")
        self.search.setAccessibleName("Search keys")
        self.search.textChanged.connect(self._apply_filter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.was_row = QWidget(self)
        was_row_layout = QHBoxLayout(self.was_row)
        was_row_layout.setContentsMargins(0, 0, 0, 0)
        self.was_label = QLabel(self.was_row)
        self.was_label.setProperty("role", "muted")
        was_row_layout.addWidget(self.was_label)
        self.revert_btn = QPushButton("Revert", self.was_row)
        self.revert_btn.setProperty("role", "link")
        self.revert_btn.clicked.connect(self._on_revert_clicked)
        was_row_layout.addWidget(self.revert_btn)
        was_row_layout.addStretch(1)
        layout.addWidget(self.was_row)
        self.was_row.setVisible(False)

        self.latch_row = QWidget(self)
        latch_row_layout = QHBoxLayout(self.latch_row)
        latch_row_layout.setContentsMargins(0, 0, 0, 0)
        self.latch_checkbox = Checkbox("Latch", self.latch_row)
        self.latch_checkbox.toggled.connect(self.latchToggled)
        latch_row_layout.addWidget(self.latch_checkbox)
        self.latch_reason_label = QLabel(self.latch_row)
        self.latch_reason_label.setProperty("role", "secondary")
        self.latch_reason_label.setWordWrap(True)
        latch_row_layout.addWidget(self.latch_reason_label)
        layout.addWidget(self.latch_row)
        self.latch_row.setVisible(False)

        self.list = QListWidget(self)
        self.list.setAccessibleName("Key")
        self.list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.list)

        self._current_value: str | None = None
        self._raw_value: str | None = None
        self._populate()

    # -- population / filtering -----------------------------------------

    def _populate(self) -> None:
        self.list.clear()
        default_item = QListWidgetItem("(Default)")
        default_item.setData(Qt.ItemDataRole.UserRole, None)
        self.list.addItem(default_item)

        if self._raw_value is not None:
            raw_item = QListWidgetItem(f"Raw: {self._raw_value}")
            raw_item.setData(Qt.ItemDataRole.UserRole, self._raw_value)
            raw_item.setToolTip("Read from the controller; not offered by this picker.")
            self.list.addItem(raw_item)

        for group_label, entries in KEYCODE_GROUPS:
            header = QListWidgetItem(f"— {group_label} —")
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
            header.setData(Qt.ItemDataRole.UserRole, _HEADER)
            self.list.addItem(header)
            for name, short_label in entries:
                item = QListWidgetItem(f"{group_label}: {short_label}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.list.addItem(item)

        self._select_value(self._current_value)

    def _apply_filter(self, query: str) -> None:
        query = query.strip().lower()
        any_visible = False
        header_item: QListWidgetItem | None = None
        header_has_visible_child = False
        for row in range(self.list.count()):
            item = self.list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data == _HEADER:
                if header_item is not None:
                    header_item.setHidden(not header_has_visible_child)
                header_item = item
                header_has_visible_child = False
                continue
            is_pinned = data is None or (self._raw_value is not None and data == self._raw_value)
            if is_pinned:
                # "(Default)" and the preserved raw entry only show with an
                # empty filter -- they have no group label to match against.
                item.setHidden(bool(query))
                continue
            matches = not query or query in item.text().lower()
            item.setHidden(not matches)
            if matches:
                header_has_visible_child = True
                any_visible = True
        if header_item is not None:
            header_item.setHidden(not header_has_visible_child)

        self._empty_query = query if not any_visible and query else None

    def no_match_text(self) -> str | None:
        """The empty-search copy (`DIRECTION-A.md`: 'No key matches
        "f13".'), or None while there's at least one visible match."""
        query = getattr(self, "_empty_query", None)
        return f'No key matches "{query}".' if query else None

    # -- was/revert row -----------------------------------------------------

    def _on_revert_clicked(self) -> None:
        self.revertRequested.emit()
        self.close()

    def _set_was_row(self, was_text: str | None) -> None:
        self.was_row.setVisible(was_text is not None)
        if was_text is not None:
            self.was_label.setText(was_text)

    # -- latch row ----------------------------------------------------------

    def _set_latch_row(self, latch: bool | None, latch_reason: str | None) -> None:
        if latch_reason is not None:
            self.latch_checkbox.setVisible(False)
            self.latch_reason_label.setVisible(True)
            self.latch_reason_label.setText(latch_reason)
            self.latch_row.setVisible(True)
            return
        if latch is not None:
            self.latch_checkbox.setVisible(True)
            self.latch_reason_label.setVisible(False)
            self.latch_checkbox.blockSignals(True)
            self.latch_checkbox.setChecked(latch)
            self.latch_checkbox.blockSignals(False)
            self.latch_row.setVisible(True)
            return
        self.latch_row.setVisible(False)

    # -- selection --------------------------------------------------------

    def _select_value(self, value: str | None) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == value:
                self.list.setCurrentItem(item)
                return

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data == _HEADER:
            return
        self._current_value = data
        self.codeChosen.emit(data)
        self.close()

    # -- public entry point -------------------------------------------------

    def open_for(
        self,
        anchor: QWidget,
        current_value: str | None,
        *,
        known: bool,
        latch: bool | None = None,
        latch_reason: str | None = None,
        was_text: str | None = None,
    ) -> None:
        """Show the popover anchored below `anchor`. `known=False` means
        `current_value` isn't in `KNOWN_KEYCODES` -- it gets its own
        preserved "Raw: ..." entry rather than being lost.

        `latch`/`latch_reason` are both `None` by default, which hides the
        Latch row entirely (Sticks' and Motion's direction pickers, and
        the Buttons page's own picker when it isn't applicable, e.g. the
        Shift layer). Passing `latch_reason` (a string) shows that text
        instead of a checkbox -- LT/RT, which have no Latch byte at all.
        Passing `latch` (a bool) shows a real, checked-to-match checkbox;
        toggling it emits `latchToggled`, not `codeChosen` -- the two are
        independent edits that happen to share one popover now.

        `was_text` is `None` by default, which hides the was/Revert row --
        the caller passes a real string (already formatted, e.g.
        `keycode_display_text()`'s own wording) only when the field being
        opened has an outstanding, unwritten touch; this widget has no
        opinion of its own on what "touched" means or how to word it."""
        self._current_value = current_value
        self._raw_value = current_value if not known and current_value is not None else None
        self._set_was_row(was_text)
        self._set_latch_row(latch, latch_reason)
        self.search.clear()
        self._populate()
        point = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(point)
        # Real bug, found in A6's code review (2026-10-22): this used
        # self.width()/height(), the widget's own pre-layout size (Qt's
        # default top-level 640x480, or whatever a previous open last left
        # it at) -- never the ~100-item list's actual content, which
        # sizeHint() reflects. The popover opened oversized (or stale)
        # every time instead of a compact anchored popup.
        hint = self.sizeHint()
        self.resize(max(hint.width(), anchor.width()), hint.height())
        self.show()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)

    # -- forward Up/Down/Enter from the search field to the list ------

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override signature
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._move_current(+1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                current = self.list.currentItem()
                if current is not None:
                    self._on_item_activated(current)
                return True
        return super().eventFilter(watched, event)

    def _move_current(self, step: int) -> None:
        count = self.list.count()
        if count == 0:
            return
        start = self.list.currentRow()
        row = start
        for _ in range(count):
            row = (row + step) % count
            item = self.list.item(row)
            if not item.isHidden() and item.data(Qt.ItemDataRole.UserRole) != _HEADER:
                self.list.setCurrentRow(row)
                return

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
