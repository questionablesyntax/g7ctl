"""Spacing, radius, type and motion tokens. A1 of the redesign
(`IMPLEMENTATION-PLAN.md` track A). Values from `DIRECTION-A.md` section 2,
adopted in full by `DESIGN-SPEC.md` section 5 ("Modifications: drop the
button-press scale. Everything else as A.").

No Qt import here on purpose -- this is plain data, usable by the QSS
generator (`g7ctlc/qss.py`), the font loader (`g7ctlc/fonts.py`) and tests
alike without pulling in PyQt6.
"""

from __future__ import annotations

from typing import NamedTuple

# Spacing scale, 4px base (`DIRECTION-A.md` section 2, "Spacing, radius,
# elevation, icons"). The gap within a group is SPACING[1] (8); between
# groups, SPACING[4] (24) -- at least twice as large, by design.
SPACING: tuple[int, ...] = (4, 8, 12, 16, 24, 32, 48)

GROUP_INNER_GAP = SPACING[1]   # 8
GROUP_OUTER_GAP = SPACING[4]   # 24

# Radius scale. Outer radius = inner + padding where surfaces nest.
RADIUS_SMALL = 4    # checkbox, chips
RADIUS_CONTROL = 8  # controls, rail items
RADIUS_PANEL = 12   # panel, sheet, picker


class TypeRole(NamedTuple):
    """One row of the type table. `point_size` is in points, not pixels --
    `DESIGN-SPEC.md` 10.2 item 6 overrides `DIRECTION-A.md`'s original
    `QFont.setPixelSize` px figures specifically so the user's own
    font-size preference is honoured; the numbers are unchanged, only the
    unit `g7ctlc/fonts.py` applies them with (`setPointSizeF`, not
    `setPixelSize`).
    """

    face: str
    weight: int
    point_size: float
    line_height: float
    tabular_figures: bool = False
    letter_spacing_em: float = 0.0


ATKINSON = "Atkinson Hyperlegible Next"
ATKINSON_MONO = "Atkinson Hyperlegible Mono"
BARLOW = "Barlow Semi Condensed"

# Role name -> TypeRole. Matches `DIRECTION-A.md`'s type table exactly;
# the "readout" role is the one the A0 `tnum` finding
# (`g7ctlc/assets/fonts/SOURCES.md`) applies to.
TYPE_ROLES: dict[str, TypeRole] = {
    "display": TypeRole(BARLOW, 600, 36, 1.1, letter_spacing_em=-0.01),
    "title": TypeRole(BARLOW, 600, 22, 1.2),
    "label": TypeRole(ATKINSON, 600, 14, 1.3),
    "body": TypeRole(ATKINSON, 400, 14, 1.45),
    "small": TypeRole(ATKINSON, 400, 13, 1.4),
    "readout": TypeRole(ATKINSON, 600, 14, 1.3, tabular_figures=True),
    "code": TypeRole(ATKINSON_MONO, 400, 13, 1.3),
}


class MotionToken(NamedTuple):
    duration_ms: int
    # Cubic-bezier control points (x1, y1, x2, y2), or None for an instant
    # (zero-duration) token where no curve applies.
    bezier: tuple[float, float, float, float] | None


# `DIRECTION-A.md` section 2, "Motion tokens". `ease.out`/`ease.inout` are
# curves, not durations -- kept here as the two `bezier` values reused
# across the duration tokens that need a curve, via MOTION_EASE_OUT /
# MOTION_EASE_INOUT below, rather than repeating the tuple per duration.
MOTION_EASE_OUT: tuple[float, float, float, float] = (0.2, 0.0, 0.0, 1.0)
MOTION_EASE_INOUT: tuple[float, float, float, float] = (0.4, 0.0, 0.2, 1.0)

MOTION_INSTANT = MotionToken(0, None)
MOTION_FAST = MotionToken(120, MOTION_EASE_OUT)
MOTION_BASE = MotionToken(180, MOTION_EASE_OUT)
MOTION_SLOW = MotionToken(300, MOTION_EASE_OUT)

# `QTimer`-coalesced repaint ceiling for live input -- never a tween.
LIVE_FRAME_MS = 16
