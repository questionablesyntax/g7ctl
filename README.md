# g7ctl

Reverse engineering GameSir Nexus's protocol for the GameSir G7 Pro
controller, to bring its customization features (button remapping first,
eventually stick/trigger/vibration/motion/polling-rate settings) to Linux
without needing Windows or the Nexus app.

Two components, one repo: `g7ctl`, a scriptable CLI, and `g7ctlc`
("G7 Control Center"), a PyQt6 GUI + tray app. Both sit on top of `pyg7`,
a standalone protocol library usable on its own from a script or a service.

Status: feature-complete against the GameSir Nexus app for everything it
exposes, with zero Windows involvement. Full read *and* write coverage for
button remapping (21 buttons, Default and Shift layers, every keycode
including all native gamepad/paddle functions), stick settings, trigger
settings, vibration, report rate, D-pad options (including "Swap Left Stick
and D-pad"), and the dock's LED brightness / auto on-off. Every per-profile
category targets one of the controller's 4 onboard slots explicitly, so no
on-device button combo is ever needed to pick which profile a change lands
in.

See [PROTOCOL.md](PROTOCOL.md) for the wire-format reference. It's
self-contained, organized for lookup rather than as a narrative, and marks
throughout which values are hardware-confirmed versus predicted from a
confirmed pattern.

## Install

The protocol library needs only [PyUSB](https://github.com/pyusb/pyusb); the
desktop app is an optional extra, so you can install the library on its own
for scripting or a service.

```bash
pip install -e .          # protocol library + the `g7ctl` CLI
pip install -e ".[gui]"   # also installs PyQt6 and `g7ctlc`
```

On Arch the dependencies are also packaged: `sudo pacman -S python-pyusb
python-pyqt6`. Running straight from a checkout works without installing
anything -- use `python3 g7ctl_tool.py` and `./g7ctlc_launcher.py` in
place of the two commands below.

Raw USB access needs either root or a one-time udev rule -- see
[Running without root](#running-without-root), which is the recommended
setup and required for the GUI's tray icon to work.

## Usage

```bash
# Remap a button. The tool switches the controller into vendor/config mode
# itself if it isn't already; with the wireless dongle no switch is needed.
g7ctl remap share f11
g7ctl remap a f12 --shift          # target the Shift Layer instead
g7ctl remap b native_b --profile 2 # target a specific onboard profile

# Read a profile's current settings back from the device
g7ctl read-state --profile 1
g7ctl read-state --profile 1 --save snapshot.json

# Push a whole saved configuration (only writes what actually differs)
g7ctl write-state snapshot.json

# List known button/keycode names (no device needed)
g7ctl list

# Send a raw command for protocol exploration -- no validation at all,
# unlike every other command above; sent to the device exactly as given
g7ctl raw 3c 0305007b013e

# Run several commands in one continuous session -- one handshake instead
# of one per command, useful for a rapid sequence of remaps/settings or a
# read -> apply -> read-to-verify script.
g7ctl batch myscript.txt        # one command per line, '#' comments
cat myscript.txt | g7ctl batch  # or pipe from stdin
g7ctl batch                     # no file -> interactive prompt
g7ctl batch myscript.txt --dry-run             # validate syntax only, no device touched
g7ctl batch myscript.txt --continue-on-error    # skip a bad line instead of stopping
```

The keycode table is complete -- Keyboard, Numpad, Mouse, and every native
gamepad/paddle function.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

202 tests, no controller required -- payload builders and blob decoders run
against a fake session (`tests/fakes.py`), and `tests/fixtures/live_read.json`
holds real `read_state()` output captured from a physical controller. The
GUI's view round-trip tests (headless, offscreen platform) are skipped
automatically if PyQt6 isn't installed. Please keep them passing; they exist
because a wrong byte here doesn't raise an error, it writes something
unintended to a device's persistent config.

## Running without root

Raw USB access normally needs root, but a persistent GUI/tray app (see
`g7ctlc/`) shouldn't run as one -- among other things, KDE's system
tray icon is a D-Bus registration scoped to your desktop session, and a
root-owned process can't register one there (the main window still renders,
since Wayland socket access doesn't care about UID, but the tray icon
silently never appears).

One-time setup:

```bash
sudo cp udev/61-g7ctl.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the controller once so the new rule applies to its device
node -- no group, no `usermod`, no log out/in needed. The rule uses
systemd-logind's `uaccess` mechanism (the same one stock rules already use
for USB mice, cameras, and scanners), which grants access automatically to
whoever's logged in at the physical seat. After that, both
`g7ctl_tool.py`/`g7ctl/main.py` and `g7ctlc` run as your normal user, no
`sudo` needed.

## GUI

`g7ctlc/` is a PyQt6 app + system tray icon covering Buttons/Sticks/
Triggers/Vibration/Report Rate, plus a "Settings" tab for the two
genuinely global, non-profile-scoped Dock settings (LED Brightness, Auto
On/Off). There's no managed local profile list -- the device's own 4
profile slots are the source of truth, picked directly via the "Profile"
selector in the top bar (every per-profile category is confirmed
genuinely profile-scoped). On every connect (including the very
first one after launch) and every time you pick a different profile, the
app automatically reads that profile's actual current settings back across
all tabs (unless there are unsynced local edits pending, in which case the
auto-read is skipped rather than silently discarding them), so the GUI
never sits there showing stale state after e.g. a binding was changed via
GameSir Nexus. "Sync Now" pushes the current in-memory state to the
selected profile, and reads a fresh baseline first to skip any setting that
already matches (rsync-style -- covers every category, so an unchanged
sync is effectively a no-op instead of unconditionally rewriting ~28-30
non-button settings every time). "Read from Device" does the same read the
auto-read does, on demand, useful for detecting drift from the onboard
on-the-fly remap shortcuts. Deadzone/Anti-deadzone fields sync like
everything else, via a live-suffix read that avoids corrupting adjacent
settings sharing the same write. Both "Sync Now" and "Read from
Device" (when it would discard unsynced edits) ask for confirmation first --
the former pushes to persistent device config, the latter overwrites every
tab.
"Export…"/"Import…" save or load the entire current state as a JSON
snapshot file at a path you choose -- the only form of on-disk persistence
now; nothing auto-saves. A "Help" menu, top bar right, has About (version and
license summary), an On-Device Features reference (the button-combo cheat
sheet below, without leaving the app), and a link to report an issue.
Left-clicking the tray icon shows/hides the
window. Launch it via the `g7ctlc_launcher.py` script in the repo root, not
`python3 -m g7ctlc` directly:

```bash
./g7ctlc_launcher.py
```

That script is a normal Python launcher (`#!/usr/bin/env python3`) that
renames its own process via `prctl(PR_SET_NAME, ...)` (stdlib `ctypes`,
Linux-only, best-effort) before starting the GUI, so the process is
identified as "g7ctlc" rather than "python3.14". Window
managers (KWin included) derive a window's class from the process's
kernel `comm` name, which `QApplication.setDesktopFileName()` alone
doesn't control from inside the app. Without this, KDE's taskbar/alt-tab/
Window Rules would identify every window as generic "python3", making
window rules match any Python script on your system, not just this app.

To have it show up properly in KDE's application launcher too, install
the desktop entry:

```bash
mkdir -p ~/.local/share/applications
sed "s|/path/to/g7ctl|$PWD|g" packaging/g7ctlc.desktop \
  > ~/.local/share/applications/g7ctlc.desktop
```

Run that from the root of your checkout. The shipped `.desktop` file uses a
`/path/to/g7ctl` placeholder in its `Exec=`/`Path=`/`Icon=` lines, since a
checkout-scoped launcher has no way to know where you cloned it; the `sed`
above substitutes your actual path. (Installing from a package instead? The
PKGBUILD generates its own `.desktop` pointing at the installed entry point,
so none of this applies.)

## On-device features (no software needed)

The controller does a lot on its own, via button combos. Worth knowing about
regardless of this tool -- and two of them can change settings **out from
under** a configuration you synced, which is the main reason "Read from
Device" exists.

- **Switch profile:** `M`+`Y` = 1, `M`+`B` = 2, `M`+`A` = 3, `M`+`X` = 4.
  Fixed across units.
- **Remap a back paddle on the fly** (`L4`/`R4`/`L5`/`R5`): hold `M` + the
  paddle until the Xbox indicator flashes slowly, press the button you want
  mirrored onto it, indicator goes solid. Press the paddle again while still
  in setting mode to clear it. This is a firmware-local "mirror this button"
  feature, separate from this tool's USB protocol, and limited to the four
  paddles — **it can silently overwrite a paddle binding this tool wrote.**
- **Toggle Hair Trigger Mode:** hold `M` + `LT`/`RT` for 2 seconds. Also
  independent of this tool, and likewise able to change trigger state
  underneath a synced profile.
- **Recalibrate sticks and triggers:** set the trigger gear switch to analog
  mode, hold `View`+`Xbox`+`Menu` until the indicator flashes, press `A`
  with sticks and triggers untouched, then run both triggers to full travel
  and both sticks to max angle three times each, and press `A` again (solid
  = done). Useful if raw axis values ever look off.
- **LED legend:** breathing = reconnecting to a paired device; flowing =
  Bluetooth pairing mode; solid = connected; off = powered down. **Standby
  is 10 minutes of inactivity** in 2.4GHz or Bluetooth mode.
- The Bluetooth / Wired / 2.4GHz selector is a real 3-position hardware
  switch. The nearby `R4/L4` latch is unrelated — a physical lock for the
  back paddles.

The official PDF manual is not redistributed here (it's GameSir's
copyright); the above is written from it in our own words.

## License

Copyright 2026 J Whittington (onemyndseye, questionablesyntax).

Two licenses, matching the package split:

- **`pyg7/` (the protocol library) — Apache-2.0.** Permissive on
  purpose. The protocol work is the valuable part, and anyone should be able
  to build on it: a distro daemon, a Steam Input helper, another tool.
- **`g7ctlc/`, `g7ctl/`, and the project as a whole —
  GPL-3.0-or-later.** Improvements to the app come back.

That direction works because Apache-2.0 code may be incorporated into a
GPL-3.0 work; the reverse is not true, and the GUI depends on the library
rather than the other way around.

### Not affiliated with GameSir

This is an independent, unofficial project, developed without the
involvement or endorsement of Guangzhou Chicken Run Network Technology Co.,
Ltd. "GameSir" and "G7 Pro" are used only to identify the hardware this
tool works with. No GameSir code, firmware, or documentation is
redistributed here — the protocol was derived by observing USB traffic to
and from a controller we own, and every line in this repository was written
from those observations.
