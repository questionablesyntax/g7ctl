"""Finding the controller and switching it into vendor/config mode.

Progress here goes through `logging`, not print(): this module is imported
by the GUI as well as the CLI, and a bare print() from a background watcher
thread lands on whatever terminal the app happened to be launched from --
invisible to the user and impossible for an embedding application to
capture or silence. cli.py attaches a plain message-only handler so
command-line output is unchanged.
"""
import glob
import logging
import os
import time
from typing import Optional

import usb.core
import usb.util

from .constants import (
    EMPTY_FLUSH,
    EP_OUT,
    HANDSHAKE_CHUNKS,
    IFACE,
    PID_DONGLE,
    PID_NATIVE,
    PID_VENDOR,
    PID_VENDOR_TRIMODE,
    PID_XINPUT,
    VID,
)

log = logging.getLogger(__name__)

# Where the kernel publishes per-device USB state. A module constant rather
# than a literal so tests can point it at a fixture directory.
SYSFS_USB_ROOT = "/sys/bus/usb/devices"

# Minimum seconds between re-enumerations before we add another one.
#
# Rapid re-enumeration is what wedges this firmware's read path: reads stop
# answering entirely while heartbeats and writes carry on, and nothing in
# software clears it -- not a host reboot, not dev.reset(), not a cable
# replug, not even the manual's own pinhole reset. Only holding Share+Menu
# on the controller, which itself costs the user every non-native binding on
# the active profile and the Shift layer.
#
# The hardware paces itself everywhere a *person* can trigger a mode change:
# Menu+Share and the M+button profile combos all need a multi-second hold,
# so thumbs cannot cycle quickly. The "gamesirapp" handshake has no such
# gate -- five 8-byte writes and the device re-enumerates as fast as USB
# allows. So this floor is not a workaround for a mystery; it is software
# honouring a limit the firmware assumes the hardware enforces.
#
# 5s is a judgment call. Deliberate induction took 7-12 rapid cycles, and
# the GUI has never wedged in normal use because its read-on-connect already
# takes seconds -- so this is roughly "be no faster than the app that is
# known to be safe."
HANDSHAKE_MIN_INTERVAL = 5.0

# Every PID the "gamesirapp" handshake is known (or reported) to land on,
# paired with whether that PID means "via the dongle". PID_VENDOR_TRIMODE is
# additive only -- it does not change behavior for any PID already in this
# list, it just gives find_writable_device()/enter_vendor_mode() one more
# place to look. A single source of truth so a future variant only needs
# adding here, not in every loop that checks "is this a vendor identity".
VENDOR_PID_CANDIDATES = ((PID_VENDOR, False), (PID_DONGLE, True), (PID_VENDOR_TRIMODE, False))


def find_device(pid: int) -> Optional[usb.core.Device]:
    return usb.core.find(idVendor=VID, idProduct=pid)


def _sysfs_node(dev: usb.core.Device) -> Optional[str]:
    """The sysfs directory for a pyusb device, matched on bus + device
    number (`devnum` is the same value pyusb calls `address`)."""
    for path in glob.glob(os.path.join(SYSFS_USB_ROOT, "*") + os.sep):
        try:
            with open(os.path.join(path, "busnum")) as fh:
                busnum = int(fh.read())
            with open(os.path.join(path, "devnum")) as fh:
                devnum = int(fh.read())
        except (OSError, ValueError):
            continue          # not a USB device node, or vanished mid-scan
        if busnum == dev.bus and devnum == dev.address:
            return path
    return None


def seconds_since_enumeration(dev: usb.core.Device) -> Optional[float]:
    """How long ago `dev` appeared on the bus, or None if unknowable.

    Asks the kernel rather than remembering ourselves. That matters for
    more than tidiness: our own record would only cover handshakes *we*
    performed, and would be blind to a re-enumeration caused by GameSir
    Nexus, an on-device profile switch (which re-enumerates twice), or the
    user replugging the cable -- which are exactly the events worth pacing
    against. It is also cross-process for free, since it was never our
    state to begin with.

    `power/connected_duration` resets on every re-enumeration, confirmed on
    hardware 2026-08-11: 17268ms before a handshake, 3394ms after, with
    `devnum` incrementing and the directory's ctime moving to match. It
    depends on CONFIG_PM, so the directory's own ctime is the fallback --
    both agreed to within a second in testing.
    """
    node = _sysfs_node(dev)
    if node is None:
        return None
    try:
        with open(os.path.join(node, "power", "connected_duration")) as fh:
            return int(fh.read()) / 1000.0
    except (OSError, ValueError):
        pass
    try:
        return max(0.0, time.time() - os.stat(node).st_ctime)
    except OSError:
        return None


def _pace_handshake(dev: usb.core.Device, min_interval: float) -> None:
    """Sleep until `dev` has been enumerated for at least `min_interval`.

    Deliberately a sleep rather than a refusal: a command that mysteriously
    fails is worse than one that is briefly slow, and the caller usually
    has no useful alternative. Anyone hitting this repeatedly wants
    `g7ctl batch`, which holds one session for many commands -- so the log
    line says so.
    """
    if min_interval <= 0:
        return
    age = seconds_since_enumeration(dev)
    if age is None:
        # No sysfs (unusual kernel, container, non-Linux). Degrade to no
        # pacing rather than failing -- a safety aid must never be the
        # reason a command cannot run.
        log.debug("could not determine enumeration age; skipping handshake pacing")
        return
    if age >= min_interval:
        return
    wait = min_interval - age
    log.info(
        "Device re-enumerated %.1fs ago; pausing %.1fs before handshaking. "
        "Rapid re-enumeration wedges this controller's read path, and only "
        "holding Share+Menu clears it (which erases the active profile's "
        "remaps). Running several commands? Use `g7ctl batch` -- one session, "
        "one handshake.", age, wait)
    time.sleep(wait)


def find_native_identity() -> Optional[usb.core.Device]:
    """The controller in its own "default GameSir identity" (`PID_NATIVE`)
    -- not usable by this tool; see `PID_NATIVE`'s comment in constants.py.
    A caller that can't find the device at any identity it *does* know how
    to talk to should check this before reporting a generic "no device
    found", so a user who's holding it in the wrong identity gets told how
    to fix that (hold Menu+Share) instead of "plug it in"."""
    return find_device(PID_NATIVE)


# Interface 1 is what actually distinguishes the two personalities, and on
# firmware v2.4.4 it is the ONLY thing that does -- see is_xinput_personality().
HID_INTERFACE_CLASS = 0x03
PERSONALITY_INTERFACE = 1


def _interface_classes(dev: usb.core.Device, number: int) -> list:
    """Every alternate setting's bInterfaceClass for one interface number.

    Returns [] when the descriptors can't be read -- a device that is
    mid-re-enumeration, or gone. Callers must treat [] as "don't know"
    rather than as any particular answer.
    """
    try:
        cfg = dev.get_active_configuration()
    except Exception:  # pragma: no cover - depends on live USB state
        return []
    return [i.bInterfaceClass for i in cfg if i.bInterfaceNumber == number]


def is_xinput_personality(dev: usb.core.Device) -> bool:
    """Is this device presenting the XInput personality (a working gamepad),
    rather than the vendor/config one?

    **PID is not a reliable answer to this, and stopped being one.** The
    identity model in this project was built on firmware v2.0.9, where
    XInput was `PID_XINPUT` and vendor/config was `PID_VENDOR`. On v2.4.4
    (`bcdDevice` 0244) the controller enumerates the **XInput personality at
    PID_VENDOR**: measured 2026-08-18 on a freshly-plugged controller
    reporting `3537:109b` with iProduct "Xbox 360 Controller for Windows",
    `xpad` bound, `/dev/input/js0` live, and 2531 XInput report frames
    (`00 14 00 04 ...`) in 6s on EP 0x82. `find_device(PID_XINPUT)` finds
    nothing at all on that firmware.

    Interface 1 still separates them cleanly, and is the discriminator used
    here because it describes function rather than labelling:

    - XInput personality: interface 1 is **HID** (class 0x03), the composite
      keyboard+mouse device that emits remapped key/mouse events.
    - Vendor/config personality: interface 1 is not HID -- vendor class or
      the isochronous audio pair, depending on identity and alt setting.

    iProduct ("Xbox 360 Controller for Windows" vs "GameSir-G7 Pro") tracks
    the same split, but a descriptor class is a stronger thing to branch on
    than a marketing string.

    Answers **False when the descriptors can't be read**, so an unreadable
    device keeps this module's previous behaviour rather than becoming
    invisible to it.
    """
    return HID_INTERFACE_CLASS in _interface_classes(dev, PERSONALITY_INTERFACE)


def find_xinput_device() -> Optional[usb.core.Device]:
    """The controller in its XInput personality, at whichever PID this
    firmware puts it behind.

    PID_XINPUT first (v2.0.9 and, presumably, anything that still uses it),
    then the vendor PIDs filtered by personality (v2.4.4, where the XInput
    personality lives at PID_VENDOR). Returns None if the controller isn't
    present in that personality at all.
    """
    dev = find_device(PID_XINPUT)
    if dev is not None:
        return dev
    for pid in (PID_VENDOR, PID_DONGLE):
        dev = find_device(pid)
        if dev is not None and is_xinput_personality(dev):
            return dev
    return None


def find_writable_device() -> tuple[Optional[usb.core.Device], bool]:
    """Find a device *already* ready to accept 0x0f vendor writes -- the wired
    controller at PID_VENDOR or the dongle at PID_DONGLE. Returns
    (device, via_dongle) or (None, False).

    Neither personality is where the hardware idles: the vendor ones are
    reached by enter_vendor_mode()'s handshake, and fall back once heartbeats
    stop. This finds the ones already switched, which in practice is most of
    the time -- a previous session usually left it there.

    **The PID alone is not enough to decide this.** On firmware v2.4.4 the
    XInput personality -- a working gamepad, `xpad` bound and `js0` live --
    also enumerates at PID_VENDOR. Matching on PID alone claimed it, which
    detached `xpad`, took the user's controller away mid-use, and then held a
    heartbeat loop on a device whose vendor endpoint answers nothing, which
    presents as a wedge without being one. See is_xinput_personality().

    Checks every PID in VENDOR_PID_CANDIDATES, not just PID_VENDOR/
    PID_DONGLE -- see that constant's comment.
    """
    for pid, via_dongle in VENDOR_PID_CANDIDATES:
        dev = find_device(pid)
        if dev is not None and not is_xinput_personality(dev):
            return dev, via_dongle
    return None, False


def make_handshake_packets() -> list[bytes]:
    packets = []
    for i, pair in enumerate(HANDSHAKE_CHUNKS):
        b = bytearray(8)
        b[1] = 0x08
        b[3] = ord(pair[0])
        b[4] = ord(pair[1])
        packets.append(bytes(b))
        if i < len(HANDSHAKE_CHUNKS) - 1:
            packets.append(EMPTY_FLUSH)
    return packets


# How long _find_stable_xinput_device() will keep re-checking before giving
# up on a device that's found but never settles -- see that function's
# docstring. Generous on purpose: rapid re-enumeration wedging this
# controller's read path (see HANDSHAKE_MIN_INTERVAL above) has been
# observed lasting several minutes in a bad stretch, and giving up early
# just means the caller's own retry (the GUI watcher's poll loop, or the
# user re-running the CLI) has to notice and try again anyway. A wait
# longer than this without settling is itself useful information -- see
# the caller's error message when this returns None.
SETTLE_MAX_WAIT = 30.0


def _find_stable_xinput_device(min_interval: float,
                                max_wait_s: float = SETTLE_MAX_WAIT) -> Optional[usb.core.Device]:
    """Find an XInput-personality device, but don't hand it back until it's
    been sitting still -- re-finding it fresh on every check rather than
    trusting one snapshot across the whole wait.

    The previous approach found the device once, slept out
    `_pace_handshake()`'s wait against that one snapshot's age, and then
    used the same (possibly by-then-stale) `Device` object to
    detach/claim/write. If the device re-enumerated again during the sleep,
    every one of those calls was silently operating on a device that no
    longer existed at that bus/address -- the handshake never actually
    reached the device that *did* exist, and the whole attempt spent its
    full `timeout_s` waiting for a vendor-mode re-enumeration nothing had
    triggered. Confirmed against a real stuck-for-minutes incident: GameSir
    Nexus's own successful recovery from the identical stuck state sent a
    byte-for-byte identical handshake, but only after the device had
    already been presenting a stable XInput report stream for ~550ms. This
    re-finds the device on every check specifically so a re-enumeration
    mid-wait is caught and re-paced, not silently missed.

    Reuses `_pace_handshake()` unchanged (same tested single-sleep
    contract) rather than reimplementing its logic -- this just loops it
    against a freshly-found device each time instead of a single stale one.

    Returns `None` if no device is ever found, or if one is found but never
    settles within `max_wait_s` -- both cases the caller already
    distinguishes for its own error message.
    """
    dev = find_xinput_device()
    if dev is None or min_interval <= 0:
        return dev
    deadline = time.time() + max_wait_s
    while True:
        age = seconds_since_enumeration(dev)
        if age is None or age >= min_interval:
            return dev
        if time.time() >= deadline:
            return None
        _pace_handshake(dev, min_interval)
        dev = find_xinput_device()  # re-find fresh -- may have re-enumerated during that sleep
        if dev is None:
            return None


def enter_vendor_mode(timeout_s: float = 10.0,
                       min_interval: float = HANDSHAKE_MIN_INTERVAL) -> tuple[Optional[usb.core.Device], bool]:
    """Handshake the controller out of XInput mode and into a vendor identity.

    Returns `(device, via_dongle)`, the same shape `find_writable_device()`
    returns -- callers need the flag to pick the session's timeouts and to
    decide whether the liveness probe applies.

    The wireless dongle re-enumerates too. Corrected 2026-08-01: this
    function used to wait for `PID_VENDOR` alone, on the belief that the
    dongle had no XInput identity to switch out of. It does -- an idle
    dongle sits at `PID_XINPUT` with `xpad` bound, takes the same
    `"gamesirapp"` handshake, and comes back as `PID_DONGLE`. Waiting for
    only `109b` meant every dongle connect from idle burned the full
    `timeout_s` and logged a failure, then quietly succeeded on the caller's
    next `find_writable_device()` poll. Observed directly: same USB port,
    `disconnect` at handshake, re-enumerated as `109c` ~2s later.
    """
    # Not find_device(PID_XINPUT): on firmware v2.4.4 the XInput personality
    # enumerates at PID_VENDOR, so looking for PID_XINPUT alone finds nothing
    # and this reports "no device" for a controller sitting right there.
    #
    # _find_stable_xinput_device(), not a bare find_xinput_device() + a
    # single _pace_handshake(): see that function's docstring for why
    # re-finding fresh on every check matters -- a stale snapshot silently
    # breaks pacing if the device re-enumerates again during the wait.
    dev = _find_stable_xinput_device(min_interval)
    if dev is None:
        if find_native_identity() is not None:
            log.error(
                "Controller is in its native GameSir identity (%04x:%04x), not "
                "XInput mode -- this tool can't talk to it there yet. Hold "
                "Menu+Share on the controller to switch back to XInput, then "
                "try again.", VID, PID_NATIVE)
        elif find_xinput_device() is not None:
            log.error(
                "Device is present but keeps re-enumerating -- it never settled "
                "into a stable state within %.1fs. Not a missing device: it's "
                "still cycling. Try again once it stops.", SETTLE_MAX_WAIT)
        else:
            log.error("No device found at %04x:%04x.", VID, PID_XINPUT)
        return None, False

    log.info("Found stable XInput-mode device (bus=%s addr=%s).", dev.bus, dev.address)
    detached = False
    if dev.is_kernel_driver_active(IFACE):
        dev.detach_kernel_driver(IFACE)
        detached = True

    usb.util.claim_interface(dev, IFACE)
    try:
        for pkt in make_handshake_packets():
            dev.write(EP_OUT, pkt)
            time.sleep(0.02)
    except usb.core.USBError as e:
        # Device may vanish mid-write once it decides to re-enumerate; that's expected.
        log.info("(write interrupted, likely re-enumerating: %s)", e)
    finally:
        try:
            usb.util.release_interface(dev, IFACE)
        except Exception as e:
            # Expected in the common case: the device is about to
            # re-enumerate anyway, so releasing an interface that's already
            # gone is routine, not exceptional -- but per this module's own
            # logging philosophy (see module docstring), a genuine failure
            # here should leave a trace somewhere, not vanish silently.
            log.debug("release_interface failed (likely already re-enumerating): %s", e)
        if detached:
            try:
                dev.attach_kernel_driver(IFACE)
            except Exception as e:
                log.debug("attach_kernel_driver failed (likely already re-enumerating): %s", e)

    log.info("Handshake sent, waiting for re-enumeration to vendor mode...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # Checks every PID in VENDOR_PID_CANDIDATES, not just PID_VENDOR/
        # PID_DONGLE -- see that constant's comment. Order doesn't encode
        # priority; every candidate is an equally valid outcome of the same
        # handshake, just on different hardware.
        for pid, via_dongle in VENDOR_PID_CANDIDATES:
            vdev = find_device(pid)
            # The personality check is what makes this a wait at all on
            # firmware v2.4.4: the device is at PID_VENDOR both before and
            # after the handshake, so matching on PID alone returns the
            # *pre*-handshake device immediately and every read after it
            # fails. Waiting for interface 1 to stop being HID waits for the
            # thing that actually changes.
            if vdev is not None and not is_xinput_personality(vdev):
                log.info("Now in vendor mode (%04x:%04x, bus=%s addr=%s).",
                         VID, pid, vdev.bus, vdev.address)
                return vdev, via_dongle
        time.sleep(0.3)
    log.error("Timed out waiting for vendor-mode re-enumeration.")
    return None, False
