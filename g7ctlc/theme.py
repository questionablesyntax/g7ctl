"""App-wide QSS stylesheet. Dark theme, single accent color for primary
actions/active states -- kept as one string so there's exactly one place
to tune colors, not scattered across every view.
"""

# Palette
BG = "#1e1f24"           # window background
SURFACE = "#26282e"      # cards/groupboxes/inputs
SURFACE_ALT = "#2f313a"  # hover/alternating rows
BORDER = "#3a3d47"
TEXT = "#e6e6e9"
TEXT_MUTED = "#9a9ca6"
ACCENT = "#ff8a3d"        # GameSir-ish orange, used sparingly for emphasis
ACCENT_HOVER = "#ff9d5c"
ACCENT_PRESSED = "#e67736"
DANGER = "#e0524f"
SUCCESS = "#3ecf6e"

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG};
}}

QLabel {{
    background: transparent;
}}

QLabel[role="muted"] {{
    color: {TEXT_MUTED};
}}

/* --- Tabs --- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    top: -1px;
    background: {SURFACE};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 8px 18px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

/* --- GroupBox --- */
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_MUTED};
}}

/* --- Buttons --- */
QPushButton {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT};
}}
QPushButton:hover {{
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background: {BORDER};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
    background: {SURFACE};
}}

QPushButton[role="primary"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #1a1a1a;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[role="primary"]:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton[role="primary"]:disabled {{
    background: {SURFACE_ALT};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}

QPushButton[role="danger"] {{
    color: {DANGER};
    border-color: {DANGER};
    background: transparent;
}}
QPushButton[role="danger"]:hover {{
    background: rgba(224, 82, 79, 0.15);
}}

/* --- Inputs --- */
QComboBox, QSpinBox, QLineEdit {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{
    border-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {ACCENT};
}}
/* Styling an input's background/color above overrides Qt's own palette-based
   greying, so without these a disabled combo/spinbox is pixel-identical to an
   editable one. That is not cosmetic: the Buttons tab disables the whole
   Shift column on profiles with no Shift layer, and the profile picker
   disables itself mid-sync -- both looked fully interactive. The :hover
   override matters just as much, since the rule above would otherwise light
   up the accent border on a control that cannot be used. */
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{
    color: {TEXT_MUTED};
    background: {SURFACE};
    border-color: {BORDER};
}}
QComboBox:disabled:hover, QSpinBox:disabled:hover, QLineEdit:disabled:hover {{
    border-color: {BORDER};
}}
QCheckBox:disabled, QLabel:disabled {{
    color: {TEXT_MUTED};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #1a1a1a;
    outline: none;
}}

/* --- Checkboxes --- */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* --- Slider --- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: {TEXT};
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT};
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* --- Group separators (Buttons tab) --- */
QFrame[role="separator"] {{
    background: {BORDER};
    max-height: 1px;
    border: none;
    margin: 6px 8px;
}}
"""
