#!/usr/bin/env bash
# Plain bash tests for tools/g7ctl-diag.sh -- no bats, no new dependency,
# same reasoning as the script itself: this project's test floor is
# `python3 -m unittest`/pytest already, and a shell-based diagnostic tool
# shouldn't need a second test framework installed just to be checked.
# Run: bash tests/test_g7ctl_diag.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../tools/g7ctl-diag.sh"

fail=0
assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" != "$actual" ]; then
        echo "FAIL: $desc"
        echo "  expected: [$expected]"
        echo "  actual:   [$actual]"
        fail=1
    else
        echo "ok: $desc"
    fi
}

# --- syntax ---------------------------------------------------------------
if bash -n "$SCRIPT"; then
    echo "ok: script parses (bash -n)"
else
    echo "FAIL: script has a syntax error"
    fail=1
fi

# --- pull the functions under test into this shell, without running the
# --- script's own top-level logic (which probes real USB hardware). Tests
# --- classify_personality(), not classify_iface1() directly -- that's the
# --- real regression-prone surface: this tool's own history already had a
# --- bug where the *caller* of classify_iface1()'s output was order-
# --- dependent even though classify_iface1() itself was correct, so a test
# --- that only checked classify_iface1() in isolation would have kept
# --- passing right through that regression. Caught during this tool's own
# --- development by deliberately reintroducing the bug and confirming
# --- these tests actually fail -- not assumed. -----------------------------
for fn in classify_iface1 classify_personality variant_name; do
    src=$(sed -n "/^${fn}() {/,/^}/p" "$SCRIPT")
    if [ -z "$src" ]; then
        echo "FAIL: could not extract ${fn}() from $SCRIPT"
        echo "      (its exact function-header text changed -- update this test's sed pattern)"
        exit 1
    fi
    eval "$src"
done

# --- variant_name() ---------------------------------------------------------
assert_eq "known PID 109b resolves to Shadow Ember" "Shadow Ember" "$(variant_name 109b)"
assert_eq "known PID 1003 resolves to White Trimode" "White Trimode" "$(variant_name 1003)"
assert_eq "known PID 105d resolves to Zenless Zone Zero" "Zenless Zone Zero" "$(variant_name 105d)"
assert_eq "unconfirmed PID resolves to empty, not a guess" "" "$(variant_name 9999)"

# --- classify_personality(): real XInput personality shape ------------------
xinput_fixture='Interface Descriptor:
      bInterfaceNumber        0
      bInterfaceClass         3 Human Interface Device
    Interface Descriptor:
      bInterfaceNumber        1
      bInterfaceClass         3 Human Interface Device'
assert_eq "XInput fixture classifies as xinput" "xinput" "$(classify_personality "$xinput_fixture")"

# --- classify_personality(): real vendor/config shape (this project's own
# --- actual hardware -- 255/Vendor Specific on both alt settings of
# --- interface 1, confirmed against a live device, not guessed) ------------
vendor_fixture='Interface Descriptor:
      bInterfaceNumber        0
      bInterfaceClass       255 Vendor Specific Class
    Interface Descriptor:
      bInterfaceNumber        1
      bAlternateSetting       0
      bInterfaceClass       255 Vendor Specific Class
    Interface Descriptor:
      bInterfaceNumber        1
      bAlternateSetting       1
      bInterfaceClass       255 Vendor Specific Class'
assert_eq "vendor fixture (class 255 on interface 1) classifies as vendor" "vendor" "$(classify_personality "$vendor_fixture")"

# --- classify_personality(): order independence -- HID as the SECOND alt
# --- setting, not the first. This is the exact case that exposed the real
# --- bug: a naive case/esac on classify_iface1()'s raw multi-line output
# --- matches by first line, not membership, and got this wrong. -----------
hid_second_fixture='Interface Descriptor:
      bInterfaceNumber        1
      bAlternateSetting       0
      bInterfaceClass       255 Vendor Specific Class
    Interface Descriptor:
      bInterfaceNumber        1
      bAlternateSetting       1
      bInterfaceClass         3 Human Interface Device'
assert_eq "hid found regardless of alt-setting order (membership, not first-match)" \
    "xinput" "$(classify_personality "$hid_second_fixture")"

# --- classify_personality(): unreadable descriptors (device gone/mid-
# --- enumeration, or lsusb -v needed sudo and didn't get it) ---------------
assert_eq "unreadable descriptors classify as unknown" \
    "unknown" "$(classify_personality "Couldn't open device, some information will be missing")"

# --- classify_personality(): interface 0's class must never leak into the
# --- interface-1-only answer ------------------------------------------------
iface0_hid_fixture='Interface Descriptor:
      bInterfaceNumber        0
      bInterfaceClass         3 Human Interface Device
    Interface Descriptor:
      bInterfaceNumber        1
      bInterfaceClass       255 Vendor Specific Class'
assert_eq "interface 0's class is ignored -- only interface 1 is checked" \
    "vendor" "$(classify_personality "$iface0_hid_fixture")"

echo
if [ "$fail" -eq 0 ]; then
    echo "All g7ctl-diag.sh tests passed."
else
    echo "Some g7ctl-diag.sh tests FAILED."
fi
exit "$fail"
