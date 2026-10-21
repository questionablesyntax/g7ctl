"""Checkbox, A2 of the redesign. A thin `QCheckBox` subclass: the
default/hover/focus/checked/disabled states are already correct from
`QCheckBox` plus A1's QSS (`DIRECTION-A.md` section 2's revision table --
checkboxes, never toggle switches, since nothing applies until written).

What this subclass actually adds is `edited`/`unread` as settable state
with a real accessible-name effect, tested here. The pixel-level hatch
treatment for `unread` is A5's job ("Wave-1 states and polish"); this
class exists so A5 has one place to add it rather than every page that
uses a checkbox.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QWidget


class Checkbox(QCheckBox):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._edited = False
        self._unread = False
        self._base_accessible_name = text
        self.setAccessibleName(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override signature
        super().setText(text)
        self._base_accessible_name = text
        self._sync_accessible_name()

    def set_edited(self, edited: bool) -> None:
        self._edited = edited
        self.setProperty("edited", edited)
        self._sync_accessible_name()

    def is_edited(self) -> bool:
        return self._edited

    def set_unread(self, unread: bool) -> None:
        self._unread = unread
        self.setProperty("unread", unread)
        self.setEnabled(not unread)
        self._sync_accessible_name()

    def is_unread(self) -> bool:
        return self._unread

    def _sync_accessible_name(self) -> None:
        suffix = ""
        if self._unread:
            suffix = ", unread"
        elif self._edited:
            suffix = ", edited"
        self.setAccessibleName(f"{self._base_accessible_name}{suffix}")
