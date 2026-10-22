"""BindingField, A4 of the redesign. The clickable trigger that replaces
`make_keycode_combo()`'s plain `QComboBox` on a re-skinned page
(`DIRECTION-A.md` section 3: "Keycode picker (replaces the combo)").

Displays the current binding via `widgets.keycode_display_text()` and
opens a shared `KeycodePicker` (A2) on click/Enter/Space -- `QPushButton`
already gives those three activation paths for free, which is why this is
a `QPushButton` subclass rather than a custom-painted field.

Does not own a `KeycodePicker` itself: a page with many rows shares one
instance (`ButtonsView._picker`, wired in `_open_picker_for()`) rather
than building 21 popovers that are never open at the same time.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QPushButton, QWidget

from g7ctlc.widgets import is_known_keycode, keycode_display_text


class BindingField(QPushButton):
    # D2: lets a page (ButtonsView) sync a controller-diagram highlight to
    # whichever field has keyboard focus, not just mouse clicks -- Tab
    # alone must reach every button this field represents.
    focused = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "binding-field")
        self._value: str | None = None
        self._known = True
        self._edited = False
        self._base_accessible_name = ""
        self._refresh_text()

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override signature
        super().focusInEvent(event)
        self.focused.emit()

    def set_value(self, value: str | None, *, known: bool | None = None) -> None:
        self._value = value
        self._known = is_known_keycode(value) if known is None else known
        self._refresh_text()

    def value(self) -> str | None:
        return self._value

    def is_known(self) -> bool:
        return self._known

    def _refresh_text(self) -> None:
        text = keycode_display_text(self._value) if self._known else f"Raw: {self._value}"
        self.setText(text)
        self.setProperty("unrecognised", not self._known)
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_accessible_name()

    def set_edited(self, edited: bool) -> None:
        self._edited = edited
        self.setProperty("edited", edited)
        self._sync_accessible_name()

    def is_edited(self) -> bool:
        return self._edited

    def setAccessibleName(self, name: str) -> None:  # noqa: N802 - Qt override signature
        self._base_accessible_name = name
        super().setAccessibleName(name)
        self._sync_accessible_name()

    def _sync_accessible_name(self) -> None:
        suffix = ", edited" if self._edited else ""
        base = self._base_accessible_name
        super().setAccessibleName(f"{base}: {self.text()}{suffix}" if base else f"{self.text()}{suffix}")
