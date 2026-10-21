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
    ATKINSON_MONO,
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
QLabel[role="secondary"], QLabel[role="muted"] {{
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

/* --- Tabs (the per-side sub-tabs inside Sticks/Triggers/Motion/
   Vibration -- MainWindow's own top-level tabs are the Rail/pages this
   redesign replaces in A3, not these) --- */
QTabWidget::pane {{
    border: 1px solid {p.border_subtle};
    border-radius: {RADIUS_PANEL}px;
    top: -1px;
    background: {p.surface_panel};
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_secondary};
    padding: 8px 18px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {p.text_primary};
    /* border.selected, not signal_fill: which sub-tab is open is a plain
       selection state, not one of CRITIC.md #1's three signal-colour
       roles. */
    border-bottom: 2px solid {p.border_selected};
}}
QTabBar::tab:hover:!selected {{
    color: {p.text_primary};
}}
QTabWidget:disabled QTabBar::tab {{
    color: {p.text_disabled};
}}
QTabWidget:disabled QTabBar::tab:selected {{
    border-bottom: 2px solid {p.border_subtle};
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

/* BindingField (A4): the keycode-picker trigger. Styled like an input
   field (left-aligned text, the same border/radius as QComboBox/
   QSpinBox/QLineEdit), not like a button -- clicking it opens a picker,
   it doesn't perform an action by itself. `unrecognised="true"` is an
   unnamed raw code kept as read (DIRECTION-A.md section 5's BindingRow:
   "unrecognised code (mono)"). */
QPushButton[role="binding-field"] {{
    background: {p.surface_raised};
    border: 1px solid {p.border_control};
    border-radius: {RADIUS_CONTROL - 2}px;
    padding: 4px 8px;
    text-align: left;
}}
QPushButton[role="binding-field"]:hover,
QPushButton[role="binding-field"]:focus {{
    border-color: {p.focus_ring};
}}
QPushButton[role="binding-field"][unrecognised="true"] {{
    font-family: "{ATKINSON_MONO}";
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
QComboBox:disabled:hover, QSpinBox:disabled:hover, QLineEdit:disabled:hover {{
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

/* --- Slider (VibrationView's level sliders) --- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {p.border_subtle};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    /* border.selected, not signal_fill: a slider's own filled portion is
       a plain value readout, not one of CRITIC.md #1's three roles. */
    background: {p.border_selected};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: {p.text_primary};
}}
QSlider::handle:horizontal:hover {{
    border: 1px solid {p.focus_ring};
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

/* OwnershipBar (A3, "the clamp bar"): full-width status region directly
   under the titlebar. Held is the one surface allowed the signal tint
   outside a live mark or the write button (CRITIC.md #1's closed list --
   the held state IS one of its three members). Every other variant stays
   neutral. */
QWidget[role="status"] {{
    border-radius: {RADIUS_PANEL}px;
}}
QWidget[role="status"][variant="held"] {{
    background: {p.surface_signal_tint};
    border: 1px solid {p.signal_fill};
}}
QWidget[role="status"][variant="connecting"],
QWidget[role="status"][variant="no_controller"] {{
    background: {p.surface_panel};
    border: 1px solid {p.border_subtle};
}}
QWidget[role="status"][variant="released"] {{
    background: {p.surface_panel};
    border: 1px solid {p.border_control};
}}
QWidget[role="status"][variant="alarm"] {{
    background: {p.surface_alarm_tint};
    border: 1px solid {p.alarm_fill};
}}
/* The word itself always sits directly on the bar's own tint at a
   readable, constant colour (CRITIC.md #2: "a bold 'Holding' word on the
   tint" -- one treatment, not a second filled shape recoloured per
   variant). The dot below is where variant colour actually lives. */
QLabel[role="capsule"] {{
    color: {p.text_primary};
    font-weight: 600;
    padding: 2px 0;
}}
/* The ownership dot: filled for the two states CRITIC.md #1's closed
   list actually allows signal/alarm colour in here (held, alarm), a
   hollow ring otherwise -- shape carries the state, not colour alone. */
QLabel[role="ownership-dot"] {{
    border-radius: 5px;
    background: transparent;
    border: 2px solid {p.border_control};
}}
QLabel[role="ownership-dot"][variant="held"] {{
    background: {p.signal_mark};
    border-color: {p.signal_mark};
}}
QLabel[role="ownership-dot"][variant="alarm"] {{
    background: {p.alarm_fill};
    border-color: {p.alarm_fill};
}}

/* Rail (A3): the left navigation column -- profile switch, per-scope nav
   groups, footer actions. */
QWidget[role="rail"] {{
    background: {p.surface_panel};
    border-right: 1px solid {p.border_subtle};
}}
QLabel[role="rail-heading"] {{
    color: {p.text_secondary};
    font-weight: 600;
    padding-top: 6px;
}}
QPushButton[role="rail-item"] {{
    text-align: left;
    border: none;
    background: transparent;
    padding: 6px 10px;
}}
QPushButton[role="rail-item"]:checked {{
    background: {p.surface_raised};
    border-left: 2px solid {p.border_selected};
    font-weight: 600;
}}
QPushButton[role="rail-item"]:hover {{
    background: {p.surface_raised};
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
