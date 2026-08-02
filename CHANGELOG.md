# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [semantic versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/questionablesyntax/g7ctl/releases/tag/v0.1.0
