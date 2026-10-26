"""ReviewSheet, S6's wave-2 escalation path (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S/DESIGN-SPEC.md 10.3): "If it finds a
conflict... it escalates to the full review sheet. Any change touching
shared scope, or more than three rows, always uses the sheet." Built on
`ModalOverlayBase` (A2), which was deliberately built ahead of this --
its own module docstring already names this file as the "later review
sheet (wave 2)" its frame/modality/focus-restoration exist for.

Shows every writable outcome from a `pyg7.workflow.PreparedJob` --
already-satisfied ones excluded, since nothing happens for those -- as
a Field / Was / Will be row, per DIRECTION-A.md section 4's own mockup.
A CONFLICT outcome also gets a "Changed on the controller" line showing
`fresh_value` (CRITIC.md #4's disposition: "row mark, 'Now 10% on the
controller', re-review"). `Escape` closes exactly like clicking
**Keep editing** -- ModalOverlayBase's own default `reject()` behaviour,
not overridden here, because closing without writing is never
destructive and needs no extra confirmation (the component inventory's
own words: "Escape = Keep editing").

**Deliberately not built in this first pass**: per-row revert from
inside the sheet (CRITIC.md #12's own mockup shows one). Reverting a
field here would need to call back into whichever page's own per-field
revert method actually owns that path -- a real path-to-view dispatch
this app has no shared concept of yet (each view reverts its own fields
through its own locally-named setting, not a path tuple MainWindow could
dispatch generically). **Write N changes** instead writes every row
shown, `force_conflicts=True` -- reaching this sheet at all means the
user has already SEEN any conflict clearly, which is the informed
consent `execute()`'s own `force_conflicts` flag exists to require.
Keep editing closes the sheet with nothing written; the field stays
exactly as drafted, revertable the normal way on its own page.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from pyg7.buttons import KNOWN_KEYCODES
from pyg7.field_spec import Intent
from pyg7.workflow import Classification, PreparedJob

from .fonts import FontLoadResult, font_for
from .modal_overlay import ModalOverlayBase
from .palette import Palette
from .widgets import keycode_display_text


def format_field_label(path: tuple) -> str:
    """A generic, honest label derived from the path itself -- not a
    hand-maintained per-field map (DIRECTION-A.md section 4's own table
    calls that "interim... until step 3's FieldSpec registry exists",
    which has landed, but without a display-label attribute of its own;
    `ButtonFieldSpec` in particular has no `.name` at all to fall back
    on). Mechanical, so it can never drift out of sync with a new field,
    even if less polished than a hand-tuned "Sticks, left, deadzone
    start" would read."""
    return ", ".join(part.replace("_", " ").title() for part in path)


def format_field_value(value: Any, *, keycode: bool = False) -> str:
    """Same wording a field's own page already shows for this value,
    wherever that convention exists (keycodes), falling back to a
    generic but still-honest rendering otherwise -- never a raw
    internal token like "native_a" or "left_stick" shown unformatted.

    `keycode=True` means the CALLER already knows this row is a
    keycode-shaped field (because some OTHER value on the same row --
    desired, baseline or fresh -- was recognisably one), so this
    specific `None` means "Not remapped" the same way the field's own
    page already shows it, not a generic "Unknown" -- `format_field_value`
    alone has no way to tell those two meanings of `None` apart from one
    bare value."""
    if value is Intent.CLEAR:
        return keycode_display_text(None)
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, str):
        if value in KNOWN_KEYCODES:
            return keycode_display_text(value)
        return value.replace("_", " ").title()
    if value is None:
        return keycode_display_text(None) if keycode else "Unknown"
    return str(value)


def _is_keycode_row(outcome) -> bool:
    for value in (outcome.intent.desired, outcome.baseline_value, outcome.fresh_value):
        if value is Intent.CLEAR or (isinstance(value, str) and value in KNOWN_KEYCODES):
            return True
    return False


class ReviewSheet(ModalOverlayBase):
    """`job.writable` outcomes, one row each. `exec()` returns
    `QDialog.DialogCode.Accepted` for Write, `Rejected` for Keep editing
    or Escape -- the caller is responsible for actually executing
    (`request_execute_reviewed`) only on Accepted."""

    def __init__(self, job: PreparedJob, scope_label: str, palette: Palette,
                 font_load: FontLoadResult, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self.job = job
        rows = job.writable
        self.setWindowTitle(f"Write {len(rows)} change{'s' if len(rows) != 1 else ''} to the controller?")

        title = QLabel(self.windowTitle(), self)
        title.setFont(font_for("title", font_load))
        title.setWordWrap(True)
        self.content_layout.addWidget(title)

        subtitle = QLabel(f"{scope_label}. Compared with what the controller holds now.", self)
        subtitle.setFont(font_for("body", font_load))
        subtitle.setProperty("role", "secondary")
        subtitle.setWordWrap(True)
        self.content_layout.addWidget(subtitle)

        rows_widget = QWidget(self)
        grid = QGridLayout(rows_widget)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        # Explicit floors for the "Was"/"Will be" columns -- without
        # these, QScrollArea's setWidgetResizable(True) below forces
        # rows_widget to whatever width the dialog ends up with, which
        # can squeeze these two columns toward zero and visibly clip
        # "Will be" at the dialog's edge (seen on hardware 2026-10-26,
        # two-row Dock sheet) rather than ever wrapping or eliding.
        grid.setColumnMinimumWidth(1, 70)
        grid.setColumnMinimumWidth(2, 110)
        for header_col, text in enumerate(("Field", "Was", "Will be")):
            header = QLabel(text, rows_widget)
            header.setFont(font_for("label", font_load))
            header.setProperty("role", "secondary")
            grid.addWidget(header, 0, header_col)

        grid_row = 1
        for outcome in rows:
            field_label = QLabel(format_field_label(outcome.intent.path), rows_widget)
            field_label.setFont(font_for("body", font_load))
            field_label.setWordWrap(True)
            grid.addWidget(field_label, grid_row, 0)

            keycode_row = _is_keycode_row(outcome)
            was_label = QLabel(format_field_value(outcome.baseline_value, keycode=keycode_row), rows_widget)
            was_label.setFont(font_for("body", font_load))
            was_label.setProperty("role", "secondary")
            grid.addWidget(was_label, grid_row, 1)

            will_be_label = QLabel(format_field_value(outcome.intent.desired, keycode=keycode_row), rows_widget)
            will_be_label.setFont(font_for("body", font_load))
            grid.addWidget(will_be_label, grid_row, 2)
            grid_row += 1

            if outcome.classification is Classification.CONFLICT:
                conflict_label = QLabel(
                    f"Changed on the controller -- now "
                    f"{format_field_value(outcome.fresh_value, keycode=keycode_row)}.",
                    rows_widget)
                conflict_label.setFont(font_for("small", font_load))
                conflict_label.setProperty("role", "caution")
                conflict_label.setWordWrap(True)
                grid.addWidget(conflict_label, grid_row, 0, 1, 3)
                grid_row += 1

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(rows_widget)
        # setWidgetResizable(True) otherwise lets the scroll area squeeze
        # rows_widget narrower than the grid actually needs (the clipped
        # "Will be" column above) -- floor it at the grid's own natural
        # width so a short dialog can't shrink it, while still letting a
        # wider dialog (a long field label) grow it further.
        scroll.setMinimumWidth(rows_widget.sizeHint().width())
        self.content_layout.addWidget(scroll, 1)

        if any(o.classification is Classification.CONFLICT for o in rows):
            notice = QLabel(
                "Some values have changed on the controller since this was drafted -- "
                "review the rows marked above. Writing will overwrite them with what's shown here.",
                self)
            notice.setFont(font_for("small", font_load))
            notice.setProperty("role", "caution")
            notice.setWordWrap(True)
            self.content_layout.addWidget(notice)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setProperty("role", "separator")
        self.content_layout.addWidget(separator)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.keep_editing_btn = QPushButton("Keep editing", self)
        self.keep_editing_btn.clicked.connect(self.reject)
        button_row.addWidget(self.keep_editing_btn)
        self.write_btn = QPushButton(f"Write {len(rows)} change{'s' if len(rows) != 1 else ''}", self)
        self.write_btn.setProperty("role", "write")
        self.write_btn.clicked.connect(self.accept)
        self.write_btn.setEnabled(bool(rows))
        button_row.addWidget(self.write_btn)
        self.content_layout.addLayout(button_row)

        self.setMinimumWidth(520)
