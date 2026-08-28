# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 J Whittington (onemyndseye, questionablesyntax)
#
# This package -- the protocol library -- is Apache-2.0, deliberately more
# permissive than the GPL-3.0 app that sits on top of it, so any project can
# talk to this controller: a distro daemon, a Steam Input helper, another
# configuration tool. The hard-won part of this work is the protocol
# knowledge, and copyleft on that layer would only narrow who can use it.
# See LICENSE in this directory, and README.md "License" for the split.
"""Reverse-engineered protocol library for the GameSir G7 Pro's vendor config mode.

Qt-free and pyusb-only: nothing here imports the GUI, so this package is
usable from a script, a service, or a udev hook on its own.

Reading the modules in this order makes the protocol easiest to follow:

  constants.py  USB identities, command bytes, category prefixes
  device.py     finding the controller and switching it into vendor mode
  session.py    the claimed USB session: heartbeat, raw send, chunked read
  buttons.py    button remap/unbind + the shared keycode table
  sticks.py     \\
  triggers.py    | one module per settings category, each following the same
  motion.py      | decode_settings()/set_value() shape -- motion.py reuses
  vibration.py   | sticks.py's own category prefix and storage convention,
  report_rate.py | see its module docstring
  dpad_options.py|
  dock_settings.py /
  curves.py     curve preset payloads shared by sticks and triggers
  values.py     small coercion helpers shared by the category modules
  state.py      the JSON state schema, read_state(), and write_state()

The command-line front end (g7ctl/) and the GUI (g7ctlc/)
are separate packages that depend on this one -- neither is imported here.

See PROTOCOL.md at the repo root for the wire-format reference.
"""

__version__ = "0.2.1"
