# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **The Buttons tab showed both the Default and Shift columns on every fresh
  launch.** Switching to any other profile corrected it and it stayed
  corrected for the rest of the session, so it looked like a redraw glitch
  rather than a missing call. The Shift layer is shared by all four
  profiles, so a Shift column sitting inside the per-profile screen implies
  a scope it does not have — which is exactly what moving Shift into the
  profile selector was meant to stop showing.

### Changed

- **The "Swap Left Stick and D-pad" tooltip no longer understates what is
  known about it.** It described the setting as not yet confirmed against
  hardware while pointing at the source file that records it as
  hardware-verified since 2026-07-29.

### Documentation

- **The config protocol is a paged register file, and PROTOCOL.md now says
  so.** Every config write is `03 [PROFILE] [PAGE] [OFFSET] [LEN]` followed
  by `LEN` bytes, writing at `(PAGE << 8) + OFFSET` — verified against every
  config write in the capture corpus. Several things previously documented
  as separate mechanisms are the same one: the prefix's third byte is a
  256-byte page selector (which is why Sticks and the dock share a `0x100`
  base), the byte after `SETTING_ID` is a length rather than a format
  marker, and `SETTING_ID` is itself a byte address. Buttons' "allocate
  form" and "compact form" are one format at two addresses — the allocate
  write includes the record's `01` marker byte and the compact one does not,
  which is the whole reason a compact write to an unconfigured button
  vanishes.
- **Custom stick and trigger curves are decoded**: a ten-byte block holding
  four `(x, y)` control points, at four known addresses, with per-point
  addresses listed. Not implemented — and the interpolation drawn between
  the points is explicitly *not* established, so anything rendering these
  curves would be guessing.
- **Corrected a claim about the shared Shift layer that was wrong in two
  different ways.** 0.1.5 retracted "the Shift layer has its own curves" in
  PROTOCOL.md but left the retracted claim standing in `pyg7/state.py`,
  complete with a measurement date and a cross-reference to a section that
  no longer existed. The sentence that replaced it then overstated the other
  way, calling the Shift blob's non-button bytes identical to an untouched
  profile's; measured, they differ in five bytes, all of them left-stick
  curve control points. The conclusion both versions supported is unchanged
  and the code was always correct: nothing can write those bytes, so reading
  only the Default layer is right.
- Recorded two unmapped areas rather than leaving them undocumented: five
  undecoded bytes in every button-table record (not always zero), and two
  stick-shaped configuration blocks nothing has ever been seen writing.

- **Switching profiles on the controller re-enumerates it, twice.** Pressing
  `M`+`Y`/`B`/`A`/`X` drops the controller off the USB bus, brings it back as
  a different USB device for roughly 45 seconds, then drops it again on the
  way back. This is GameSir firmware — it happens with nothing running — but
  it has two consequences worth knowing, now documented in the README and
  PROTOCOL.md. Steam and anything else tracking gamepads sees a different
  device and loses a custom controller name. And keyboard/mouse remaps stop
  working for that window, because the HID interfaces that emit them do not
  exist in the other identity — while the gamepad itself keeps working, so it
  presents as "my remaps broke" rather than "my controller disconnected".

## [0.1.5] - 2026-08-07

**The Shift layer is one layer, shared by all four profiles.** 0.1.4 stopped
it corrupting Profile 1, but explained it wrongly and locked it to Profile 1
as a result. It is now a fifth entry in the profile selector — a peer of the
four profiles, which is how the controller actually stores it — and editable
again from anywhere.

### Changed

- **The Shift layer is now its own entry in the profile selector**, sitting
  after Profile 4 as "Shift Layer (shared)", and the per-profile Buttons tab
  no longer has a Shift column. The controller has exactly **one** Shift
  layer, shared by all four profiles — so a global column inside a
  per-profile screen was the wrong shape, and 0.1.4 made it worse by
  disabling that column everywhere except Profile 1. Selecting the Shift
  entry shows Buttons only: the other tabs and Report Rate are profile-scoped
  and cannot be written to the Shift layer at all.
- **Shift bindings can be edited from any profile again.** 0.1.4 refused them
  outside Profile 1, which was safe but wrong — the write was never
  profile-specific in the first place.

### Fixed

- **A state file exported before 0.1.4 has its Shift section dropped on
  load**, with a warning. Those files recorded Profile 1's *Default* layer as
  the profile's Shift layer (the pre-0.1.4 read fell back to it). Harmless
  while Shift writes were refused; now that they work, importing one would
  push Profile 1's default bindings over the Shift layer every profile shares.

### Documentation

- 0.1.4's release note below says the controller "stores Shift-layer bindings
  for Profile 1 only". That is **not correct** — it stores one Shift layer for
  the whole device. The corruption 0.1.4 fixed was real and the fix was right;
  only the explanation was wrong. PROTOCOL.md now carries the evidence,
  including GameSir Nexus's own read pattern.
- PROTOCOL.md also retracts the claim that the Shift layer has its own stick
  curves, deadzones and vibration levels. It compared the Shift blob against
  the one *configured* profile and read configured-versus-factory as
  layer-scoping. The Shift layer is button bindings only.

## [0.1.4] - 2026-08-07

**Update if you use more than one profile.** On 0.1.3 and earlier, editing
the Shift layer on Profiles 2-4 wrote into Profile 1's Default layer. If you
have done that, check Profile 1's bindings against what you expect before
syncing anything else — this release stops the damage but cannot undo it.

### Added

- **`g7ctl --version`.** There was no way to ask the CLI what it was; the
  GUI has shown its version in About since 0.1.0. It reports the running
  package's own `__version__` and the directory it was imported from,
  because the number alone cannot answer the question people actually need
  answered: `g7ctl-git` builds the same `pyproject.toml` version as `g7ctl`
  (only its pacman version carries the revision), so the path is what
  separates a release from a VCS build, and a checkout from site-packages.
  Installed distribution metadata is appended only when it disagrees with
  the running module — which means a checkout shadowing an installed
  package, or genuine version drift.
- **A test pinning the five version strings a release bumps by hand**
  (`pyproject.toml`, the three packages' `__init__.py`, and the release
  PKGBUILD's `pkgver`). Nothing checked they agreed, and a miss is silent in
  the worst place: `--version` reporting one number while the wheel metadata
  and pacman report another.

### Fixed

- **Editing the Shift layer on Profiles 2-4 overwrote Profile 1.** The
  controller stores Shift-layer bindings for Profile 1 only. Asking for one
  on another profile produced category `0x06`/`0x07`/`0x08`, which the
  firmware does not implement and does not reject: it falls back to Profile
  1's Default-layer blob. So the Buttons tab's Shift column, on Profiles
  2-4, wrote each binding into Profile 1's Default layer -- and then read
  Profile 1's bindings back and displayed them as that profile's Shift
  layer, which is why the damage was invisible from inside the app. If you
  have edited Shift bindings on Profiles 2-4, check Profile 1's Default
  layer against what you expect. The Shift column is now disabled on those
  profiles, reads return no Shift layer for them, and the protocol layer
  refuses to put an unimplemented category on the wire at all. This is a
  limit of what g7ctl can currently address, not a proven limit of the
  hardware: no category byte reaches a Shift layer for Profiles 2-4, but
  users report per-profile Shift bindings working in GameSir Nexus, so
  there is likely a mechanism still to be found. Tracked in PROTOCOL.md.
- **`--version` and `-h` could kill a running batch session.**
  `_NonExitingArgumentParser` exists so one bad line in a hundred-line
  script doesn't end the process, but it overrode only `error()` — and
  argparse's version and help actions print and then call `exit()` directly,
  never touching `error()`. Both now raise the same per-line error as any
  other invalid line. Latent before this release, since neither option
  existed at the top level; adding `--version` would have made it reachable.

## [0.1.3] - 2026-08-01

A packaging release, cut so the corrected launcher entry actually reaches
installed systems: `packaging/PKGBUILD` builds from a release tarball, so
0.1.2's packages still ship the old one no matter what `main` says. No
change to the library, CLI, or GUI code — the protocol path is identical to
0.1.2.

### Changed

- **`packaging/g7ctlc.desktop` is now the single source of the launcher
  entry.** Both PKGBUILDs used to carry their own heredoc copy, so the same
  content lived in three places and had already drifted apart in structure.
  They now derive the installed entry from that one file, rewriting only the
  three lines that must differ (`Exec`/`Icon` to their installed forms,
  `Path=` dropped) and stripping comments. Editing the entry is now a
  one-file change.
- **The launcher entry gained `Keywords`, `GenericName` and a corrected
  `Categories`.** It was `Categories=Utility;` with no search terms, so it
  surfaced only for someone already typing its name. It now sits under
  `Settings;HardwareSettings;`, where a user looks for device configuration,
  and matches searches for gamesir, controller, gamepad, remap, deadzone and
  so on. Deliberately one main category: keeping `Utility` alongside
  `Settings` makes some menus list the app twice, which
  `desktop-file-validate` warns about. Both the checkout and packaged forms
  validate clean.

### Added

- **A VCS PKGBUILD at `packaging/git/`**, building the tip of `main` rather
  than a release tarball: `cd packaging/git && makepkg -si`. Protocol fixes
  here land well before a version is cut, and until now the only packaged
  path was a tagged release — you could not build what was on `main`, let
  alone check that a change still packaged before tagging it. Produces
  `python-pyg7-git`/`g7ctl-git`/`g7ctlc-git`, which provide and conflict
  with their stable counterparts, version each build as `<latest tag>.rN.g<hash>`
  so pacman orders them correctly, and run the 209-test suite during the
  build.

## [0.1.2] - 2026-08-01

The 2.4GHz dongle release. Everything this project had written down about
the dongle since 2026-07-26 was wrong in the same way: it had only ever been
observed while our own tool was holding it, so the state it idles in was
never once seen. Correcting that fixed a slow connect, a session running the
wrong timeouts, and a README that told wireless users the opposite of the
truth.

### Added

- **The GUI now says on screen that the controller isn't playable while the
  app holds it.** An amber note in the status bar, next to the connection
  state and directly beneath the "Release Device" button that clears it,
  shown only while a session is actually held; the tray tooltip's "Connected"
  label says the same, since a user who just found a dead pad is likely
  looking at the tray rather than a hidden window. This was previously a
  README-only caveat — and one the README got wrong for wireless users, who
  had no reason to connect a dead gamepad to this app at all.

### Changed

- **`pyg7.device.enter_vendor_mode()` now returns `(device, via_dongle)`**
  instead of just `device`, matching `find_writable_device()`. Callers need
  the flag to pick the session's timeouts and to decide whether the
  controller-liveness probe applies; returning only the device is what let
  both in-tree call sites hardcode `via_dongle=False`. Breaking for anyone
  scripting against the library directly — unpack the tuple.

### Fixed

- **The 2.4GHz dongle is not exempt from "Release Device".** The README,
  `PROTOCOL.md`, and the `PID_DONGLE` comment all said the dongle accepted
  configuration writes while continuing to work as a plain gamepad, so the
  README told wireless users they could leave the app connected and never
  think about it. They cannot: the controller is held in its vendor identity
  over the dongle exactly as it is over the cable, and is just as unplayable.
  Verified from daily use and with `g7ctlc` connected over the dongle —
  interface 0 bound to `usbfs`, nothing bound to `xpad`, no `/dev/input/js*`.
- **The wireless dongle does take the mode-switch handshake, and
  `enter_vendor_mode()` never waited for its landing PID.** An idle dongle
  enumerates as `100a` (an ordinary Xbox pad, `xpad` bound), takes the same
  `"gamesirapp"` handshake as the wired controller, and re-enumerates as
  `109c` about two seconds later on the same USB port. `enter_vendor_mode()`
  polled for `109b` alone, so every dongle connect from idle burned its full
  10-second timeout and logged `Timed out waiting for vendor-mode
  re-enumeration` before the caller's next `find_writable_device()` poll
  quietly succeeded. It now accepts either landing PID and reports which one
  it got.
- **A dongle reached via the handshake ran with wired timeouts.** Both call
  sites passed `via_dongle=False` after `enter_vendor_mode()`, so a session
  established that way used the tighter wired read timeout and settle count
  over the extra RF hop, and skipped `probe_controller_live()` entirely.
  Only sessions that found an already-switched dongle got the relaxed
  handling.
- The docs said the opposite of all of this: `PROTOCOL.md` had the dongle as
  a single-identity device that "can't re-enumerate over RF" and needed no
  handshake, dated 2026-07-26. That was inferred from only ever seeing the
  dongle mid-session — it stays in `109c` while anything heartbeats it, and
  a previous session had always left it there. The identity table, the
  mode-switch section, `PID_DONGLE`/`PID_XINPUT`'s comments, and the README
  are corrected.

## [0.1.1] - 2026-07-31

Documentation and packaging fixes. No functional change to the library, CLI,
or GUI; the protocol code is byte-for-byte identical to 0.1.0.

### Fixed

- **The Arch package could not be installed.** All three split packages
  shipped the wheel's single `.dist-info` directory, so `pacman` refused the
  transaction with "exists in both" on every file in it. One wheel is one
  Python distribution with one metadata directory, and it cannot be divided
  three ways; `python-pyg7` now owns it exclusively, and since both other
  packages depend on it the metadata is still always present exactly once.
- **The README credited `g7ctlc_launcher.py` with the `prctl` process
  rename** and steered readers away from `python3 -m g7ctlc`. The rename
  actually happens in `g7ctlc.app.main()`, so the launcher script,
  `python -m g7ctlc`, and the installed `g7ctlc` command all behave
  identically.
- Building a wheel emitted seven setuptools warnings: `project.license` as a
  TOML table (deprecated, removal scheduled 2027-Feb-18), a superseded
  license classifier, and `g7ctlc.assets` being an importable directory
  absent from the `packages` configuration. All cleared.

### Added

- **"Release Device" is now documented.** To read or write configuration the
  controller must sit in its vendor identity, and in that identity it is not
  an XInput pad and cannot emit remapped keys — so over USB it is not usable
  for playing while the GUI is connected. The button that reverts it was
  present in the UI but appeared nowhere in the README. (This entry
  originally claimed the 2.4GHz dongle was exempt; it isn't — corrected in
  0.1.2 above.)
- A repository-layout table in the README, explaining `g7ctl_tool.py` and
  `g7ctlc_launcher.py` — the two root-level scripts that let a fresh clone
  run with nothing installed.
- A GUI screenshot in the README.
- PEP 639 licensing metadata. Both license texts now ship in the wheel
  (`LICENSE` and `pyg7/LICENSE`); previously only the GPL one did, which
  understated the dual licensing.
- A real `sha256sum` in the PKGBUILD, and a header recording exactly what has
  been build-tested.

## [0.1.0] - 2026-07-31

Initial public release. Covers every settings category GameSir Nexus exposes
as a page of its own, with no Windows involvement anywhere in the stack. Not
parity with the whole app -- Nexus has scattered options not yet enumerated,
and motion/gyro is unimplemented by choice.

### Added

- **`pyg7`, a standalone protocol library** (Apache-2.0) implementing the
  GameSir G7 Pro's vendor configuration protocol over raw USB. Depends only
  on PyUSB, so it can be embedded in a service, a udev hook, or a one-off
  script without pulling in a GUI toolkit.
- **`g7ctl`, a scriptable CLI.** Per-category subcommands (`remap`,
  `stick-set`, `trigger-set`, `vibration-set`, `report-rate-set`, `dpad-set`,
  `dock-set`), whole-configuration `read-state`/`write-state` via JSON
  snapshots, `list` for the known button and keycode names, and `raw` for
  protocol exploration. It enters vendor mode on its own rather than
  requiring a separate setup command first.
- **`batch` mode** -- one continuous session for many commands, read from a
  script file, stdin, or an interactive prompt. A whole "read baseline →
  apply changes → read back to verify" sequence costs one handshake instead
  of one per command. `--dry-run` validates syntax without touching the
  device; `--continue-on-error` skips a bad line instead of stopping.
- **`g7ctlc`, a PyQt6 GUI and tray app** ("G7 Control Center",
  GPL-3.0-or-later) covering Buttons, Sticks, Triggers, Vibration and Report
  Rate, plus a Settings tab for the two device-global dock settings. It reads
  the selected profile's real current state on connect and on every profile
  switch, so it never sits showing stale values after a change made
  elsewhere. "Sync Now" reads a fresh baseline first and writes only what
  actually differs. Export/Import save and load the full state as JSON.
- **Full read and write coverage** of every Nexus settings page: button
  remapping across 21 buttons and both the Default and Shift layers, stick
  settings, trigger settings, vibration, report rate, D-pad options
  (including "Swap Left Stick and D-pad"), and the dock's LED brightness and
  auto on/off.
- **A complete keycode table** -- 119 values spanning keyboard, numpad,
  mouse, and every native gamepad and paddle function. The last five
  Controller-native gaps (`0x0D`, `0x11`, `0x12`, `0x1F`, `0x20`) were
  resolved by writing raw values to a scratch profile and reading back
  Nexus's own labels for them, rather than inferring from a read alone.
- **Explicit profile targeting.** Every per-profile category addresses one of
  the controller's four onboard slots directly, so no on-device button combo
  is ever needed to choose which profile a change lands in.
- **Wireless dongle support**, including a real liveness probe: the dongle is
  a separate USB device that enumerates and heartbeats happily on its own, so
  the tool checks that a controller is actually answering rather than
  reporting a false "connected".
- **Safe long-form writes.** Several settings (stick and trigger
  deadzone/anti-deadzone, and "Swap Left Stick and D-pad") use a write whose
  payload spans storage it doesn't conceptually own. Each reads that live
  span immediately before writing and replays it unchanged, instead of
  trusting a captured constant that would overwrite neighbouring settings
  with stale data.
- **udev rule** using systemd-logind's `uaccess`, so the CLI and GUI run as a
  normal user -- no group, no `usermod`, no re-login.
- **202 tests**, no controller required. Every payload builder and blob
  decoder runs against a fake session, with a fixture captured from real
  hardware. CI runs the suite and `ruff` on Python 3.9, 3.12, and 3.13.
- **[PROTOCOL.md](PROTOCOL.md)** -- a self-contained wire-format reference
  for the whole protocol, marking throughout which values are
  hardware-confirmed and which are predicted from a confirmed pattern.
- **Arch packaging** (`packaging/PKGBUILD`) producing three packages --
  `python-pyg7`, `g7ctl`, and `g7ctlc` -- from the single source tree.

### Licensing

- `pyg7/` (the protocol library) is **Apache-2.0**; `g7ctl/`, `g7ctlc/`, and
  the distribution as a whole are **GPL-3.0-or-later**. The library is
  permissive so anything can talk to this controller -- a distro daemon, a
  Steam Input helper, another config tool -- while the apps stay copyleft.
  Apache-2.0 rather than MIT for the patent grant and its explicit refusal to
  license trademarks.
- No GameSir code, firmware, or documentation is redistributed here. The tray
  icons are abstract gamepad-outline glyphs carrying no product likeness. See
  the README's non-affiliation and trademark notice.

### Known limitations

- Curve control-point editing, the motion/gyro tab, and Bluetooth mode are
  not implemented. Battery level was investigated and not solved. See
  [PROTOCOL.md](PROTOCOL.md) "Not implemented / out of scope" for the full
  list and what is known about each.
- The PKGBUILD is structurally validated but has not been build-tested
  against a real release tarball.

[Unreleased]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/questionablesyntax/g7ctl/releases/tag/v0.1.0
