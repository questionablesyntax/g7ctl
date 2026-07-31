# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 J Whittington (onemyndseye, questionablesyntax)
"""Static content for the Help menu's About / On-Device Features dialogs.

Kept as data, separate from main_window.py's widget wiring, matching this
package's existing one-file-per-concern layout (theme.py, tray.py). The
On-Device Features text is adapted from README.md's "On-device features"
section -- kept intentionally short here (this is a quick in-app reference,
not the full writeup) with a pointer back to the source of truth so the two
don't need to be regenerated from each other, just periodically checked
against it.
"""
from . import __version__

REPO_URL = "https://github.com/questionablesyntax/g7ctl"
ISSUES_URL = f"{REPO_URL}/issues"

ABOUT_HTML = f"""
<h3>G7 Control Center</h3>
<p>Version {__version__}</p>
<p>An independent, reverse-engineered configuration tool for the GameSir G7
Pro controller on Linux -- no Windows or GameSir Nexus required.</p>
<p>
<b>pyg7</b> (the protocol library) is licensed <b>Apache-2.0</b>;
this application and the distribution as a whole are licensed
<b>GPL-3.0-or-later</b>. See the repository's <code>README.md</code>
"License" section for the full text and rationale.
</p>
<p><i>Not affiliated with GameSir.</i> This is an independent, unofficial
project developed without the involvement or endorsement of Guangzhou
Chicken Run Network Technology Co., Ltd. "GameSir" and "G7 Pro" are used
only to identify the hardware this tool works with.</p>
<p><a href="{REPO_URL}">{REPO_URL}</a></p>
"""

ON_DEVICE_FEATURES_HTML = """
<h3>On-Device Features</h3>
<p>The controller does a lot on its own, via button combos -- worth knowing
regardless of this tool. Two of these can change settings
<b>out from under</b> a profile you've synced, which is the main reason
"Read from Device" exists.</p>
<ul>
<li><b>Switch profile:</b> M+Y = 1, M+B = 2, M+A = 3, M+X = 4. Fixed across
units.</li>
<li><b>Remap a back paddle on the fly</b> (L4/R4/L5/R5): hold M + the paddle
until the Xbox indicator flashes slowly, press the button you want mirrored
onto it, indicator goes solid. Press the paddle again while still in setting
mode to clear it. Independent of this tool's USB protocol -- it can silently
overwrite a paddle binding this tool wrote.</li>
<li><b>Toggle Hair Trigger Mode:</b> hold M + LT/RT for 2 seconds. Also
independent of this tool.</li>
<li><b>Recalibrate sticks and triggers:</b> set the trigger gear switch to
analog mode, hold View+Xbox+Menu until the indicator flashes, press A with
sticks and triggers untouched, then run both triggers to full travel and
both sticks to max angle three times each, and press A again (solid =
done).</li>
<li><b>LED legend:</b> breathing = reconnecting to a paired device; flowing =
Bluetooth pairing mode; solid = connected; off = powered down. Standby is 10
minutes of inactivity in 2.4GHz or Bluetooth mode.</li>
<li>The Bluetooth / Wired / 2.4GHz selector is a real 3-position hardware
switch. The nearby R4/L4 latch is unrelated -- a physical lock for the back
paddles.</li>
</ul>
<p>See the repository's <code>README.md</code> "On-device features" section
for the complete writeup.</p>
"""
