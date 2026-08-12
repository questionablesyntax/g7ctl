# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 J Whittington (onemyndseye, questionablesyntax)
#
# The application is copyleft: improvements to the tool people actually run
# should come back. The protocol library it depends on (pyg7/) is
# Apache-2.0 instead -- that direction of dependency is fine, since
# Apache-2.0 code may be incorporated into a GPL-3.0 work. The reverse would
# not be. See ../LICENSE and README.md "License".
"""PyQt6 GUI + tray app for the GameSir G7 Pro Linux config tool.

Talks to the controller only through pyg7/ (the Qt-free protocol
library) -- nothing here imports pyusb directly, and the dependency never
runs the other way.

Layout:
  app.py         QApplication bootstrap; owns the watcher thread and signal wiring
  watcher.py     DeviceWatcher -- connect/heartbeat/job loop on a worker thread
  main_window.py MainWindow -- tabs, profile selector, Sync/Read/Import/Export
  views/         one widget per category tab (Buttons/Sticks/Triggers/Vibration/Settings)
  widgets.py     shared pickers and form controls used by more than one view
  tray.py        system tray icon, mirrors the watcher's connection state
  theme.py       the single QSS stylesheet
"""

__version__ = "0.1.8"
