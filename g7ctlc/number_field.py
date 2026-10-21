"""NumberField, A2 of the redesign (`DIRECTION-A.md` section 5: "percent,
0-255, bits" variants). A `QSpinBox` subclass adding the behaviour the
bare widget doesn't give you for free:

- PageUp/PageDown steps by 10, Up/Down by 1 (`QAbstractSpinBox` only wires
  Up/Down to `stepBy` on its own; PageUp/PageDown do nothing without this).
- An `error` state while the typed text is momentarily out of range (the
  field still clamps on commit -- `QSpinBox` always has -- but the typed
  digits are flagged instead of silently refusing the keystroke).
- `unread` suppresses the displayed number entirely ("no number", not a
  placeholder) while leaving the underlying value untouched, matching
  `DESIGN-SPEC.md` section 2's "unknown is not a value" rule. The hatch
  paint itself is A5's job, same split as `segmented_control.py`/
  `checkbox.py`.
- `edited` is a settable accessible-name hook, same split.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSpinBox, QWidget


class NumberField(QSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edited = False
        self._unread = False
        self._error = False
        self._base_accessible_name = ""
        self.lineEdit().textEdited.connect(self._on_text_edited)

    # -- variants ---------------------------------------------------------

    @classmethod
    def percent(cls, parent: QWidget | None = None) -> NumberField:
        field = cls(parent)
        field.setRange(0, 100)
        field.setSuffix("%")
        return field

    @classmethod
    def byte_value(cls, parent: QWidget | None = None) -> NumberField:
        field = cls(parent)
        field.setRange(0, 255)
        return field

    @classmethod
    def bits(cls, parent: QWidget | None = None) -> NumberField:
        field = cls(parent)
        field.setRange(0, 255)
        field.setDisplayIntegerBase(16)
        field.setPrefix("0x")
        return field

    # -- stepping -----------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if event.key() == Qt.Key.Key_PageUp:
            self.stepBy(10)
            return
        if event.key() == Qt.Key.Key_PageDown:
            self.stepBy(-10)
            return
        super().keyPressEvent(event)

    # -- error state ----------------------------------------------------

    def _on_text_edited(self, text: str) -> None:
        body = text
        if self.prefix() and body.startswith(self.prefix()):
            body = body[len(self.prefix()):]
        if self.suffix() and body.endswith(self.suffix()):
            body = body[: len(body) - len(self.suffix())]
        out_of_range = False
        if body:
            try:
                typed = int(body, self.displayIntegerBase())
            except ValueError:
                typed = None
            if typed is not None and not (self.minimum() <= typed <= self.maximum()):
                out_of_range = True
        self._set_error(out_of_range)

    def _set_error(self, error: bool) -> None:
        if error == self._error:
            return
        self._error = error
        self.setProperty("error", error)
        self.setToolTip(f"Enter {self.minimum()} to {self.maximum()}" if error else "")
        self.style().unpolish(self)
        self.style().polish(self)

    def is_error(self) -> bool:
        return self._error

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        super().focusOutEvent(event)
        self._set_error(False)  # QSpinBox has clamped the value by now

    # -- unread: no number, value untouched --------------------------------

    def textFromValue(self, value: int) -> str:  # noqa: N802 - Qt override signature
        if self._unread:
            return ""
        return super().textFromValue(value)

    def set_unread(self, unread: bool) -> None:
        was_unread = self._unread
        self._unread = unread  # textFromValue() reads this; set it before touching prefix/suffix below
        if unread and not was_unread:
            self._visible_prefix, self._visible_suffix = self.prefix(), self.suffix()
            self.setPrefix("")
            self.setSuffix("")  # prefix/suffix wrap textFromValue(), so "no number" needs both cleared
        elif not unread and was_unread:
            self.setPrefix(self._visible_prefix)
            self.setSuffix(self._visible_suffix)
        self.setProperty("unread", unread)
        self.setEnabled(not unread)
        self._sync_accessible_name()

    def is_unread(self) -> bool:
        return self._unread

    # -- edited: accessible-name hook ----------------------------------

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
        suffix = ""
        if self._unread:
            suffix = ", unread"
        elif self._edited:
            suffix = ", edited"
        super().setAccessibleName(f"{self._base_accessible_name}{suffix}")
