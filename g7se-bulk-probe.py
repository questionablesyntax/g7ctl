#!/usr/bin/env python3
"""g7se-bulk-probe.py -- test whether the G7 SE's third (bulk) interface
answers the config-read protocol that interface 0 does not.

Background: on a G7 SE (idProduct 0x1010, bcdDevice 6.33), `g7ctl diag`
succeeds -- it reads the firmware version fine over the normal config
interface (interface 0, EP_OUT=0x02/EP_IN=0x82). But `g7ctl read-state`
times out on that same interface: the actual per-profile settings data
never comes back, confirmed on two separate occasions. `lsusb -v`
against this same unit shows a third interface (interface 2,
alt-setting 1) with its own bulk endpoint pair (EP_OUT=0x01/EP_IN=0x81,
the same 64-byte packet size as interface 0) that this project has never
tried talking to. This script tries it.

Safe: read-only, start to finish. Every request below is a CMD_READ --
the same "ask the device to hand back a copy of its own settings"
operation `g7ctl read-state`/`g7ctl diag` already perform against every
other confirmed G7 Pro variant. Nothing here writes a setting, changes a
profile, or touches anything on the controller.

Usage:
    sudo python3 g7se-bulk-probe.py

Needs pyusb: `python3 -m pip install --user pyusb` if you don't have it
(the script will tell you plainly if it's missing rather than crash with
a confusing traceback).

Please paste EVERYTHING this prints, including any errors, back to the
g7ctl project -- a failure with a clear error is just as useful here as
a success.
"""
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("This needs the 'pyusb' package, which isn't installed.")
    print("Try: python3 -m pip install --user pyusb")
    print("Then run this script again.")
    sys.exit(1)

VID = 0x3537
PID = 0x1010

# Interface 0 -- the normal config channel. Known working here for
# device-info reads (g7ctl diag succeeded), known failing for CMD_READ
# profile reads (g7ctl read-state timed out, twice).
IFACE_0 = 0
EP_OUT_0 = 0x02
EP_IN_0 = 0x82

# Interface 2, alt-setting 1 -- the untested bulk pair from lsusb -v.
# This is the actual thing being tested.
IFACE_2 = 2
IFACE_2_ALT = 1
EP_OUT_2 = 0x01
EP_IN_2 = 0x81

# Same wire format g7ctl's own pyg7 library uses (pyg7/session.py's
# send_raw()/read_chunk(), pyg7/constants.py) -- reproduced here instead
# of imported, so this script has zero dependency on pyg7 being
# installed and can be handed to anyone with just pyusb.
CMD_HEARTBEAT = 0x02
CMD_READ = 0x05
READ_SUBCOMMAND = 0x04
REPORT_ID_READ_RESPONSE = 0x10
READ_RESPONSE_MARKER = 0x3c

SETTLE_HEARTBEATS = 24     # pyg7's own VendorSession.settle() default
SETTLE_INTERVAL = 0.25
READ_CHUNK_TIMEOUT = 4.0

# Exactly what `g7ctl read-state` asks for first, and exactly what
# already times out on interface 0 -- Profile 1's Default-layer blob,
# first chunk. 0x01 = profile_layer_byte(1, shift=False) in pyg7.
CATEGORY = 0x01
OFFSET = 0x0000
LENGTH = 0x37  # pyg7's READ_CHUNK_LENGTH

_seq = 0


def next_seq() -> int:
    global _seq
    _seq = (_seq + 1) % 256
    return _seq


def build_packet(cmd_byte: int, payload: bytes) -> bytes:
    if len(payload) > 60:
        raise ValueError("payload too long")
    pkt = bytearray(64)
    pkt[0] = 0x0f
    pkt[1] = 0x00
    pkt[2] = next_seq()
    pkt[3] = cmd_byte
    pkt[4:4 + len(payload)] = payload
    return bytes(pkt)


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def main() -> None:
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print(f"No device {VID:04x}:{PID:04x} found. Is it plugged in?")
        sys.exit(1)
    print(f"Found {VID:04x}:{PID:04x} at bus={dev.bus} address={dev.address}")

    iface0_detached = False
    iface2_detached = False
    try:
        # --- Claim interface 0 and warm up, exactly like a real g7ctl ---
        # --- session does before any read (pyg7's own settle()). ---
        if dev.is_kernel_driver_active(IFACE_0):
            print("Detaching kernel driver (xpad, presumably) from interface 0...")
            dev.detach_kernel_driver(IFACE_0)
            iface0_detached = True
        usb.util.claim_interface(dev, IFACE_0)
        print("Claimed interface 0.")

        print(f"Sending {SETTLE_HEARTBEATS} heartbeats over interface 0 "
              "(same warmup g7ctl always does before a read)...")
        for _ in range(SETTLE_HEARTBEATS):
            dev.write(EP_OUT_0, build_packet(CMD_HEARTBEAT, bytes([0xf2, 0x00])))
            time.sleep(SETTLE_INTERVAL)
        print("Warmup done.\n")

        # --- Claim interface 2, select alt-setting 1 for the bulk pair ---
        try:
            if dev.is_kernel_driver_active(IFACE_2):
                print("Detaching kernel driver from interface 2...")
                dev.detach_kernel_driver(IFACE_2)
                iface2_detached = True
        except usb.core.USBError:
            pass  # no driver bound is the expected/normal case here
        usb.util.claim_interface(dev, IFACE_2)
        dev.set_interface_altsetting(interface=IFACE_2, alternate_setting=IFACE_2_ALT)
        print(f"Claimed interface 2, selected alt-setting {IFACE_2_ALT} "
              "(the bulk endpoint pair from lsusb -v).\n")

        # --- Test A: just listen. Does the bulk IN endpoint push ---
        # --- anything unprompted, the way report 0x10 does on ---
        # --- interface 0? ---
        print("=== Test A: passive listen on EP 0x81 for 3 seconds ===")
        print("(does the bulk endpoint push anything on its own?)")
        saw_anything = False
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                data = dev.read(EP_IN_2, 64, timeout=200)
                saw_anything = True
                print(f"  <- {hexdump(bytes(data))}")
            except usb.core.USBError as e:
                if "timeout" not in str(e).lower():
                    print(f"  (error: {e})")
        if not saw_anything:
            print("  Nothing. Silent -- consistent with a request/response")
            print("  channel rather than a push stream (expected either way).")
        print()

        # --- Test B: send the exact request that already times out on ---
        # --- interface 0, this time over the bulk pair. ---
        print(f"=== Test B: CMD_READ over EP 0x01/0x81 "
              f"(category={CATEGORY:#04x}, offset={OFFSET:#06x}, length={LENGTH}) ===")
        print("(this exact request already times out on interface 0 -- does")
        print(" the bulk pair answer where the interrupt pair doesn't?)")
        req_payload = bytes([READ_SUBCOMMAND, CATEGORY,
                              (OFFSET >> 8) & 0xFF, OFFSET & 0xFF, LENGTH])
        pkt = build_packet(CMD_READ, req_payload)
        print(f"  -> {hexdump(pkt)}")
        try:
            dev.write(EP_OUT_2, pkt)
        except usb.core.USBError as e:
            print(f"  Write failed: {e}")
            print("  (informative on its own -- means this endpoint doesn't")
            print("   accept this kind of write at all, not just 'no reply')")
        else:
            echo = bytes([CMD_READ, CATEGORY, (OFFSET >> 8) & 0xFF,
                          OFFSET & 0xFF, LENGTH])
            got_match = False
            deadline = time.time() + READ_CHUNK_TIMEOUT
            while time.time() < deadline:
                remaining_ms = max(1, int((deadline - time.time()) * 1000))
                try:
                    report = bytes(dev.read(EP_IN_2, 64, timeout=remaining_ms))
                except usb.core.USBError as e:
                    if "timeout" in str(e).lower():
                        break
                    print(f"  read error: {e}")
                    break
                print(f"  <- {hexdump(report)}")
                if (len(report) >= 4 + len(echo) + LENGTH
                        and report[0] == REPORT_ID_READ_RESPONSE
                        and report[3] == READ_RESPONSE_MARKER
                        and report[4:4 + len(echo)] == echo):
                    got_match = True
                    payload = report[4 + len(echo):4 + len(echo) + LENGTH]
                    print("  MATCH -- this looks like a real read response.")
                    print(f"  Profile 1 config data: {hexdump(payload)}")
                    break
            if not got_match:
                print(f"  No matching response within {READ_CHUNK_TIMEOUT}s.")
                print("  (anything printed above that ISN'T a match is still")
                print("   worth reporting -- even garbage tells us something")
                print("   is listening on this endpoint at all.)")

    finally:
        print("\nCleaning up...")
        try:
            usb.util.release_interface(dev, IFACE_2)
        except Exception:
            pass
        if iface2_detached:
            try:
                dev.attach_kernel_driver(IFACE_2)
            except Exception:
                pass
        try:
            usb.util.release_interface(dev, IFACE_0)
        except Exception:
            pass
        if iface0_detached:
            try:
                dev.attach_kernel_driver(IFACE_0)
            except Exception:
                pass
        print("Done. Please paste everything this printed, including any")
        print("errors, back -- either result (a real answer or a clean")
        print("failure) settles the question this was built to test.")


if __name__ == "__main__":
    main()
