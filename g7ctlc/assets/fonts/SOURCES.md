# Vendored fonts -- provenance

All OFL 1.1 (`OFL-*.txt` alongside each family here, exact files from each
source, unmodified).

| Family | Weights vendored | Source | Pinned at |
|---|---|---|---|
| Atkinson Hyperlegible Next | Regular (400), SemiBold (600) | `github.com/googlefonts/atkinson-hyperlegible-next`, `fonts/ttf/` | commit `7925f50f649b3813257faf2f4c0b381011f434f1` |
| Atkinson Hyperlegible Mono | Variable (all weights in one file) | `github.com/google/fonts`, `ofl/atkinsonhyperlegiblemono/` | commit `45e3d5269e4a17d823f6d84470bc084dc5ae46f6` |
| Barlow Semi Condensed | Medium (500), SemiBold (600) | `github.com/google/fonts`, `ofl/barlowsemicondensed/` | commit `45e3d5269e4a17d823f6d84470bc084dc5ae46f6` |

Weights match what the plan actually uses (text at 400/600, display at
500/600); re-vendor the specific weight file from the same source/commit
if a page needs another one, rather than widening to the full family.

## A0 check: tabular figures (D5 / `DESIGN-SPEC.md` section 9)

Checked with `fontTools` against the GSUB feature list of each vendored
file:

- **Atkinson Hyperlegible Next: has `tnum`.** Confirmed present on the
  Regular weight. `QFont.setFeature(QFont.Tag(b"tnum"), 1)` can target
  this family directly for numeric readouts -- the spec's fallback-to-Mono
  plan for numerics is not needed.
- **Atkinson Hyperlegible Mono: no `tnum` feature, and none needed.** It's
  monospace -- every glyph already has the same advance width, which is
  what `tnum` exists to force on a proportional font.
