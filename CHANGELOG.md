# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-07-31

Initial public release. Feature-complete against the GameSir Nexus app for
everything Nexus exposes, with no Windows involvement anywhere in the stack.

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
- **Full read and write coverage** of everything Nexus exposes: button
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

[Unreleased]: https://github.com/questionablesyntax/g7ctl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/questionablesyntax/g7ctl/releases/tag/v0.1.0
