"""OwnershipBar, A3 of the redesign ("the clamp bar", `DIRECTION-A.md`
section 5's `ClampBar`). Full-width, directly under the titlebar, on every
screen, with the release action in it (`DESIGN-SPEC.md` section 2's
"Persistent ownership bar"). `role=status`, polite: this is a status
region, not a control -- the capsule carries no button padding, and the
one actual control in it (Release/Reconnect) is styled neutral, because
handing the controller back is always safe.

Five connection states map onto four visual variants (`disconnected` and
`no_controller` share the same "no controller" look -- `DIRECTION-A.md`'s
own ClampBar inventory only has one slot for it; the two keep separate
wording for the same reason they always have: "never tried" and "tried,
nothing answered" are different facts worth saying, even though neither
looks different from the other). `alarm` is implemented but unwired in
this phase: CRITIC.md #7 keeps it for a connection-level alarm distinct
from an ordinary failed sync/read (which already surfaces through
`error_label` and a blocking dialog, DESIGN-SPEC.md 10.1 #7's own "the
bar stays Holding and an alarm inline notice sits directly beneath it")
-- nothing in this app raises that condition yet.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from g7ctlc.icon_loader import LucideIconLoader
from g7ctlc.palette import Palette

_STATUS_TEXT = {
    "disconnected": "No controller connected.",
    "connecting": "Connecting…",
    "connected": "Holding. This app has the controller. Its gamepad input is paused.",
    "paused": "Released. Click Reconnect to resume.",
    "no_controller": "No controller responding.",
    "alarm": "Something went wrong while holding the controller.",
}

_VARIANT = {
    "disconnected": "no_controller",
    "connecting": "connecting",
    "connected": "held",
    "paused": "released",
    "no_controller": "no_controller",
    "alarm": "alarm",
}

_RELEASE_BUTTON_TEXT = {"paused": "Reconnect"}


class OwnershipBar(QWidget):
    releaseRequested = pyqtSignal()  # True/False (release/reconnect) is MainWindow's call, not this bar's

    def __init__(self, palette: Palette, icon_loader: LucideIconLoader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "status")
        self.setAccessibleName("Controller ownership")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(10)
        # CRITIC.md #2, accepted: no pill, no button padding -- a status,
        # not a control. A small filled/hollow dot (never colour alone --
        # its own shape differs held vs. not) plus bold ordinary text
        # sitting directly on the bar's tint, not inside a second filled
        # shape. The first version of this file got this wrong (a filled
        # capsule with text.on-signal, CRITIC's finding #2's own *rejected*
        # design) -- caught by actually rendering it: text.on-signal is
        # near-black, same as the dark palette's near-black surface.signal-
        # tint background, so the word "Holding" was rendering invisible.
        self.dot = QLabel("", self)
        self.dot.setProperty("role", "ownership-dot")
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        self.capsule = QLabel("", self)
        self.capsule.setProperty("role", "capsule")
        top.addWidget(self.capsule)
        self.playability_label = QLabel("", self)
        self.playability_label.setToolTip(
            "Reading or writing configuration claims the gamepad interface "
            "directly, which detaches the kernel's controller driver for as "
            "long as the session is held -- not because configuration needs "
            "a special identity (it doesn't; both identities the controller "
            "can present answer it equally). This is just as true over the "
            "2.4GHz dongle as it is wired -- the dongle bridges the same "
            "session through. Click \"Release Device\" to hand the "
            "controller back without quitting."
        )
        top.addWidget(self.playability_label)
        top.addStretch(1)
        self.battery_label = QLabel("", self)
        self.battery_label.setProperty("role", "muted")
        self.battery_label.setToolTip(
            "Charge as reported by the controller itself.\n\n"
            "Read from the input stream it broadcasts while connected, so it "
            "costs no extra USB traffic and issues no config read."
        )
        self.battery_label.setVisible(False)
        top.addWidget(self.battery_label)
        self.release_button = QPushButton("Release Device", self)
        self.release_button.setEnabled(False)
        self.release_button.setToolTip(
            "Hand the controller back so it works as a gamepad again "
            "(stops heartbeating), without quitting the app"
        )
        self.release_button.clicked.connect(self.releaseRequested.emit)
        top.addWidget(self.release_button)
        layout.addLayout(top)

        self.detail_label = QLabel("", self)
        self.detail_label.setProperty("role", "secondary")
        layout.addWidget(self.detail_label)

        self.set_state("disconnected")

    def set_state(self, state: str) -> None:
        variant = _VARIANT.get(state, "no_controller")
        self.setProperty("variant", variant)
        self.style().unpolish(self)
        self.style().polish(self)
        # The dot carries its own `variant` property and is re-polished
        # directly, rather than relying on an ancestor-dependent QSS
        # selector cascading down from `self`'s own re-polish above.
        self.dot.setProperty("variant", variant)
        self.style().unpolish(self.dot)
        self.style().polish(self.dot)
        text = _STATUS_TEXT.get(state, state)
        self.capsule.setText(text)
        self.setAccessibleDescription(text)
        self.playability_label.setText(
            "not usable as a gamepad until released" if state == "connected" else ""
        )
        self.release_button.setText(_RELEASE_BUTTON_TEXT.get(state, "Release Device"))
        self.release_button.setEnabled(state in ("connected", "paused"))

    def set_release_enabled(self, enabled: bool) -> None:
        """Lets MainWindow suppress the release control mid-sync, same
        reasoning as every other hardware-facing control -- a click
        through this button during a write must not be able to drop the
        session (`request_sync_now()`/`request_read_from_device()`)."""
        self.release_button.setEnabled(enabled)

    def set_battery(self, percent: int, charging: bool) -> None:
        self.battery_label.setText(
            f"Battery: {percent}%" + ("  (charging)" if charging else ""))
        self.battery_label.setProperty("role", "muted" if percent > 20 else "caution")
        self.style().unpolish(self.battery_label)
        self.style().polish(self.battery_label)
        self.battery_label.setVisible(True)

    def clear_battery(self) -> None:
        self.battery_label.clear()
        self.battery_label.setVisible(False)

    def set_firmware_tooltip(self, text: str) -> None:
        self.capsule.setToolTip(text)
