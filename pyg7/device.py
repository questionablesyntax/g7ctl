"""Finding the controller and switching it into vendor/config mode.

Progress here goes through `logging`, not print(): this module is imported
by the GUI as well as the CLI, and a bare print() from a background watcher
thread lands on whatever terminal the app happened to be launched from --
invisible to the user and impossible for an embedding application to
capture or silence. cli.py attaches a plain message-only handler so
command-line output is unchanged.
"""
import logging
import time
from typing import List, Optional, Tuple

import usb.core
import usb.util

from .constants import (
    EMPTY_FLUSH, EP_OUT, HANDSHAKE_CHUNKS, IFACE, PID_DONGLE, PID_NATIVE, PID_VENDOR, PID_XINPUT, VID,
)

log = logging.getLogger(__name__)


def find_device(pid: int) -> Optional[usb.core.Device]:
    return usb.core.find(idVendor=VID, idProduct=pid)


def find_native_identity() -> Optional[usb.core.Device]:
    """The controller in its own "default GameSir identity" (`PID_NATIVE`)
    -- not usable by this tool; see `PID_NATIVE`'s comment in constants.py.
    A caller that can't find the device at any identity it *does* know how
    to talk to should check this before reporting a generic "no device
    found", so a user who's holding it in the wrong identity gets told how
    to fix that (hold Menu+Share) instead of "plug it in"."""
    return find_device(PID_NATIVE)


def find_writable_device() -> Tuple[Optional[usb.core.Device], bool]:
    """Find a device already ready to accept 0x0f vendor writes -- either the
    wired controller in vendor mode (PID_VENDOR, requires enter_vendor_mode()
    first) or the wireless dongle (PID_DONGLE, needs no mode switch at all).
    Returns (device, via_dongle) or (None, False)."""
    dev = find_device(PID_VENDOR)
    if dev is not None:
        return dev, False
    dev = find_device(PID_DONGLE)
    if dev is not None:
        return dev, True
    return None, False


def make_handshake_packets() -> List[bytes]:
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


def enter_vendor_mode(timeout_s: float = 10.0) -> Optional[usb.core.Device]:
    dev = find_device(PID_XINPUT)
    if dev is None:
        if find_native_identity() is not None:
            log.error(
                "Controller is in its native GameSir identity (%04x:%04x), not "
                "XInput mode -- this tool can't talk to it there yet. Hold "
                "Menu+Share on the controller to switch back to XInput, then "
                "try again.", VID, PID_NATIVE)
        else:
            log.error("No device found at %04x:%04x.", VID, PID_XINPUT)
        return None

    log.info("Found XInput-mode device (bus=%s addr=%s).", dev.bus, dev.address)
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
        vdev = find_device(PID_VENDOR)
        if vdev is not None:
            log.info("Now in vendor mode (bus=%s addr=%s).", vdev.bus, vdev.address)
            return vdev
        time.sleep(0.3)
    log.error("Timed out waiting for vendor-mode re-enumeration.")
    return None
