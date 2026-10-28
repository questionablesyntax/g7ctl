# Controller drawing -- provenance

`front.svg`: original line art authored for this project, 2026-10-22.
Geometry traced (potrace) from GameSir's own printed manual diagram and
cross-checked against the Nexus app's button-map screenshot and the
maintainer's own photos of their physical G7 Pro -- never from Nexus cover art
or any other proprietary illustration shipped as an asset. See
`DESIGN-SPEC.md` section 8's 2026-10-22 amendment in the redesign notes
for the full reasoning on why tracing real controller geometry from any
of those references is ordinary illustration practice, not a derivative
of someone else's protected expression.

L4/R4 paddle icon composed in separately, traced from the Nexus app's own
product-photo render (not its line-art diagram) for the same reason.
View and Share button glyphs traced/built from the maintainer's own close-up
photos of the physical controller.

22 named, invisible hit-region elements (`<circle>`/`<rect>` with
`fill="none"`, no stroke) layered over the line art, one per
`pyg7.buttons.KNOWN_BUTTON_IDS` entry plus the non-bindable D-pad
sub-directions -- `guide` and the M/mode button are deliberately excluded,
neither is remappable. `ControllerDiagram` (`g7ctlc/controller_diagram.py`)
looks these up by id via `QSvgRenderer.boundsOnElement()`.

2026-10-28 cleanup: three circular outlines (the left stick's outer ring,
the D-pad ring and the Y button ring) were redrawn as true circles at the
traced centres, and the M/mode button's corrupted interior was replaced
with a plain pill outline and an M glyph, both hand-authored; the
superseded traced paths were removed. All other geometry is still the
original trace.
