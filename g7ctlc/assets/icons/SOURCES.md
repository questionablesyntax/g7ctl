# Vendored icons -- provenance

`lucide-static` **1.61.0**, pinned (`registry.npmjs.org/lucide-static/-/lucide-static-1.61.0.tgz`).
`LICENSE` in this directory is that package's own license file, copied
unmodified.

**License note, correcting `DESIGN-SPEC.md` section 8's "MIT notice":**
Lucide's own icons are **ISC**, not MIT. A named sub-list of icons
*derived from the Feather project* carries an additional MIT notice
within the same `LICENSE` file. Of the 22 icons vendored here, six are on
that Feather-derived list and so carry both notices: `check`,
`chevron-down`, `info`, `lock`, `search`, `x`. The rest are ISC only.
Either way the one `LICENSE` file in this directory covers all of it --
nothing further to vendor per-icon.

All 22 names below were checked directly against this exact pinned
version in A0 -- confirmed present as `<name>.svg` in the package's
`icons/` directory before being copied here. Matches `g7ctlc/icons.py`'s
`ICON_NAMES`.

```
activity, battery, battery-charging, battery-low, check, chevron-down,
circle-alert, circle-help, file-down, file-up, gamepad-2, info, layers,
loader-circle, lock, refresh-cw, rotate-ccw, search, triangle-alert,
unplug, usb, x
```

## A0 note for A1 (icon loader)

Vendored SVGs ship at Lucide's default `stroke-width="2"`. `DIRECTION-A.md`
calls for "one absolute stroke of 1.5px" -- A1's `IconLoader`
implementation (`g7ctlc/icons.py`) is where that override happens, once,
not per call site and not by re-vendoring edited copies.
