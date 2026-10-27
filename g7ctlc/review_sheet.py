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

**Per-row revert** (added 2026-10-26, IMPLEMENTATION-PLAN.md's "Not
started" list item 3 -- CRITIC.md #12's own mockup shows one): each
row's own small Revert link emits `rowReverted(path)` so the CALLER can
revert that field for real, on whichever page actually owns it. This
class has no path-to-view dispatch of its own -- the caller resolves
that itself, via `scope_for_path()` (g7ctlc/scopes.py, added alongside S7's
cross-scope batching, so a caller handling a sheet whose rows span more
than one page can dispatch each reverted row to the right one without
needing to track "which scope is this sheet for" as a single value).
The row is then dropped from `self.job` itself (`dataclasses.replace()`
with a narrower `outcomes` tuple -- `execute()` only ever reads
`job.outcomes`/`job.writable`, both computed properties, so this is a
real, sound narrowing, not a cosmetic one) and hidden from the grid;
**Write N changes** re-labels itself to match what's actually left and,
reaching zero, disables itself with a "Nothing left to write" notice
rather than auto-closing -- CRITIC.md #12's own complaint about the
review sheet "clos[ing] itself under the pointer when the last row is
reverted". Closing is still one click away (**Keep editing**), just
never a surprise.

**Write N changes** writes every remaining row, `force_conflicts=True`
-- reaching this sheet at all means the user has already SEEN any
conflict clearly (and could revert it, per above), which is the
informed consent `execute()`'s own `force_conflicts` flag exists to
require. Keep editing closes the sheet with nothing written; any field
never reverted in-sheet stays exactly as drafted, revertable the normal
way on its own page.

**Scope grouping** (added 2026-10-26, S7 -- "Mixed-scope integration"):
when a job's rows span more than one scope (a single "Write all N
changes" batch can now touch Vibration, Dock, Triggers, etc. all at
once -- `MainWindow._on_write_all_clicked()`), rows are grouped under a
per-scope section heading instead of one flat list, so a reader can
tell which page each row came from. A job whose rows all belong to one
scope -- still the overwhelming common case, since escalation itself
has no "more than one scope" trigger of its own (dropped the same day
it was proposed: the read was that the sheet is a soft-
error surface, "something's weird, take a look," not a toll gate on
touching more than one page) -- renders exactly as before, no grouping
visible at all.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from PyQt6.QtCore import pyqtSignal
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
from .scopes import SCOPE_LABELS, scope_for_path
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
    (`request_execute_reviewed`) only on Accepted, and must read
    `sheet.job` (not the `job` it originally passed in) at that point,
    since a per-row revert narrows it in place."""

    rowReverted = pyqtSignal(tuple)  # the reverted row's own field path

    def __init__(self, job: PreparedJob, scope_label: str, palette: Palette,
                 font_load: FontLoadResult, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self.job = job
        self._font_load = font_load
        self._row_widgets: dict[tuple, list[QWidget]] = {}
        self._section_widgets: dict[str, QWidget] = {}
        self._row_scope: dict[tuple, str | None] = {}

        self._title_label = QLabel(self)
        self._title_label.setFont(font_for("title", font_load))
        self._title_label.setWordWrap(True)
        self.content_layout.addWidget(self._title_label)

        self._subtitle_label = QLabel(
            f"{scope_label}. Compared with what the controller holds now.", self)
        self._subtitle_label.setFont(font_for("body", font_load))
        self._subtitle_label.setProperty("role", "secondary")
        self._subtitle_label.setWordWrap(True)
        self.content_layout.addWidget(self._subtitle_label)

        rows_widget = QWidget(self)
        self._grid = grid = QGridLayout(rows_widget)
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
        for header_col, text in enumerate(("Field", "Was", "Will be", "")):
            header = QLabel(text, rows_widget)
            header.setFont(font_for("label", font_load))
            header.setProperty("role", "secondary")
            grid.addWidget(header, 0, header_col)

        self._grid_row = 1
        # Group by scope only when more than one is actually present --
        # a flat list (today's overwhelmingly common case, see the class
        # docstring) gets no section headers at all, unchanged from
        # before S7.
        scopes_present: list[str | None] = []
        for outcome in job.writable:
            s = scope_for_path(outcome.intent.path)
            if s not in scopes_present:
                scopes_present.append(s)
        if len(scopes_present) > 1:
            for scope in scopes_present:
                self._add_section_header(rows_widget, scope)
                for outcome in job.writable:
                    if scope_for_path(outcome.intent.path) == scope:
                        self._add_row(rows_widget, outcome, scope=scope)
        else:
            for outcome in job.writable:
                self._add_row(rows_widget, outcome, scope=scopes_present[0] if scopes_present else None)

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

        self._conflict_notice = QLabel(
            "Some values have changed on the controller since this was drafted -- "
            "review the rows marked above. Writing will overwrite them with what's shown here.",
            self)
        self._conflict_notice.setFont(font_for("small", font_load))
        self._conflict_notice.setProperty("role", "caution")
        self._conflict_notice.setWordWrap(True)
        self.content_layout.addWidget(self._conflict_notice)

        self._empty_notice = QLabel("Nothing left to write.", self)
        self._empty_notice.setFont(font_for("small", font_load))
        self._empty_notice.setProperty("role", "secondary")
        self.content_layout.addWidget(self._empty_notice)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setProperty("role", "separator")
        self.content_layout.addWidget(separator)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.keep_editing_btn = QPushButton("Keep editing", self)
        self.keep_editing_btn.clicked.connect(self.reject)
        button_row.addWidget(self.keep_editing_btn)
        self.write_btn = QPushButton(self)
        self.write_btn.setProperty("role", "write")
        self.write_btn.clicked.connect(self.accept)
        button_row.addWidget(self.write_btn)
        self.content_layout.addLayout(button_row)

        self.setMinimumWidth(520)
        self._refresh_header()

    def _add_section_header(self, rows_widget: QWidget, scope: str | None) -> None:
        label = QLabel(SCOPE_LABELS.get(scope, scope or "Other"), rows_widget)
        label.setFont(font_for("label", self._font_load))
        label.setProperty("role", "secondary")
        self._grid.addWidget(label, self._grid_row, 0, 1, 4)
        self._section_widgets[scope] = label
        self._grid_row += 1

    def _add_row(self, rows_widget: QWidget, outcome, *, scope: str | None = None) -> None:
        font_load = self._font_load
        grid = self._grid
        row = self._grid_row
        widgets: list[QWidget] = []

        field_label = QLabel(format_field_label(outcome.intent.path), rows_widget)
        field_label.setFont(font_for("body", font_load))
        field_label.setWordWrap(True)
        grid.addWidget(field_label, row, 0)
        widgets.append(field_label)

        keycode_row = _is_keycode_row(outcome)
        was_label = QLabel(format_field_value(outcome.baseline_value, keycode=keycode_row), rows_widget)
        was_label.setFont(font_for("body", font_load))
        was_label.setProperty("role", "secondary")
        grid.addWidget(was_label, row, 1)
        widgets.append(was_label)

        will_be_label = QLabel(format_field_value(outcome.intent.desired, keycode=keycode_row), rows_widget)
        will_be_label.setFont(font_for("body", font_load))
        grid.addWidget(will_be_label, row, 2)
        widgets.append(will_be_label)

        path = outcome.intent.path
        revert_btn = QPushButton("Revert", rows_widget)
        revert_btn.setProperty("role", "link")
        revert_btn.clicked.connect(lambda _c=False, p=path: self._on_row_revert_clicked(p))
        grid.addWidget(revert_btn, row, 3)
        widgets.append(revert_btn)
        row += 1

        if outcome.classification is Classification.CONFLICT:
            conflict_label = QLabel(
                f"Changed on the controller -- now "
                f"{format_field_value(outcome.fresh_value, keycode=keycode_row)}.",
                rows_widget)
            conflict_label.setFont(font_for("small", font_load))
            conflict_label.setProperty("role", "caution")
            conflict_label.setWordWrap(True)
            grid.addWidget(conflict_label, row, 0, 1, 4)
            widgets.append(conflict_label)
            row += 1

        self._row_widgets[path] = widgets
        self._row_scope[path] = scope
        self._grid_row = row

    def _on_row_revert_clicked(self, path: tuple) -> None:
        """Narrows self.job in place (see the class docstring) and hides
        the row -- the caller (connected to rowReverted) is responsible
        for making the revert real on whichever page actually owns this
        field; this class only ever reflects what's left to write."""
        for widget in self._row_widgets.pop(path, ()):
            widget.setVisible(False)
        scope = self._row_scope.pop(path, None)
        if scope in self._section_widgets and scope not in self._row_scope.values():
            self._section_widgets.pop(scope).setVisible(False)
        self.job = dataclasses.replace(
            self.job, outcomes=tuple(o for o in self.job.outcomes if o.intent.path != path))
        self._refresh_header()
        self.rowReverted.emit(path)

    def _refresh_header(self) -> None:
        rows = self.job.writable
        n = len(rows)
        self.setWindowTitle(
            "Nothing left to write." if n == 0
            else f"Write {n} change{'s' if n != 1 else ''} to the controller?")
        self._title_label.setText(self.windowTitle())
        self.write_btn.setText(f"Write {n} change{'s' if n != 1 else ''}")
        self.write_btn.setEnabled(n > 0)
        has_conflicts = any(o.classification is Classification.CONFLICT for o in rows)
        self._conflict_notice.setVisible(has_conflicts)
        self._empty_notice.setVisible(n == 0)
