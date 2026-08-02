# g7ctl

A reverse-engineered implementation of GameSir Nexus's USB protocol, bringing
the GameSir G7 Pro's customization — button remapping, stick and trigger
settings, vibration, polling rate, dock options — to Linux without Windows or
the Nexus app.

Two components, one repo: `g7ctl`, a scriptable CLI, and `g7ctlc`
("G7 Control Center"), a PyQt6 GUI + tray app. Both sit on top of `pyg7`,
a standalone protocol library usable on its own from a script or a service.

Status: every settings category GameSir Nexus exposes as a page of its own is
mapped, with full read *and* write and zero Windows involvement — button
remapping (21 buttons, Default and Shift layers, the whole keycode picker
including native gamepad/paddle functions), stick settings, trigger settings,
vibration, report rate, D-pad options (including "Swap Left Stick and
D-pad"), and the dock's LED brightness / auto on-off. Every per-profile
category targets one of the controller's 4 onboard slots explicitly, so no
on-device button combo is ever needed to pick which profile a change lands
in.

**Scope: the GameSir G7 Pro, because that's the controller on the desk.**
That's what this was reverse-engineered against and the only hardware any of
it has ever run on.

It may work on more than that. What's implemented here is the GameSir Nexus
app's protocol rather than anything G7 Pro-specific: the vendor ID is
GameSir's, and the mode-switch handshake sends the string `"gamesirapp"`,
naming the app rather than a device. GameSir's own listing for Nexus says it
covers the **G7, Kaleid, and T7 / Tarantula Pro Xbox** families, so those are
the plausible candidates — each with model variants of its own. **None of
them has ever been tested here, and none is claimed to work.**

If you have one and want to try, the place to start is
`pyg7/constants.py`: it hard-codes the G7 Pro's four USB product IDs and
device discovery matches on them, so another model isn't merely untested, it
won't be detected at all. Add its product IDs there and see how far you get.
A report either way — including "the handshake works but the setting IDs are
different" — would be genuinely useful, and is the only way this question
gets answered.

Support for other models isn't planned at this time.

See [PROTOCOL.md](PROTOCOL.md) for the wire-format reference. It's
self-contained, organized for lookup rather than as a narrative, and marks
throughout which values are hardware-confirmed versus predicted from a
confirmed pattern.

## Repository layout

| Path | What it is |
|---|---|
| `pyg7/` | Protocol library (Apache-2.0). PyUSB only, no Qt — usable on its own. |
| `g7ctl/` | The CLI. |
| `g7ctlc/` | The GUI + tray app. |
| `g7ctl_tool.py` | Convenience shim: runs the CLI straight from a checkout, no install. Equivalent to the `g7ctl` command. |
| `g7ctlc_launcher.py` | Same idea for the GUI.  |
| `packaging/`, `udev/` | Arch PKGBUILDs (`packaging/` for a released tarball, `packaging/git/` for the tip of `main`) and desktop entry; the udev rule for non-root USB access. |

The two root-level scripts exist purely so a fresh `git clone` is runnable
with nothing installed. If you install the package, use the `g7ctl` and
`g7ctlc` commands instead — they do the same thing.

## Install

### Arch Linux

The easiest route, and the only one that sets up USB permissions for you:

```bash
git clone https://github.com/questionablesyntax/g7ctl
cd g7ctl/packaging && makepkg -si
```

That builds three packages -- `python-pyg7` (the library), `g7ctl` (the CLI)
and `g7ctlc` (the GUI) -- and you can install any subset; the two
applications pull the library in as a dependency. `python-pyg7` ships the
udev rule to `/usr/lib/udev/rules.d/`, so raw USB access works as your normal
user with no further setup. Replug the controller once afterwards and you're
done -- you can skip [Running without root](#running-without-root) entirely.
`g7ctlc` also installs a desktop entry and icon, so the GUI shows up in your
application launcher.

Not on the AUR yet; build it from a checkout as above.

To build the current tip of `main` instead of the last release -- protocol
fixes tend to land well before a version is cut -- use the VCS PKGBUILD:

```bash
cd g7ctl/packaging/git && makepkg -si
```

That produces `python-pyg7-git`, `g7ctl-git` and `g7ctlc-git`, which
conflict with and provide their stable counterparts, so the two sets are
mutually exclusive: installing `g7ctlc-git` replaces `g7ctlc`. It clones the
repository itself, versions each build as `0.1.2.rN.g<hash>` so pacman
orders successive builds correctly, and runs the test suite during the build
-- worth doing on a source that isn't a reviewed release tag.

Nothing here is Arch-specific, though, and the layout is deliberately
packaging-friendly: a standard PEP 517 build, three importable packages with
the dependency arrow pointing one way (both apps depend on the library, never
the reverse), PyQt6 isolated behind an optional extra so the library installs
headless, the udev rule and desktop entry as plain standalone files, no
vendored dependencies, and 209 tests that run without any hardware attached
so a packager can execute them during a build. Packaging for other distros
should be straightforward, and contributions doing so are welcome.

### Anything else

The protocol library needs only [PyUSB](https://github.com/pyusb/pyusb); the
desktop app is an optional extra, so you can install the library on its own
for scripting or a service.

```bash
pip install -e .          # protocol library + the `g7ctl` CLI
pip install -e ".[gui]"   # also installs PyQt6 and `g7ctlc`
```

Running straight from a checkout works without installing anything -- use
`python3 g7ctl_tool.py` and `./g7ctlc_launcher.py` in place of the two
commands below.

Going this route, raw USB access needs either root or a one-time udev rule --
see [Running without root](#running-without-root), which is the recommended
setup and required for the GUI's tray icon to work.

## Usage

```bash
# Remap a button. The tool switches the controller into vendor/config mode
# itself if it isn't already -- wired or wireless, no separate step needed.
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

The keycode table covers every entry in Nexus's own picker -- Keyboard,
Numpad, Mouse, and all native gamepad/paddle functions. The byte space itself
isn't exhaustively enumerated, though: at least one region outside those
blocks exists (`0xE6`/`0xE7`, see PROTOCOL.md), so an unrecognised value is
surfaced as raw hex rather than dropped.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

209 tests, no controller required -- payload builders and blob decoders run
against a fake session (`tests/fakes.py`), and `tests/fixtures/live_read.json`
holds real `read_state()` output captured from a physical controller. The
GUI's view round-trip tests (headless, offscreen platform) are skipped
automatically if PyQt6 isn't installed. Please keep them passing; they exist
because a wrong byte here doesn't raise an error, it writes something
unintended to a device's persistent config.

## Running without root

**Installed the Arch packages? Skip this section** -- `python-pyg7` already
shipped the rule to `/usr/lib/udev/rules.d/`. Just replug the controller
once. This section is for pip installs and checkout runs.

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

<img src="docs/screenshot.png" alt="G7 Control Center showing the Buttons tab: each of the 21 buttons listed with its Default Layer and Shift Layer binding, a profile selector and report rate in the top bar, and Read from Device / Sync Now actions along the bottom." width="480">

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
snapshot file at a path you choose.

**While the app is connected, the controller is not usable for playing --
wired and over the 2.4GHz dongle alike.** To read or write configuration the
controller has to be in its vendor/config identity, and in that identity it
is not presenting as an Xbox pad: no XInput gamepad, and no HID
keyboard/mouse to emit your remapped keys (see
[PROTOCOL.md](PROTOCOL.md) "Device identities"). That is a property of the
controller, not of the cable: wireless works the same way, one USB product
ID apart. An idle dongle enumerates as an ordinary Xbox pad, takes the same
mode-switch handshake, and drops back to being a pad once nothing is
holding it. "Release Device" hands the controller back
without quitting the app; the button then becomes "Reconnect". The CLI has
the same property -- it holds the device only for the duration of a
command. Expect the wireless controller to be generally a little slower to
respond than the wired one, handover included; the extra RF hop is why the
session runs relaxed timeouts over the dongle.

Left-clicking the tray icon shows/hides the window. From a checkout:

```bash
./g7ctlc_launcher.py
```

`python3 -m g7ctlc` and the installed `g7ctlc` command work identically --
all three go through `g7ctlc.app:main()`, so pick whichever suits you.

On startup the app renames its own process to "g7ctlc" via
`prctl(PR_SET_NAME, ...)` (stdlib `ctypes`, Linux-only, best-effort), rather
than showing up as "python3". Window managers (KWin included) derive a
window's class from the process's kernel `comm` name, which
`QApplication.setDesktopFileName()` alone doesn't control from inside the
app. Without it, KDE's taskbar/alt-tab/Window Rules would identify every
window as generic "python3", so a window rule meant for this app would match
any Python script on your system.

To have it show up properly in KDE's application launcher too, install
the desktop entry:

```bash
mkdir -p ~/.local/share/applications
sed "s|/path/to/g7ctl|$PWD|g" packaging/g7ctlc.desktop \
  > ~/.local/share/applications/g7ctlc.desktop
```

## On-device features (no software needed)

The controller does a lot on its own, via button combos. Worth knowing about
regardless of this tool -- and two of them can change settings **out from
under** a configuration you synced, which is the main reason "Read from
Device" exists.

- **Switch profile:** `M`+`Y` = 1, `M`+`B` = 2, `M`+`A` = 3, `M`+`X` = 4.
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

## License

Copyright 2026 J Whittington (questionablesyntax).

Two licenses, matching the package split:

- **`pyg7/` (the protocol library) — Apache-2.0.** Permissive on
  purpose. The protocol work is the useful part, and anyone should be able
  to build on it: a distro daemon, a Steam Input helper, another tool.
- **`g7ctlc/`, `g7ctl/`, and the project as a whole —
  GPL-3.0-or-later.**

### Not affiliated with GameSir

This is an independent, unofficial project, developed without the
involvement or endorsement of Guangzhou Chicken Run Network Technology Co.,
Ltd. "GameSir" and "G7 Pro" are used only to identify the hardware this
tool works with. No GameSir code, firmware, or documentation is
redistributed here — the protocol was derived by observing USB traffic to
and from a controller we own, and every line in this repository was written
from those observations.
