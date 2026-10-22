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
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from g7ctlc.widgets import KEYCODE_GROUPS

_HEADER = "__header__"


class KeycodePicker(QWidget):
    """A popover listbox, not a modal dialog -- it closes on Escape or on
    losing focus, same as a combo box's own dropdown (`Qt.WindowType.Popup`
    gives this for free).
    """

    codeChosen = pyqtSignal(object)  # emits the keycode name (str), or None for "(Default)"

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

    def open_for(self, anchor: QWidget, current_value: str | None, *, known: bool) -> None:
        """Show the popover anchored below `anchor`. `known=False` means
        `current_value` isn't in `KNOWN_KEYCODES` -- it gets its own
        preserved "Raw: ..." entry rather than being lost."""
        self._current_value = current_value
        self._raw_value = current_value if not known and current_value is not None else None
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
