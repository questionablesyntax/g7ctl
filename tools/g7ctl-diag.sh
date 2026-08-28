#!/usr/bin/env bash
# g7ctl-diag.sh -- read-only USB diagnostic capture for GameSir controllers.
#
# Tier 1 only (ROADMAP item 46): a diagnostic capture, nothing more. This
# tool never writes to the device and never sends the vendor-mode
# handshake -- classifying which personality a controller is currently in
# only needs its USB descriptors, which are already there to read, no
# session required. If you're trying to test a code fix or capture a full
# protocol session, this script isn't the tool for that -- see the g7ctl
# repo's own README/CONTRIBUTING for those (a real step up in what's
# needed, not something this script tries to paper over).
#
# Meant to be run exactly like this, nothing else installed first:
#   curl -fsSL https://raw.githubusercontent.com/questionablesyntax/g7ctl/main/tools/g7ctl-diag.sh | bash
#
# Only real dependency is usbutils' `lsusb` -- not pyusb, not Python, not
# git. lsusb -v exposes real interface descriptors on most desktop Linux
# setups without root; this script tries without sudo first and only
# suggests it if a GameSir device's own interface descriptors come back
# incomplete for that specific device.
#
# Repo-tracked (not a scratchpad/DM'd copy) specifically so "which version
# of the diagnostic script is this person running" is never ambiguous --
# a real problem the v0.2.1 PID reports hit. Authored/hosted here with
# clean LF line endings for the same reason a Reddit-DM'd copy of an
# earlier version of this script once broke: a `curl`'d raw-GitHub-URL
# copy can't pick up stray CRLFs the way a pasted one can.

set -uo pipefail

VID="3537"

# --- lsusb availability -------------------------------------------------

if ! command -v lsusb >/dev/null 2>&1; then
    echo "lsusb not found -- it's part of the 'usbutils' package." >&2
    if command -v pacman >/dev/null 2>&1; then
        echo "Try: sudo pacman -S usbutils" >&2
    elif command -v apt >/dev/null 2>&1 || command -v apt-get >/dev/null 2>&1; then
        echo "Try: sudo apt install usbutils" >&2
    elif command -v dnf >/dev/null 2>&1; then
        echo "Try: sudo dnf install usbutils" >&2
    elif command -v zypper >/dev/null 2>&1; then
        echo "Try: sudo zypper install usbutils" >&2
    elif command -v rpm-ostree >/dev/null 2>&1; then
        # Bazzite and other rpm-ostree images -- confirmed real gap, not
        # hypothetical: hit during the ROADMAP item 46 diagnostic work.
        echo "This looks like an rpm-ostree image (Bazzite or similar)." >&2
        echo "Try: rpm-ostree install usbutils   (needs a reboot to take effect)" >&2
        echo "or: run this from a distrobox/toolbox container that has it." >&2
    else
        echo "Install it with your distro's package manager, then re-run this script." >&2
    fi
    exit 1
fi

# --- find every GameSir-VID device, any PID -----------------------------
# Deliberately not limited to PIDs this project already knows -- the whole
# point is surfacing a PID nobody's seen yet, not confirming known ones.

mapfile -t LINES < <(lsusb -d "${VID}:" 2>/dev/null || true)

if [ "${#LINES[@]}" -eq 0 ]; then
    echo "No device with USB vendor ID ${VID} (GameSir) found."
    echo "Make sure the controller is plugged in (wired) or its dongle is,"
    echo "and the controller itself is powered on if using the dongle."
    exit 0
fi

echo "# g7ctl diagnostic capture"
echo
echo "Found ${#LINES[@]} GameSir-VID device(s). Paste this whole block into"
echo "your bug report -- it's read-only, nothing was written to the device."
echo
echo "**This is one snapshot, not the full picture.** A USB device can only"
echo "present one identity at a time -- it physically can't be in vendor"
echo "mode, XInput, and its native GameSir identity all at once -- so a"
echo "single run only ever shows whichever one it's in right now. See"
echo "\"Getting the full picture\" at the end of this report for how to"
echo "capture the others in separate runs; even just this one is a real,"
echo "useful data point on its own, so send it either way."
echo

# --- known variant table -------------------------------------------------
# Mirrors pyg7/constants.py's VARIANT_NAMES -- kept in sync by hand, this
# file has no Python/pyg7 dependency to import it from. If this ever
# drifts, pyg7.constants.identify_variant() is the source of truth.
variant_name() {
    case "$1" in
        109b) echo "Shadow Ember" ;;
        1003) echo "White Trimode" ;;
        105d) echo "Zenless Zone Zero" ;;
        *) echo "" ;;
    esac
}

# --- classify one PID's interface 1 shape --------------------------------
# Mirrors pyg7.device.is_xinput_personality() exactly: collect
# bInterfaceClass across every alt setting of interface number 1: HID
# (class 3) present anywhere in that set means XInput personality;
# otherwise it's a vendor/config personality. Empty (can't read the
# descriptors) means "don't know", same as the Python version's own
# documented behavior for an unreadable device.
classify_iface1() {
    local verbose_output="$1"
    awk '
        /Interface Descriptor:/ { in_iface = 1; num = ""; class = ""; next }
        in_iface && /bInterfaceNumber/ { num = $2 }
        in_iface && /bInterfaceClass/ {
            class = $2
            if (num == "1") {
                if (class == "3") { print "hid" } else { print "other:" class }
            }
            in_iface = 0
        }
    ' <<< "$verbose_output"
}

# Turns classify_iface1()'s per-alt-setting lines into one of exactly
# three stable answers: xinput / vendor / unknown. Kept as its own
# function (not inlined in the main loop) specifically so it has
# something to be tested against directly -- this is where the real
# regression this tool's own history already produced once lives (a
# case/esac on classify_iface1()'s full, possibly multi-line output is
# order-dependent and silently wrong whenever the hid alt setting isn't
# first; caught by tests/test_g7ctl_diag.sh, not by eye).
classify_personality() {
    local verbose_output="$1"
    local shape
    shape=$(classify_iface1 "$verbose_output")
    if [ -z "$shape" ]; then
        echo "unknown"
    elif grep -q "^hid$" <<< "$shape"; then
        echo "xinput"
    else
        echo "vendor"
    fi
}

for line in "${LINES[@]}"; do
    # "Bus 003 Device 042: ID 3537:109b GameSir-G7 Pro"
    pid=$(sed -n "s/.*ID ${VID}:\([0-9a-fA-F]\{4\}\).*/\1/p" <<< "$line")
    if [ -z "$pid" ]; then
        continue
    fi

    verbose=$(lsusb -v -d "${VID}:${pid}" 2>/dev/null || true)
    sudo_hint=""
    if ! grep -q "Interface Descriptor:" <<< "$verbose"; then
        # Try again with sudo only if the plain read came back without
        # interface descriptors at all -- don't ask for sudo pre-emptively,
        # most setups don't need it (confirmed: works root-less on a
        # normal desktop Linux config during this tool's own development).
        # -n (non-interactive): a curl|bash pipeline has no TTY for sudo to
        # prompt on -- without -n this can hang forever instead of just
        # failing, confirmed directly while testing this script.
        if command -v sudo >/dev/null 2>&1; then
            verbose_sudo=$(sudo -n lsusb -v -d "${VID}:${pid}" 2>/dev/null || true)
            if grep -q "Interface Descriptor:" <<< "$verbose_sudo"; then
                verbose="$verbose_sudo"
                sudo_hint=" (needed sudo to read full descriptors)"
            fi
        fi
    fi

    bcddevice=$(sed -n 's/^[[:space:]]*bcdDevice[[:space:]]*//p' <<< "$verbose" | head -1)
    iproduct=$(sed -n 's/^[[:space:]]*iProduct[[:space:]]*[0-9]*[[:space:]]*//p' <<< "$verbose" | head -1)

    case "$(classify_personality "$verbose")" in
        xinput) personality="XInput (gamepad-ready)" ;;
        vendor) personality="vendor/config" ;;
        *) personality="unknown -- couldn't read interface 1's descriptors${sudo_hint:-, even with sudo}" ;;
    esac

    name=$(variant_name "$pid")
    if [ -n "$name" ]; then
        variant_line="$name (confirmed)"
    else
        variant_line="not yet confirmed by this project -- if you know which G7 Pro edition this is, that's exactly the report to file"
    fi

    echo "## ${line#* }"
    echo
    echo "| Field | Value |"
    echo "|---|---|"
    echo "| PID | \`${pid}\`${sudo_hint} |"
    echo "| iProduct | ${iproduct:-(unknown)} |"
    echo "| bcdDevice | ${bcddevice:-(unknown)} |"
    echo "| Interface 1 shape | ${personality} |"
    echo "| Known variant | ${variant_line} |"
    echo
done

echo "---"
echo
echo "Recent kernel log lines mentioning this bus (helps spot re-enumeration"
echo "churn -- if the controller disconnects/reconnects a lot right around"
echo "when something goes wrong, that's worth including):"
echo
echo '```'
dmesg 2>/dev/null | grep -iE "usb|gamesir|3537" | tail -40 || echo "(dmesg not readable without sudo -- try: sudo dmesg | grep -iE 'usb|gamesir|3537' | tail -40)"
echo '```'
echo
echo "## Getting the full picture"
echo
echo "This run only found the personality/personalities listed above. A"
echo "controller (or dongle) can be in exactly one identity at a time, so"
echo "capturing all four this project tracks (native / XInput / vendor /"
echo "dongle -- see VARIANT_PIDS.md) takes separate runs, one per physical"
echo "state. Each is optional and safe -- only ever a read, same as this"
echo "run -- but the more of these you can include, the more useful the"
echo "report:"
echo
echo "- **Unplug the controller, wait a few seconds, plug it back in, and"
echo "  re-run this script immediately.** Catches the idle/XInput state"
echo "  before anything switches it into vendor mode."
echo "- **Hold Menu+Share on the controller** (per GameSir's own manual),"
echo "  then re-run. Catches its native GameSir identity."
echo "- **If you have the 2.4GHz dongle**, unplug the wired cable, plug in"
echo "  the dongle instead with the controller powered on and paired, then"
echo "  re-run. Catches the dongle's own PID."
echo
echo "Paste the output from every run you're able to do, not just one."
