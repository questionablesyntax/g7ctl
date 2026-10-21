"""SegmentedControl, A2 of the redesign (`DIRECTION-A.md` section 5: "text,
stepped meter" variants). Built as styled checkable buttons in an exclusive
`QButtonGroup`, per `DESIGN-SPEC.md` 10.2 item 7 -- not custom-painted, so
the platform's own button semantics (focus, press feedback, accessible
state) stay intact.

Scope note: `edited`/`unread` are wired as plain Qt dynamic properties here
(settable, queryable, included in the accessible name) but carry no visual
treatment yet. The hatch overlay and the unread-to-read reveal are A5's
deliverable ("Wave-1 states and polish"); wiring the hook now means A5 has
something to attach to instead of touching this file again.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class SegmentedControl(QWidget):
    """One exclusive group of segments, identified by string value.

    `meter=True` selects the stepped-meter variant (`DIRECTION-A.md`
    section 5): the same exclusive-selection model, but every segment at
    or below the selected index is marked `filled="true"` so the QSS can
    paint a cumulative bar rather than a single highlighted choice (e.g.
    vibration intensity).

    Keyboard: Left/Right/Home/End move *and* select, matching the ARIA
    "radiogroup with roving tabindex" pattern -- only the selected segment
    is a Tab stop; the others are reachable by arrow key once inside the
    group. This matches `QButtonGroup`'s own exclusive-selection semantics,
    it does not reimplement them.
    """

    selectionChanged = pyqtSignal(object)  # emits the selected value, or None (off-scale)

    def __init__(
        self,
        items: Sequence[tuple[str, str]],
        *,
        meter: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """`items` is `[(value, label), ...]` in display order."""
        super().__init__(parent)
        if not items:
            raise ValueError("SegmentedControl needs at least one segment")
        self._meter = meter
        self._values = [value for value, _label in items]
        self._edited = False
        self._unread = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0 if meter else 4)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for index, (value, label) in enumerate(items):
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setProperty("role", "segment")
            button.setProperty("segmentPosition", _position(index, len(items)))
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus if index == 0 else Qt.FocusPolicy.NoFocus)
            button.setAccessibleName(label)
            button.installEventFilter(self)
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[value] = button

        self._group.buttonToggled.connect(self._on_button_toggled)

    # -- selection ------------------------------------------------------

    def value(self) -> str | None:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return None  # off-scale: no segment selected

    def set_value(self, value: str | None) -> None:
        if value is None:
            checked = self._group.checkedButton()
            if checked is not None:
                self._group.setExclusive(False)
                checked.setChecked(False)
                self._group.setExclusive(True)
            self._refresh_fill()
            return
        button = self._buttons.get(value)
        if button is None:
            raise KeyError(f"no such segment: {value!r}")
        button.setChecked(True)

    def is_off_scale(self) -> bool:
        return self.value() is None

    def _on_button_toggled(self, button: QPushButton, checked: bool) -> None:
        if checked:
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            for other in self._buttons.values():
                if other is not button:
                    other.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_fill()
        self.selectionChanged.emit(self.value())

    def _refresh_fill(self) -> None:
        if not self._meter:
            return
        selected = self.value()
        selected_index = self._values.index(selected) if selected in self._values else -1
        for index, value in enumerate(self._values):
            self._buttons[value].setProperty("filled", index <= selected_index)
            self._buttons[value].style().unpolish(self._buttons[value])
            self._buttons[value].style().polish(self._buttons[value])

    # -- edited / unread hooks (A5 attaches the visual treatment) ------

    def set_edited(self, edited: bool) -> None:
        self._edited = edited
        self.setProperty("edited", edited)
        self._sync_accessible_names()

    def is_edited(self) -> bool:
        return self._edited

    def set_unread(self, unread: bool) -> None:
        self._unread = unread
        self.setProperty("unread", unread)
        self.setEnabled(not unread)
        self._sync_accessible_names()

    def is_unread(self) -> bool:
        return self._unread

    def _sync_accessible_names(self) -> None:
        suffix = ""
        if self._unread:
            suffix = ", unread"
        elif self._edited:
            suffix = ", edited"
        for button in self._buttons.values():
            label = button.text()
            button.setAccessibleName(f"{label}{suffix}")

    # -- roving tabindex: arrow keys move focus and selection -----------

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override signature
        if event.type() == event.Type.KeyPress and watched in self._buttons.values():
            key = event.key()
            order = list(self._buttons.values())
            current = order.index(watched)
            if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
                self._move_selection(order, current, +1)
                return True
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
                self._move_selection(order, current, -1)
                return True
            if key == Qt.Key.Key_Home:
                self._select_and_focus(order[0])
                return True
            if key == Qt.Key.Key_End:
                self._select_and_focus(order[-1])
                return True
        return super().eventFilter(watched, event)

    def _move_selection(self, order: list[QPushButton], current: int, step: int) -> None:
        target = order[(current + step) % len(order)]
        self._select_and_focus(target)

    def _select_and_focus(self, button: QPushButton) -> None:
        button.setChecked(True)
        button.setFocus(Qt.FocusReason.OtherFocusReason)


def _position(index: int, count: int) -> str:
    if count == 1:
        return "only"
    if index == 0:
        return "first"
    if index == count - 1:
        return "last"
    return "middle"


class CaptionedSegmentedControl(QWidget):
    """A `SegmentedControl` with the off-scale caption `DIRECTION-A.md`
    section 5 calls for ("off-scale (no segment selected + text)"). Plain
    composition, not inheritance, so callers that don't need the caption
    keep using the bare control.
    """

    selectionChanged = pyqtSignal(object)

    def __init__(
        self,
        items: Sequence[tuple[str, str]],
        off_scale_text: str,
        *,
        meter: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._off_scale_text = off_scale_text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.control = SegmentedControl(items, meter=meter, parent=self)
        self.caption = QLabel(off_scale_text, self)
        self.caption.setProperty("role", "secondary")
        layout.addWidget(self.control)
        layout.addWidget(self.caption)

        self.control.selectionChanged.connect(self._on_selection_changed)
        self._on_selection_changed(self.control.value())

    def _on_selection_changed(self, value: object) -> None:
        self.caption.setVisible(value is None)
        self.selectionChanged.emit(value)

    def value(self) -> str | None:
        return self.control.value()

    def set_value(self, value: str | None) -> None:
        self.control.set_value(value)
