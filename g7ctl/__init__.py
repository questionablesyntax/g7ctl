# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 J Whittington (onemyndseye, questionablesyntax)
#
# The application is copyleft: improvements to the tool people actually run
# should come back. The protocol library it depends on (pyg7/) is
# Apache-2.0 instead -- that direction of dependency is fine, since
# Apache-2.0 code may be incorporated into a GPL-3.0 work. The reverse would
# not be. See ../LICENSE and README.md "License".
"""Command-line front end for the GameSir G7 Pro Linux config tool.

Talks to the controller only through pyg7/ (the Qt-free protocol
library) -- nothing here imports PyQt6, and the dependency never runs the
other way.

Layout:
  main.py   argument parsing, command dispatch, on-device command handlers
"""

__version__ = "0.1.5"
