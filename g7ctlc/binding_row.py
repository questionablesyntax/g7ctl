"""BindingRow, A4 of the redesign (`DIRECTION-A.md` section 5's
component inventory: "base, shift-reference" variants). One row of the
Buttons page: a name, the editable binding for whichever layer is
currently active on this page, a Latch (Continuous Trigger) control or
its "not applicable" reason, and -- on the per-profile Buttons page only
-- a read-only reference showing what the Shift layer holds for this same
button (`DIRECTION-A.md` section 3: "The Shift column is read-only
reference").

Both the default-layer and shift-layer `BindingField`s are always built
and always kept current, only visibility toggles between them -- same
invariant `buttons_view.py`'s pre-redesign combos relied on (switching
views must never look like switching values, or a hidden field's real
value would get swept away on the next edit). `ButtonsView` owns the
shared `KeycodePicker` and wires each field's `clicked` signal to it;
this class only builds and lays out the row.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from g7ctlc.binding_field import BindingField
from g7ctlc.checkbox import Checkbox
from g7ctlc.widgets import keycode_display_text

NAME_COL_WIDTH = 140
LATCH_COL_WIDTH = 90
# DIRECTION-A.md section 5's "the content measure caps at 760px for form
# columns" -- found unimplemented in A6's design critique: at the real
# 1120px default window width, default_field/shift_field/shift_reference
# (each a stretch-1 column) grew unboundedly instead. Capped on the row
# itself, not the individual fields, so Qt's own layout still splits the
# available width between them proportionally in both "default" mode (two
# stretch columns) and "shift" mode (one) -- no per-mode pixel math needed.
MAX_ROW_WIDTH = 760


class BindingRow(QWidget):
    def __init__(
        self,
        name: str,
        *,
        latch_reason: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """`latch_reason=None` builds a real Latch checkbox; a string
        builds the "why not" text LT/RT show instead (they have no
        button-table record to hold a Continuous Trigger byte at all --
        see `pyg7.buttons.continuous_trigger_offset()`)."""
        super().__init__(parent)
        self.setMaximumWidth(MAX_ROW_WIDTH)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.name_label = QLabel(name, self)
        self.name_label.setFixedWidth(NAME_COL_WIDTH)
        layout.addWidget(self.name_label)

        self.default_field = BindingField(self)
        self.default_field.setAccessibleName(f"{name}, Base layer")
        layout.addWidget(self.default_field, 1)

        self.shift_field = BindingField(self)
        self.shift_field.setAccessibleName(f"{name}, Shift layer")
        layout.addWidget(self.shift_field, 1)

        # Column order matches the header ButtonsView builds (Button | Base
        # layer | Shift (shared) | Latch) -- shift_reference before latch,
        # not after. Caught by actually rendering the page and looking at
        # it: the two were swapped relative to the header on the first pass.
        self.shift_reference = QLabel("", self)
        self.shift_reference.setProperty("role", "secondary")
        self.shift_reference.setAccessibleName(f"{name}, Shift layer (shared), reference only")
        layout.addWidget(self.shift_reference, 1)

        self.latch: Checkbox | None = None
        self.latch_reason_label: QLabel | None = None
        if latch_reason is None:
            self.latch = Checkbox("", self)
            self.latch.setAccessibleName(f"{name}, Latch")
            self.latch.setFixedWidth(LATCH_COL_WIDTH)
            layout.addWidget(self.latch)
        else:
            self.latch_reason_label = QLabel(latch_reason, self)
            self.latch_reason_label.setProperty("role", "secondary")
            self.latch_reason_label.setWordWrap(True)
            self.latch_reason_label.setFixedWidth(LATCH_COL_WIDTH)
            layout.addWidget(self.latch_reason_label)

        self.set_mode("default")

    def set_shift_reference(self, value: str | None) -> None:
        """Mirrors `shift_field`'s value into the read-only reference
        label -- call this whenever `shift_field` changes, whether from a
        fresh `load_state()` or an edit made on the Shift page."""
        self.shift_reference.setText(
            "No Shift binding" if value is None else keycode_display_text(value)
        )

    def set_mode(self, mode: str) -> None:
        """"default": Base layer editable, Latch, read-only Shift
        reference. "shift": Shift layer editable, no Latch, no
        reference (it would just repeat the field beside it)."""
        shift_mode = mode == "shift"
        self.default_field.setVisible(not shift_mode)
        self.shift_field.setVisible(shift_mode)
        if self.latch is not None:
            self.latch.setVisible(not shift_mode)
        if self.latch_reason_label is not None:
            self.latch_reason_label.setVisible(not shift_mode)
        self.shift_reference.setVisible(not shift_mode)
