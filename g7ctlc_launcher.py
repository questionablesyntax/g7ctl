#!/usr/bin/env python3
"""Run the GUI straight from a source checkout, with no install step.

If the project is pip-installed, prefer the `g7ctlc` console script instead
-- it does exactly the same thing. This script is named g7ctlc_launcher.py
rather than plain g7ctlc specifically to avoid colliding with the g7ctlc/
package directory sitting right next to it (a file and a directory can't
share one name in the same place, and giving them near-identical names
risks Python import ambiguity too). It exists so the app is runnable from a
fresh `git clone`, which is still the primary way it gets used.

The prctl(PR_SET_NAME) process rename that KDE's window matching depends on
used to live here, which meant it only applied when the app was started this
particular way. It now lives in g7ctlc.app.main(), so both launch paths
behave identically -- see _rename_process() there for why it's needed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from g7ctlc.app import main

if __name__ == "__main__":
    sys.exit(main())
