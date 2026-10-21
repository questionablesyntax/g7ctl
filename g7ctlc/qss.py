"""QSS generator, A1 of the redesign. Produces the application stylesheet
from a `Palette` (`g7ctlc/palette.py`) instead of the single hardcoded
theme `g7ctlc/theme.py` carries today -- `g7ctlc/theme.py` is untouched by
this phase; A3 is where the shell is rewired onto this generator.

No Qt import here -- plain string generation, so the colour-rule test
(`tests/test_theme_qss.py`) can check the signal hue's closed list
(CRITIC.md #1: the held state, live input marks, the one write button)
directly against generated text, without needing PyQt6 at all.

Button roles this generator knows: unmarked (neutral: `surface.raised`
fill, `border.control` edge -- CRITIC.md #6, selected/neutral no longer
look the same), `role="write"` (the *only* button-role allowed the signal
fill), `role="danger"` (`alarm.fill`, destructive actions).
"""

from __future__ import annotations

from g7ctlc.palette import Palette
from g7ctlc.tokens import (
    ATKINSON,
    RADIUS_CONTROL,
    RADIUS_PANEL,
    RADIUS_SMALL,
)


def generate_stylesheet(palette: Palette) -> str:
    p = palette
    return f"""
QWidget {{
    background-color: {p.surface_ground};
    color: {p.text_primary};
    font-family: "{ATKINSON}";
}}

QMainWindow {{
    background-color: {p.surface_ground};
}}

QLabel {{
    background: transparent;
}}
QLabel[role="secondary"] {{
    color: {p.text_secondary};
}}
QLabel[role="signal"] {{
    color: {p.text_signal};
}}
QLabel[role="alarm"] {{
    color: {p.text_alarm};
}}
QLabel[role="caution"] {{
    color: {p.text_caution};
}}
QLabel:disabled {{
    color: {p.text_disabled};
}}

/* --- Panels (groups, the per-page content pane) --- */
QGroupBox {{
    background: {p.surface_panel};
    border: 1px solid {p.border_subtle};
    border-radius: {RADIUS_PANEL}px;
    margin-top: 14px;
    padding-top: 14px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.text_secondary};
}}

/* --- Buttons --- */
/* Neutral is the unmarked default (CRITIC.md #6: selected and neutral
   must not look the same -- the 2px border.selected outline is reserved
   for selection, drawn by the selecting widget, not here). */
QPushButton {{
    background: {p.surface_raised};
    border: 1px solid {p.border_control};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 14px;
    color: {p.text_primary};
}}
QPushButton:hover {{
    border-color: {p.focus_ring};
}}
QPushButton:pressed {{
    background: {p.surface_overlay};
}}
QPushButton:disabled {{
    color: {p.text_disabled};
    border-color: {p.border_subtle};
    background: {p.surface_panel};
}}

/* The one button role allowed the signal fill (CRITIC.md #1's closed
   list): the review sheet's "Write N changes" and the fast path's
   "Write 1 change" (DESIGN-SPEC.md 10.3). Nothing else in this
   stylesheet is signal_fill/-hover/-pressed. */
QPushButton[role="write"] {{
    background: {p.signal_fill};
    border: 1px solid {p.signal_fill};
    color: {p.text_on_signal};
    font-weight: 600;
}}
QPushButton[role="write"]:hover {{
    background: {p.signal_fill_hover};
    border-color: {p.signal_fill_hover};
}}
QPushButton[role="write"]:pressed {{
    background: {p.signal_fill_pressed};
    border-color: {p.signal_fill_pressed};
}}
QPushButton[role="write"]:disabled {{
    background: {p.surface_raised};
    border-color: {p.border_subtle};
    color: {p.text_disabled};
}}

QPushButton[role="danger"] {{
    color: {p.text_alarm};
    border-color: {p.alarm_fill};
    background: transparent;
}}
QPushButton[role="danger"]:hover {{
    background: {p.surface_alarm_tint};
}}

/* SegmentedControl (A2): styled checkable buttons in an exclusive group,
   not custom-painted (DESIGN-SPEC.md 10.2 item 7). Selected gets the raised
   fill plus the border.selected ring reserved for selection (CRITIC.md #6);
   unselected segments stay the plain neutral button above. `filled="true"`
   is the stepped-meter variant's cumulative-bar fill, distinct from the
   single selected segment of the text variant. */
QPushButton[role="segment"]:checked {{
    background: {p.surface_raised};
    border: 2px solid {p.border_selected};
    font-weight: 600;
}}
QPushButton[role="segment"][filled="true"] {{
    background: {p.surface_raised};
    border-color: {p.border_control};
}}

QPushButton[role="link"] {{
    border: none;
    background: transparent;
    color: {p.text_secondary};
    text-decoration: underline;
    padding: 2px 4px;
}}
QPushButton[role="link"]:hover {{
    color: {p.text_primary};
}}

/* --- Inputs --- */
QComboBox, QSpinBox, QLineEdit {{
    background: {p.surface_raised};
    border: 1px solid {p.border_control};
    border-radius: {RADIUS_CONTROL - 2}px;
    padding: 4px 8px;
    min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover,
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {p.focus_ring};
}}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{
    color: {p.text_disabled};
    background: {p.surface_panel};
    border-color: {p.border_subtle};
}}
QSpinBox[error="true"], QLineEdit[error="true"] {{
    border-color: {p.alarm_fill};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface_overlay};
    border: 1px solid {p.border_control};
    selection-background-color: {p.surface_raised};
    selection-color: {p.text_primary};
    outline: none;
}}

/* --- Checkboxes (draft semantics: nothing applies until written, so
   these are checkboxes, never toggle switches -- DIRECTION-A.md
   section 2's revision table) --- */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.border_control};
    border-radius: {RADIUS_SMALL}px;
    background: {p.surface_raised};
}}
QCheckBox::indicator:checked {{
    background: {p.border_selected};
    border-color: {p.border_selected};
}}
QCheckBox:disabled {{
    color: {p.text_disabled};
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border_subtle};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.text_secondary};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* InlineNotice (A2): a full hairline border on all sides, never a side
   stripe (DIRECTION-A.md section 5). */
QWidget[role="notice-info"] {{
    background: {p.surface_panel};
    border: 1px solid {p.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
}}
QWidget[role="notice-caution"] {{
    background: {p.surface_panel};
    border: 1px solid {p.text_caution};
    border-radius: {RADIUS_CONTROL}px;
}}
QWidget[role="notice-alarm"] {{
    background: {p.surface_alarm_tint};
    border: 1px solid {p.alarm_fill};
    border-radius: {RADIUS_CONTROL}px;
}}

/* --- Dividers --- */
QFrame[role="separator"] {{
    background: {p.border_subtle};
    max-height: 1px;
    border: none;
    margin: 6px 8px;
}}
"""
