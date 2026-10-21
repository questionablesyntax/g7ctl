"""Font loading, A1 of the redesign. Loads the vendored families under
`g7ctlc/assets/fonts/` (`OFL.txt` alongside each, `SOURCES.md` for exact
provenance) via `QFontDatabase.addApplicationFont`, and builds a `QFont`
per `tokens.TypeRole` in points (`DESIGN-SPEC.md` 10.2 item 6), not pixels.

Needs PyQt6 -- unlike `palette.py`/`tokens.py`/`qss.py`, this module is
not meant to be importable without it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

from g7ctlc.tokens import TYPE_ROLES, TypeRole

_ASSETS_FONTS_DIR = Path(__file__).parent / "assets" / "fonts"

# Family name -> vendored file(s). Variable fonts (one file, every weight)
# list themselves once; static families list each vendored weight file,
# since `addApplicationFont` registers exactly the weights handed to it.
_VENDORED_FILES: dict[str, tuple[str, ...]] = {
    "Atkinson Hyperlegible Next": (
        "AtkinsonHyperlegibleNext-Regular.ttf",
        "AtkinsonHyperlegibleNext-SemiBold.ttf",
    ),
    "Atkinson Hyperlegible Mono": (
        "AtkinsonHyperlegibleMono-Variable.ttf",
    ),
    "Barlow Semi Condensed": (
        "BarlowSemiCondensed-Medium.ttf",
        "BarlowSemiCondensed-SemiBold.ttf",
    ),
}

# `DIRECTION-A.md` section 2, "Type": "If loading fails, the fallback is
# Noto Sans, then DejaVu Sans."
FALLBACK_CHAIN: tuple[str, ...] = ("Noto Sans", "DejaVu Sans")

_TNUM_TAG = b"tnum"


@dataclasses.dataclass(frozen=True)
class FontLoadResult:
    loaded_families: tuple[str, ...]
    failed_families: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failed_families


def load_fonts() -> FontLoadResult:
    """Register every vendored file with `QFontDatabase`. Safe to call
    more than once -- `addApplicationFont` on an already-registered file
    is a harmless no-op repeat registration, not an error.
    """
    loaded: list[str] = []
    failed: list[str] = []
    for family, filenames in _VENDORED_FILES.items():
        family_ok = False
        for filename in filenames:
            path = _ASSETS_FONTS_DIR / filename
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id != -1 and QFontDatabase.applicationFontFamilies(font_id):
                family_ok = True
        (loaded if family_ok else failed).append(family)
    return FontLoadResult(tuple(loaded), tuple(failed))


def _resolve_family(face: str, load_result: FontLoadResult) -> str:
    if face in load_result.loaded_families:
        return face
    for fallback in FALLBACK_CHAIN:
        return fallback
    return face  # pragma: no cover - FALLBACK_CHAIN is never empty


def font_for(role: str, load_result: FontLoadResult, *, scale: float = 1.0) -> QFont:
    """Build the `QFont` for a `tokens.TypeRole`, in points so the user's
    own font-size preference is honoured (`DESIGN-SPEC.md` 10.2 item 6).
    `scale` is an additional multiplier for the app's own text-size
    preference (independent of the OS one `setPointSizeF` already tracks).
    """
    spec: TypeRole = TYPE_ROLES[role]
    family = _resolve_family(spec.face, load_result)
    font = QFont(family)
    font.setWeight(QFont.Weight(spec.weight))
    font.setPointSizeF(spec.point_size * scale)
    if spec.letter_spacing_em:
        # QFont letter spacing is in percent-of-font-advance units for
        # QFont.SpacingType.PercentageSpacing; 1.0 em of tracking == 100.
        font.setLetterSpacing(
            QFont.SpacingType.PercentageSpacing, 100 + spec.letter_spacing_em * 100
        )
    if spec.tabular_figures:
        _try_enable_tabular_figures(font)
    return font


def _try_enable_tabular_figures(font: QFont) -> None:
    """Confirmed present on this project's floor (A0: `QFont.setFeature`
    needs Qt 6.7, `pyproject.toml` now requires it, and Atkinson
    Hyperlegible Next ships `tnum` -- `g7ctlc/assets/fonts/SOURCES.md`).
    Still guarded, not called unconditionally: a user's system Qt plugin
    can be older than what this project was built against, and a readout
    with proportional-but-not-tabular digits is a cosmetic wobble, not a
    reason to crash the app.
    """
    set_feature = getattr(font, "setFeature", None)
    tag_type = getattr(QFont, "Tag", None)
    if set_feature is None or tag_type is None:
        return
    try:
        set_feature(tag_type(_TNUM_TAG), 1)
    except (TypeError, ValueError):
        pass
