# GameSir G7 Pro vendor protocol -- quick reference

Confirmed wire format only, organized for lookup, and self-contained. The
reference implementation lives in [`pyg7/`](pyg7/).

Everything here was derived by observing USB traffic to and from a
controller we own. Where a value is confirmed, it was seen on the wire or
verified by a write/read-back round trip against real hardware; where it is
predicted from a confirmed pattern, it says so explicitly. Nothing below is
guesswork presented as fact.

**Applicability.** Every value in this document was confirmed against a
GameSir G7 Pro, the only hardware it has been exercised on.

The protocol may not be specific to that model. Three things point that way:
the vendor ID `0x3537` is GameSir's rather than the G7 Pro's; the
mode-switch handshake sends the ASCII string `"gamesirapp"`, naming the
Nexus application rather than a device; and GameSir's own listing for Nexus
says the app covers the **G7, Kaleid, and T7 / Tarantula Pro Xbox** families.
A single app driving several controller families over one vendor protocol is
the straightforward reading of that.

It remains an inference. Nothing here has been tried on any other device, and
the layers are worth separating if someone does: the framing (§"Packet
framing") and the handshake are the most likely to carry over, the category
prefixes and `SETTING_ID` values less certainly, and the product IDs in
"Device identities" below are G7 Pro-specific for sure. Treat everything else
as confirmed for the G7 Pro and unverified anywhere else.

## Device identities

| Identity | VID:PID | Role |
|---|---|---|
| Default runtime | `3537:100a` | "Xbox 360 Controller for Windows" -- standard XInput pad. Interface 1 also exposes a genuine HID keyboard+mouse device (`xpad` + `usbhid`) -- this is what actually emits remapped key/mouse events. **This is where the hardware idles on either transport**: wired, and also the dongle once nothing is heartbeating it (corrected 2026-08-01 -- see the dongle row). |
| Vendor/config | `3537:109b` | "GameSir-G7 Pro" -- config/telemetry protocol lives here. Interface 1 is isochronous audio in this mode, no HID keyboard/mouse. |
| Wireless dongle, vendor/config | `3537:109c` | The dongle's counterpart to `109b`, same physical unit and serial. **It is a mode, not the dongle's only identity** -- an idle dongle enumerates as `100a` with `xpad` bound, takes the same `"gamesirapp"` handshake, and re-enumerates here; it falls back to `100a` once heartbeats stop. So the dongle behaves exactly as the cable does, one PID apart. While a session is held the controller is **not playable**, same as `109b`: interface 0 shows `driver -> usbfs` in sysfs, `xpad` has nothing bound, and no `/dev/input/js*` node exists. Recovery is perceptibly (not measured) lazier over RF, consistent with the relaxed dongle timings in `pyg7/session.py`. See `pyg7/device.py:enter_vendor_mode()` and `find_writable_device()`. |
| Native GameSir identity | `3537:1022` | "GameSir-G7 Pro" (no manufacturer string, unlike `109b`). Reached by holding **Menu+Share** on the controller (documented in GameSir's manual as an XInput/native-identity toggle -- the same combo that clears a rare `CMD_READ` wedge). Two plain HID-class interfaces (`0x82`/`0x02` and `0x84`/`0x04`, no vendor-specific class-255 interface at all) -- **not the same protocol as `109b`/`109c`**: neither interface answers the standard `CMD_HEARTBEAT` payload or streams anything unprompted. Not reverse-engineered. `pyg7/device.py:find_native_identity()` recognizes this PID so a user stuck here gets a "hold Menu+Share" message instead of a generic "device not found." |

### A profile switch re-enumerates the controller, twice

Pressing an on-device profile combo (`M`+`Y`/`B`/`A`/`X`) makes the
controller drop off the USB bus and come back as **`109b`**, sit there for
roughly 45 seconds, then drop again and return to `100a`. Two full
disconnect/re-enumerate cycles per profile change, with no software
involved.

Measured 2026-08-08, wired, with nothing of this project running -- no
vendor session, no `g7ctlc`, only passive sysfs polling. Two consecutive
switches, from the kernel log:

```
00:22:15  disconnect
00:22:16  100a -> 109b   "GameSir-G7 Pro"
00:23:03  disconnect                        (~47s later, unprompted)
00:23:04  109b -> 100a   "Xbox 360 Controller for Windows"
```

Consequences worth knowing:

- **The HID keyboard/mouse interfaces do not exist while it sits at
  `109b`** (see the identity table above), and those are the only path by
  which a remapped key or mouse event reaches the host. Keyboard and mouse
  bindings are therefore dead for that window after every profile change.
  The gamepad half keeps working -- `Generic X-Box pad` and `js0` are
  present at `109b` too -- so this presents as "the remaps broke", not "the
  controller disconnected".
- **Anything holding a vendor session loses it.** The session dies because
  the device re-enumerated, not the other way round.
- **Software watching for gamepads sees a different device.** Steam, for
  one, shows the pad under a different name after a profile switch and
  drops a user-assigned custom name, because the product string, the PID
  and the interface set all change. This was originally reported as a Steam
  quirk; it is the firmware.

The ~45s dwell was consistent across both cycles measured, but two samples
is not a timing characterisation and no mechanism for it is established.

## Switching out of `100a`: `109b` wired, `109c` over the dongle

Send ASCII `"gamesirapp"` as 5 chunks of 2 characters, each an 8-byte OUT
report on endpoint `0x02`: `00 08 00 [c1] [c2] 00 00 00`, with an empty
flush packet `00 08 00 00 00 00 00 00` between each chunk. Device goes
silent ~1.3-1.5s after the last chunk, then re-enumerates as `109b`. No
prior handshake/negotiation steps are required (confirmed: this step
alone is sufficient). See `pyg7/device.py:enter_vendor_mode()`.

**The dongle takes the same handshake and re-enumerates the same way**, just
landing on `109c` instead of `109b`. Corrected 2026-08-01; this section
previously read "wired only" and claimed the dongle was already reachable
for vendor writes as soon as it was plugged in, needing no switch at all.

That claim came from only ever observing the dongle *after* a switch. It
stays in `109c` as long as something heartbeats it, and a previous session
usually left it there -- so `find_writable_device()` kept finding it ready
and nothing contradicted the assumption. Restarting `g7ctlc` exposed the
idle state, in one unambiguous sequence on a single USB port with no
wired controller attached:

```
xpad 3-8:1.0: xpad_try_sending_next_out_packet ...   <- xpad was bound to it
usb 3-8: USB disconnect, device number 21            <- at the handshake
usb 3-8: new full-speed USB device number 22         <- ~2s later
usb 3-8: New USB device found, idProduct=109c        <- same port, now vendor
```

The practical cost of the wrong assumption was in `enter_vendor_mode()`,
which waited for `109b` alone: every dongle connect from idle burned the
full timeout and logged a failure before the caller's next
`find_writable_device()` poll quietly succeeded. It now accepts either
landing PID and reports which one it got, since the caller needs that to
pick the session's timeouts. `find_writable_device()` still tries `109b`
first, then `109c`.

## Packet framing (once in `109b`)

64-byte interrupt OUT reports on endpoint `0x02`:

```
byte 0:   0x0f      fixed report ID
byte 1:   0x00      fixed
byte 2:   SEQ       increments per command, shared counter (heartbeat + writes)
byte 3:   CMD       0x02 = heartbeat, 0x3c = config write,
                    0x05 = config read (see "Reading current config"),
                    0x01 = device info query (see below)
bytes 4+: payload, zero-padded to 64 bytes
```

**A census of every command byte the corpus contains, with the emitting USB
device resolved, yields exactly these four.** `usbmon` captures a whole bus,
so any such census that does not pin `usb.device_address` will report other
hardware's traffic as controller commands -- an earlier one here did. The G7
uses four report IDs in total: `0x03` and `0x0f` OUT, `0x10` and `0x20` IN.

**Device info** (`CMD=0x01`): byte 4 selects *which* field is returned; the
answer arrives on `IN 0x10` as `3c [LEN] [...]`, the same length-prefixed
shape config reads use. Only two selectors appear in the corpus, because
these are the only two Nexus asks for:

| selector | response | reading |
|---|---|---|
| `0x09` | `3c 0a 30 00 32 00 30 00 39 00` | length 10, UTF-16LE `"0209"` -- a version string |
| `0x0b` | `3c 0c 01` | length 12, value `01` |

The selector space is unexplored -- 253 other values have never been tried.
This is the most promising known lead for a **model/variant identifier**:
Nexus renders the correct one of the five G7 Pro colourways, and nothing in
the USB descriptors distinguishes them (`product` is `"GameSir-G7 Pro"` for
all of them, and `bcdDevice` is a firmware revision), so it must be asking
the device something. Sweeping `CMD=0x01` selectors is cheap and read-only.

**Every write needs an active heartbeat session.** An isolated write with
no heartbeat before/after is silently discarded and the device reverts to
`100a` almost immediately. Wrap every write with heartbeats before *and*
after (`pyg7/session.py:VendorSession`, `~0.316s` cadence matches the
real app).

**Heartbeat** (`CMD=0x02`): payload `f2 00`, fixed.

## Config writes are addressed writes into a register file

Every `CMD=0x3c` payload in every capture we hold fits one shape:

```
03 [PROFILE] [PAGE] [OFFSET] [LEN] [LEN bytes of data]
        -> write LEN bytes at address (PAGE << 8) + OFFSET
```

Verified against all 248 `CMD_WRITE` payloads across the capture corpus,
zero contradictions. The check is one-sided and worth stating as such: a
data field that legitimately ends in `0x00` cannot be distinguished from
padding, so `LEN >= observed` is consistent and only `LEN < observed` would
falsify. Nothing falsified.

Three consequences, each of which this document previously described as a
separate mechanism:

- **The prefix's third byte is a 256-byte page selector**, not a category
  tag. That is why Sticks' storage base and Dock's are both `0x100`: they
  are the same page, not a coincidence.
- **The byte after `SETTING_ID` is a length**, not a format/type marker.
  Where this document says "marker" below, read "length". "Swap Left Stick
  and D-pad" had this right first (`0x37` = 55 bytes following); the same
  reading generalises to every other setting, including the deadzone
  "long form" writes whose marker was observed varying with how much
  trailing data came along -- that is a length changing, doing exactly what
  a length does.
- **`SETTING_ID` is a byte address.** A setting's storage offset is not
  derived from its ID by a formula; it *is* its ID, plus the page.

The `LEN` framing is what makes the "collateral write" hazards ordinary
rather than mysterious: a write of length 14 at `0x13F` covers `0x13F..0x14C`
because that is what it says, and the curve block at `0x144` happens to live
there. See "Sticks" (the live-suffix note) and "Two collateral-write
landmines" below.

## Category prefixes

All config writes use `CMD=0x3c`. The first bytes of the payload identify
the category (in register-file terms: `[PROFILE]` and the page):

| Category | Prefix | Notes |
|---|---|---|
| Buttons | `03 [PROFILE+LAYER] 00` | middle byte combines profile + layer -- see below |
| Sticks (Left) | `03 [PROFILE] 01` | except `resolution_bits`, which uses `03 [PROFILE] 00` |
| Sticks (Right) | same as Left | every `SETTING_ID` `+ 0x20` |
| Triggers (Left) | `03 [PROFILE] 00` | |
| Triggers (Right) | same as Left | every `SETTING_ID` `+ 0x1C` (**not** `0x20` -- each category has its own offset) |
| Vibration | `03 [PROFILE] 00` | same prefix as Triggers -- structurally indistinguishable except by `SETTING_ID` value range |
| Report Rate | `03 [PROFILE] 00` | same prefix as Triggers/Vibration |
| D-Pad Options | `03 [PROFILE] 00` | same prefix family; see "D-Pad Options" below |

`PROFILE` is a plain profile number, 1-4 -- every category is genuinely
profile-scoped, none of them fall back to "whichever profile is physically
active." See "Profile scoping" below for how this was confirmed.

## Buttons

`03 [PROFILE+LAYER] 00 [BUTTON_ID] 01 [KEYCODE]` (remap)
`03 [PROFILE+LAYER] 00 [BUTTON_ID] 00` (unbind)

**PROFILE+LAYER** -- one byte:
```
Default layer:  the profile number, 01-04
Shift layer:    always 05
```
**There is exactly one Shift layer, shared by all four profiles.** It is
device-global -- the same relationship dock settings have to profiles.
Five per-profile-ish config blobs exist in total: `01`-`04` and `05`.

Originally documented as `profile + (4 if Shift Layer else 0)`, which
predicts `06`/`07`/`08` for Profiles 2-4's Shift layers. Those categories do
not exist, and **the firmware does not reject them** -- it falls back to
Profile 1's Default-layer blob. A Shift write aimed at Profile 4 therefore
*modified Profile 1's Default layer*, and the matching read returned Profile
1's data, so a write-then-read-back test confirmed the write "worked" while
it was corrupting another profile.

Evidence for the global reading, gathered 2026-08-07:

- Reading all 256 category bytes returns exactly six distinct blobs:
  `01`-`04`, `05`, and `20` (dock). The other 250 return blob 1.
- A write to category `08` changed Profile 1's Default layer at offset
  `0x90` and nothing else on the device.
- Switching the active profile on the controller does not change what `05`
  returns -- byte-identical across a switch to Profile 2, the switch
  verified behaviourally rather than assumed.
- **Nexus reads the same six blobs and has never emitted `06`/`07`/`08`.**
  In a capture of a view-only profile-tab switch it reads the profile's own
  blob, then `05` in full, then dock -- fetching `05` while displaying
  Profile 4, which is the shared-resource pattern dock follows.
- Confirmed in Nexus's UI: a Shift binding set on Profile 1's tab appears on
  Profile 2's tab. Nexus shows a Shift section under every profile tab,
  which is why per-profile Shift layers are widely assumed.

### An empty slot means "factory default", not "unbound"

A button table slot whose record does not start with `01` -- and an LT/RT
keycode byte of `00` -- means the button has never been explicitly
configured, **not** that it does nothing. The firmware allocates a slot on
first write (see BUTTON_ID below); until then the button performs its
factory function.

Confirmed 2026-08-07 on Profile 2, whose table has only `a` and the four
paddles allocated and whose LT/RT bytes are `00`: every face button, D-pad
direction, shoulder, stick click and trigger behaved as a normal gamepad
input in Steam Input and KDE's controller settings. Nexus displays the
factory function for these slots, which is why its display disagrees with
a naive "no record = unbound" reading.

Note the consequence for `unbind`: unbinding a button returns its slot to
exactly the bytes of a never-configured slot (verified by writing a keycode
to a scratch profile, unbinding it, and diffing back to a byte-identical
baseline). The device cannot represent "explicitly dead" as distinct from
"never configured", so **unbind restores the factory function** rather than
disabling the button.

### The Shift layer is button bindings only

Blob `05` carries stick/trigger/vibration bytes, but only because all five
blobs share one 480-byte layout. Nexus never exposes them, and **nothing
can write them**, since those categories' prefixes carry a plain profile
number and no profile number addresses `05`. That last point is the one
that matters: it is why reading only the Default layer is correct.

Their values are *close* to an untouched profile's, not identical. Measured
2026-08-08 against a capture's own read responses, `05` differs from
Profile 2 in 43 bytes; 34 are button-table slots and 4 more are the LT/RT
keycodes (also bindings), leaving exactly five non-button differences --
the left stick's four curve control points. `05` holds the Standard preset
there; untouched profiles hold a different curve. Note also that profiles
2 and 3 differ from each other in 125 bytes, so "an untouched profile" is
not a single reference to compare against.

An earlier revision of this document claimed the opposite -- that the Shift
layer had its own curves, deadzones and vibration levels, "which is how
separate ADS and hipfire curves are built". That was wrong. It compared
`05` against Profile 1, the one *configured* profile, and read the
difference as layer-scoping; Profiles 2, 3 and 4 show the same values as
`05`. The difference was configured-versus-factory, not default-versus-shift.

**BUTTON_ID -- always send the 2-byte allocate form**, `[allocate_id,
0x02]`, never the compact 1-byte form. A button's "has this been
configured before" state isn't knowable without a device read, and a
compact-form write to a button the firmware currently considers
unconfigured is **silently discarded** (confirmed on RT and L5, both of
which reverted to needing allocate form on a later test despite an earlier
compact-eligible write). Allocate form is confirmed safe to
resend to an already-configured button too, so there's no reason to ever
use compact form. `pyg7/buttons.py:_to_allocate_form()` does this
conversion automatically; the table below lists compact-form values for
reference (allocate = compact - 1) since that's what the original captures
recorded.

**Why, mechanically -- there are not two forms.** Under the register-file
model above, `BUTTON_ID` is an address and `0x02`/`0x01` is a length. A
button's record is `01 [KEYCODE] 00 00 00 00 00` at a fixed offset, so:

```
allocate:  [record_start]     LEN=02   01 [keycode]   <- writes the marker AND the keycode
compact:   [record_start + 1] LEN=01      [keycode]   <- writes the keycode only
```

Compact form is "discarded" on an unconfigured button because it never
writes the `01` marker, so the record still does not begin with `01` and
every reader -- including the firmware -- still treats it as unconfigured.
`allocate_id == compact_id - 1` because the marker byte sits one address
before the keycode byte. Nothing is being allocated; there is no allocator,
and the "reset to unconfigured at some point, cause unknown" note in
`buttons.py` needs no special mechanism either -- anything that clears the
marker byte produces it.

**Every allocate ID in the table below is exactly its slot's offset in the
button table** (`0x42 + n*7`), checked for all 20 slots.

| Button | Compact | Allocate (what's actually sent) |
|---|---|---|
| Share | `AC` | `AB 02` |
| A | `7B` | `7A 02` |
| B | `82` | `81 02` |
| X | `89` | `88 02` |
| Y | `90` | `8F 02` |
| LB | `5F` | `5E 02` |
| RB | `66` | `65 02` |
| LT | `D4` | `D3 02` |
| RT | `F0` | `EF 02` |
| L3 (stick click) | `6D` | `6C 02` |
| R3 (stick click) | `74` | `73 02` |
| View | `9E` | `9D 02` |
| Menu | `A5` | `A4 02` |
| L4 | `B3` | `B2 02` |
| R4 | `C1` | `C0 02` |
| L5 | unconfirmed | `B9 02` |
| R5 | unconfirmed | `C7 02` |
| D-Pad Up | unconfirmed | `42 02` |
| D-Pad Down | unconfirmed | `49 02` |
| D-Pad Left | unconfirmed | `50 02` |
| D-Pad Right | unconfirmed | `57 02` |

Not remappable: Xbox/Guide (center) button, M (hardware profile-switch).

### Continuous Trigger (rapid-fire), byte 4 of a button's record

Nexus's Buttons tab exposes a per-button "Continuous Trigger" toggle --
rapid-fire. It is stored **inside the button's own 7-byte record**, at byte
4, and written like any other single byte:

```
03 [PROFILE] 00 [record_offset + 4] 01 [00|01]
```

Confirmed 2026-08-08 (`test61`) on two buttons: `A`'s record is at `0x7A`
and its toggle wrote `0x7E`; `Y`'s record is at `0x8F` and its toggle wrote
`0x93`. Same `+4` offset within each record, different addresses -- so this
is genuinely per-button, not one global flag.

**It is a plain boolean; there is no rate setting** (confirmed in Nexus's
own UI). So the value is `01`/`00` and nothing else.

**Every button binding has one** -- Nexus shows the checkbox on every
button, so byte 4 is a live field in all 20 records, not something only
certain buttons carry. A GUI can treat it as one checkbox per button row.

That leaves bytes 2, 3, 5 and 6 of each record still unknown. Byte 6 is
definitely in use -- Profile 3 carries `0x0A` there on every slot, including
unbound ones and the reserved Xbox slot -- and is **not** Continuous
Trigger, which was the guess before this capture.

### Keycodes

One flat byte-value space -- there's no separate "page" per tab; the
Keyboard/Mouse/Numpad/Controller tabs in the app UI are a display grouping
only.

**Native gamepad passthrough** (not a clean ascending run):

| Function | Byte | | Function | Byte |
|---|---|---|---|---|
| native LB | `05` | | native Menu | `0F` |
| native RB | `06` | | native Share/Capture | `10` |
| native L3 | `07` | | native L4 | `11` |
| native R3 | `08` | | native R4 | `12` |
| native A | `09` | | native LT | `13` |
| native B | `0A` | | native RT | `14` |
| native X | `0B` | | | |
| native Y | `0C` | | | |
| native Home (Xbox/Guide) | `0D` | | | |
| native View | `0E` | | | |

`L4`/`R4` (`11`/`12`) sit inside this otherwise-contiguous `05`-`14` block;
`L5`/`R5` (`1F`/`20`) do not -- a separate two-byte region, confirmed the
same way (see below), not a numbering mistake.

| Function | Byte |
|---|---|
| native L5 | `1F` |
| native R5 | `20` |

All five confirmed 2026-07-30, by a different method than the rest of this
table: written to a scratch profile's face buttons (X→`0D`, Y→`11`, B→`12`,
A→`1F`, Menu→`20`) with this tool, then read back via GameSir Nexus's own
picker labels ("Home", "L4", "R4", "L5", "R5") instead of inferring from
Nexus's UI directly. `Home` here is the native Xbox/Guide button's own
keycode -- it is still not a valid *remap target* in Nexus's own picker
(Xbox/Guide and M are confirmed non-remappable there), but the wire value
exists and is readable/writable via this raw protocol regardless.

Watching Linux `evdev`/`usbmon` alone could not have answered this: the
`xpad` driver only understands the standard XInput button set, so a paddle
bound to a paddle-specific native function produces no distinguishable
kernel-level event. Reading the values back through Nexus's own picker
labels was the only way to name them. See "New keycode region:
`0xE6`/`0xE7`" below for a third, unrelated gap in the codespace.

**Keyboard** -- one linear run with no gaps, `0x32` through `0x79`. Read it
in columns: `0x32`-`0x49`, then `0x4A`-`0x61`, then `0x62`-`0x79`.
**Bold** entries are directly hardware-confirmed; the rest are predicted
from the same linear run.

| Key | Byte | Key | Byte | Key | Byte |
|---|---|---|---|---|---|
| Esc | `32` | **- / _** | **`4A`** | J | `62` |
| F1 | `33` | = / + | `4B` | K | `63` |
| F2 | `34` | Backspace | `4C` | L | `64` |
| F3 | `35` | Tab | `4D` | ; / : | `65` |
| F4 | `36` | Q | `4E` | ' / " | `66` |
| F5 | `37` | **W** | **`4F`** | **Enter** | **`67`** |
| F6 | `38` | E | `50` | Shift (L) | `68` |
| F7 | `39` | R | `51` | Z | `69` |
| F8 | `3A` | T | `52` | X | `6A` |
| F9 | `3B` | Y | `53` | C | `6B` |
| F10 | `3C` | U | `54` | V | `6C` |
| **F11** | **`3D`** | I | `55` | B | `6D` |
| **F12** | **`3E`** | O | `56` | N | `6E` |
| \` / ~ | `3F` | P | `57` | M | `6F` |
| **1** | **`40`** | [ / { | `58` | , / < | `70` |
| **2** | **`41`** | ] / } | `59` | . / > | `71` |
| **3** | **`42`** | \\ / \| | `5A` | / / ? | `72` |
| **4** | **`43`** | Caps Lock | `5B` | Shift (R) | `73` |
| 5 | `44` | **A** | **`5C`** | **Ctrl (L)** | **`74`** |
| 6 | `45` | **S** | **`5D`** | **Win** | **`75`** |
| 7 | `46` | **D** | **`5E`** | Alt (L) | `76` |
| 8 | `47` | F | `5F` | **Space** | **`77`** |
| **9** | **`48`** | G | `60` | **Alt (R)** | **`78`** |
| 0 | `49` | H | `61` | Ctrl (R) | `79` |

17 of the 72 entries were confirmed directly, spread across every row of
the layout (function row, number row, QWERTY row, home row, bottom row, and
modifiers). All 17 landed exactly where the linear run predicted, with zero
deviations, which is why the remaining 55 are considered high-confidence
rather than speculative -- but they have not been individually tested.

**Numpad** (fully mapped, no gaps): `/`=`85`, `*`=`86`, `-`=`87`, `+`=`88`,
`.`=`89`, `Enter`=`8A`, then digits `Numpad_n = 0x8B + n` (confirmed at
n=0,1,7,9; 2-6,8 predicted from the same confirmed linear run).

**Mouse** (fully mapped, no gaps): Left Click `C8`, Middle Click `C9`,
Right Click `CA`, Mouse Button 5 `CB`, Mouse Button 4 `CC`, Scroll Up `CD`,
Scroll Down `CE` -- a contiguous run, all confirmed. Mouse *movement* is
not a target in this table at all -- it's Sticks' "Simulate the Mouse"
output mode instead (`SETTING_ID=0x55` value `04`).

### New keycode region: `0xE6`/`0xE7`

Not part of any of the four blocks above -- a separate, previously-unseen
region found via the Controller-native picker's microphone icon and a
bidirectional swap-arrows icon (bottom row of that picker), which write
`E6` and `E7` respectively. Wire values are confirmed via live capture;
the exact function each represents is inferred from the icon shape alone,
not from testing the resulting device behavior. Stored in
`pyg7/buttons.py`'s `KNOWN_KEYCODES` as `mic_mute` (`0xE6`,
tentative name) and `unknown_swap_0xe7` (`0xE7`, name deliberately not
guessed). Likely a "system/media function" region distinct from
native-gamepad, Keyboard, Numpad, and Mouse -- not otherwise explored.

## D-Pad Options

Two toggles on Nexus's Buttons tab, below the button diagram -- not button
remaps, but grouped with Buttons since that's where they live in the UI.
Same `03 [PROFILE] 00` prefix as Triggers/Vibration/Report Rate.

| Setting | `SETTING_ID` | Payload after prefix | Notes |
|---|---|---|---|
| D-Pad Diagonal Lock | `0x2D` | `[id] 01 [0/1]` | Simple boolean, fully implemented |
| Swap Left Stick and D-pad | `0x2B` | `[id] 37 [val] [val] [53-byte live suffix]` | Long form -- see below |

**Swap Left Stick and D-pad**, unlike every other setting on this page, is
not `[SETTING_ID] [marker] [value]`: the byte after `SETTING_ID` is a
**length**, not a format marker -- `0x37` (55) is exactly how many bytes
follow it (`4` header `+ 3` prefix `+ 1 SETTING_ID + 1` length byte `+ 55 =
64`, one full packet). Of those 55 bytes, only the first two matter:
`val` is written identically to both `0x2B` and `0x2C` (both confirmed
`0x00`->`0x01` in the one captured toggle -- OFF is inferred from the same
boolean convention every other flag here uses, not independently captured).
The trailing 53 bytes are collateral storage this write's payload happens to
span (D-Pad Diagonal Lock's own byte at `0x2D` sits inside it) -- same
"long-form write spans registers it doesn't conceptually own" shape as
Sticks/Triggers Deadzone, fixed the same way: read the live 53 bytes via
`VendorSession.read_live_suffix()` immediately before building the payload,
never a stored constant. Implemented 2026-07-28 (`pyg7/dpad_options.py`
`set_swap_stick_dpad()`); **hardware-verified 2026-07-29** -- a full-blob
diff of a real ON then OFF write on the physical controller showed exactly
the two intended bytes changing each time, with the OFF-state blob coming
back byte-identical to the pre-write baseline.

## Dock Settings

Genuinely global/device-wide -- **not** profile-scoped, unlike everything
else in this document. Found in Nexus's top-level "Settings" section, not
a per-category tab. Own fixed prefix, `03 20 01` (middle byte does not
vary with profile).

| Setting | `SETTING_ID` | Payload after prefix | Values |
|---|---|---|---|
| LED Brightness | `0xF9` | `[id] 01 [percent]` | `00`/`19`/`32`/`4B`/`64` (0/25/50/75/100, plain percentage) |
| Auto On/Off | `0xF6` | `[id] 01 [0/1]` | boolean |

Reading: `CMD_READ` category `0x20` directly (not `profile_layer_byte()`),
a separate blob (>480 bytes) from the 4 per-profile ones. Storage offset =
`SETTING_ID + 0x100` (same base Sticks' `03 [profile] 01` prefix uses) --
confirmed via read-diff.

## Sticks

`SETTING_ID` below is for **Left Stick**; add `0x20` for Right Stick
(confirmed on 2 settings, treated as a general rule).

| Setting | `SETTING_ID` | Payload after prefix | Notes |
|---|---|---|---|
| Trajectory | `0x3D` | `[id] 01 [00=Circle\|01=Raw]` | |
| Curve preset | `0x44` | `curve_preset_payload()` -- see below | |
| Deadzone Initial | `0x3F` | long form, **suffix must be read live, not hardcoded -- see note below** | |
| Deadzone Max | `0x40` | same note | |
| Anti-Deadzone Initial | `0x41` | same note | |
| Anti-Deadzone Max | `0x42` | same note | |
| Resolution/Bit | `0x32` | `[id] 01 [12-bits]`, uses prefix `03 [PROFILE] 00` (not `03 [PROFILE] 01`) | 8-12 bits |
| Output mode | `0x55` | `[id] 01 [01=L-stick\|02=R-stick\|03=Directional\|04=Mouse]` | |
| Invert X | `0x51` | `[id] 01 [00\|01]` | |
| Invert Y | `0x52` | `[id] 01 [00\|01]` | |
| Sensitivity | `0x53` | `[id] 01 [0-100]` | |
| DPI (Mouse mode only) | `0x54` | `[id] 01 [0-100]` | |
| Overlap Area (Directional mode only) | `0x56` | `[id] 01 [0-100]` | |
| Direction Bindings (Directional mode only) | `0x57` | `[id] 05 [up][down][left][right][ring]`, bulk write, 5 keycode bytes in one command | |

**Deadzone/anti-deadzone: suffix must be read live, not hardcoded.** These
"long form" writes are `[SETTING_ID] [marker] [value] [suffix]`, where
`suffix` (~11-20 bytes depending on setting) lands in the device's own
register file starting right at `storage_offset + 1` (see "Sticks/Triggers/
Vibration storage offsets" below) -- a span that **overlaps other settings'
own storage** (Curve preset data on both categories; this side's own LT/RT
keycode on Triggers, see below). A fixed/hardcoded suffix silently corrupts
whatever else lives in that span with stale data from whenever the suffix
was captured. The fix: before building the payload, `read_chunk()` the live
current bytes at that exact offset/length and use those as the suffix --
this replays whatever's *actually* there unchanged, regardless of what it
encodes. Implemented as `sticks.py`/`triggers.py`'s `_live_suffix()`,
hardware-confirmed clean 2026-07-28.
`set_value()` takes a `profile: int = 1` parameter so the live read targets
the right profile+layer category byte.

## Triggers

`SETTING_ID` below is for **Left Trigger**; add `0x1C` for Right Trigger
(a *different* offset than Sticks' `0x20` -- confirmed each category has
its own constant, not universal).

| Setting | `SETTING_ID` | Payload after prefix |
|---|---|---|
| Hair Trigger Mode | `0xD8` | `[id] 01 [00=Off\|81=Adaptive\|82=Fixed]` |
| Deadzone Initial | `0xCF` | long form -- **same live-suffix note as Sticks** |
| Deadzone Max | `0xD0` | same note |
| Anti-Deadzone Initial | `0xD1` | same note |
| Anti-Deadzone Max | `0xD2` | same note |
| Curve preset | `0xDC` | `curve_preset_payload()` -- byte-for-byte identical shape data to Sticks' curve |

## Vibration

Same prefix as Triggers (`03 [PROFILE] 00`). No Left/Right offset needed --
Left/Right are already distinct `SETTING_ID`s below.

| Setting | `SETTING_ID` | Payload after prefix |
|---|---|---|
| Left Grip level | `0x20` | `[id] 01 [0-100]` |
| Right Grip level | `0x21` | `[id] 01 [0-100]` |
| Left Trigger level | `0x22` | `[id] 01 [0-100]` |
| Right Trigger level | `0x23` | `[id] 01 [0-100]` |
| Left Trigger Force+Sync flags | `0x24` | `[id] 01 [bit0=Force, bit1=Sync]`, one byte, not two settings |
| Right Trigger Force+Sync flags | `0x25` | same bit layout |

**Nexus's own sliders offer 5 positions, not 101.** Every vibration-level
write in the capture corpus carries `00`, `19`, `32`, `4B` or `64` --
0/25/50/75/100 -- and nothing else. The wire encoding is still a plain
percent byte (same arrangement as Dock LED Brightness), so this is a UI
restriction rather than a protocol one.

**Whether the firmware honours an off-grid value is untested.** `pyg7` and
the GUI accept the full 0-100 range, so a user can ask for 37 -- a value
Nexus can never produce. Nothing establishes whether the device stores 37,
snaps it to a step, or discards the write, and no capture can answer it
because Nexus never sends one. A write-then-read round trip would settle
whether it is *stored*; whether the motor actually varies at that
granularity is a separate question and not answerable from the wire at all.

## Report Rate

Same prefix as Triggers/Vibration (`03 [PROFILE] 00`). No Left/Right (but
genuinely profile-scoped, same as everything else -- see "Profile
scoping").

| Setting | `SETTING_ID` | Payload after prefix | Values |
|---|---|---|---|
| Report/polling rate | `0x30` | `[id] 01 [VALUE]` | `00`=250Hz, `01`=500Hz, `02`=1000Hz |

Note: the real Nexus app disables native trigger vibration when this is
set to 1000Hz (observed in the Nexus app's own UI, not independently
verified at the protocol level) -- likely a genuine bandwidth constraint, not a bug.

## Curve payload (shared: Sticks `0x44`, Triggers `0xDC`)

```
Custom (mode-select only):  [SETTING_ID] 01 03 00
Standard/Concave/S-Curve:   [SETTING_ID] 0A [preset_index] [9 bytes shape data]
```
`preset_index`: Standard=`00`, Concave=`01`, S-Curve=`02`. Shape data is
fixed per preset (see `pyg7/curves.py`), identical across Sticks and
Triggers and across Left/Right -- only the `SETTING_ID` differs. Note `0A`
is the length of what follows (index + 9 bytes = 10), not a format marker.

### A curve is five handles: two endpoints plus three interior points

The editor in Nexus shows five draggable dots. They are not five entries in
one array -- the two endpoints live in the Deadzone/Anti-Deadzone registers
and only the middle three live in the curve block:

```
0x13F  bottom endpoint X   (= deadzone_initial)     0-100
0x140  top    endpoint X   (= deadzone_max)         0-100
0x141  bottom endpoint Y   (= anti_deadzone_initial) 0-100
0x142  top    endpoint Y   (= anti_deadzone_max)     0-100
...
0x144  preset index (3 = Custom)
0x145  scale, always 0x64
0x146  00 00   fixed origin corner -- never written by any drag
0x148  P1 (x, y)   interior, draggable
0x14A  P2 (x, y)   interior, draggable
0x14C  P3 (x, y)   interior, draggable
0x14E  ff ff   fixed max corner -- never written by any drag
```

(Left stick shown; add `0x20` for the right stick. Triggers use the same
layout from `0xDC`, `+0x1C` for the right side.)

**The "Custom curve" is a second view onto controls that already existed.**
The Deadzone slider's two handles are the endpoints' X coordinates and the
Anti-Deadzone slider's two handles are their Y coordinates; the curve editor
draws those as movable 2D points and adds the three interior ones. That is
also what Anti-Deadzone *is*, geometrically: the Y of the curve's endpoints,
which is why raising it lifts output near centre.

Confirmed 2026-08-08 by dragging all five handles bottom-to-top and reading
the writes (`test58`): the endpoints emitted long-form writes at `0x3F` and
`0x40`, the interior three emitted 2-byte writes at `0x48`, `0x4A`, `0x4C`,
and the resulting slider values (deadzone 20/97, anti-deadzone 0/86) matched
the bytes exactly.

**Two corrections this replaces.** `00 00` and `ff ff` were read as a
control point and as an "unset fifth point" respectively; they are neither.
They are fixed frame corners, and no drag has ever written them. The earlier
claim that the `(255,255)` endpoint is "implicit" was also wrong -- the real
endpoints are explicit, just stored elsewhere.

#### Preset shape data

The three presets' interior points, from their `0x44` payloads:

| Preset | Interior points | Shape |
|---|---|---|
| Standard | (40,41) (128,128) (215,214) | on the diagonal -> identity |
| Concave | (94,23) (176,79) (232,161) | below the diagonal throughout |
| S-Curve | (40,76) (128,128) (215,178) | above, then on, then below |

**How Nexus draws a Custom curve: straight segments through the points.**
Observed 2026-08-08 by setting Concave (strongly non-collinear points) and
switching to Custom so the handles render. The line passes *through* every
control point with a visible kink at each -- not a spline pulled toward
them. Notably the same points shown under the *preset* are drawn smooth, so
Nexus renders presets and Custom differently.

That is a fact about **Nexus's rendering**, not about the firmware. Whether
the controller itself interpolates linearly between control points cannot
be answered from any capture -- the wire carries the points and nothing
about the shape between them. Settling it would mean feeding a known input
ramp and measuring the output, which no test here has done.

For a tool that edits Custom curves the distinction does not matter: the
control points written are exact either way, and a polyline matches what
Nexus shows in the same mode.

#### An unwritten block: the scale byte is the marker

A curve block that has never been written reads as all zeros -- **scale
`0x00` rather than `0x64`** -- and its three points as `(0,0)`. That is
"never configured", not "a curve at the origin", the same convention this
protocol uses for unconfigured button slots and LT/RT keycodes. Profiles 3
and 4 on the development controller are in this state while still carrying
valid deadzone values.

**Anything establishing a curve must write the whole 10-byte block**, not
just the points: `[SETTING_ID] 0A [index] [scale] [origin x2] [P1][P2][P3]`,
the same shape the presets use. A points-only write leaves scale at `0x00`,
so the points land correctly on the device and then read back as
unconfigured -- confirmed on hardware 2026-08-08 (Profile 4: index and all
three points stored, scale `0x00`, the decoder reporting no points).
Writing the full block sets scale and the round trip closes.

#### Editing points

Once a block is configured, a drag writes just the point moved -- 2 bytes
for `(x, y)`, or 1 byte to change `x` alone (both forms observed). All six
addresses below are capture-confirmed:

| Point | Left stick | Right stick | Left trigger | Right trigger |
|---|---|---|---|---|
| P1 | `0x48` | `0x68` | `0xE0` | `0xFC` |
| P2 | `0x4A` | `0x6A` | `0xE2` | `0xFE` |
| P3 | `0x4C` | `0x6C` | `0xE4` | `0x100` (see below) |

`0x48`/`0x4A`/`0x4C` confirmed in `test58`; `0x6A`, `0xE2` and `0xFE`
confirmed in `test60`, along with their preset registers `0x64`, `0xDC` and
`0xF8` -- so the `+0x20` (Sticks) and `+0x1C` (Triggers) side offsets hold
for curves. `P1`/`P3` on the right stick and left trigger are predicted from
those confirmations, not individually observed.

**The Right Trigger's third point crosses a page boundary**, and this is the
clearest demonstration in the whole protocol that the prefix's third byte is
a *page number* rather than a category tag. Its address is `0xF8 + 8 =
0x100`, past the end of the one-byte `SETTING_ID` field, so the page byte
increments and the offset wraps:

```
03 01 01 00 02 e4 82        confirmed on the wire, test62
   ^^ ^^ ^^
   |  |  +-- offset 0x00
   |  +----- page 1  (Triggers otherwise write page 0)
   +-------- profile
```

A *trigger* write therefore carries the same three prefix bytes a *stick*
write does. Under a "category prefix" reading that is inexplicable; under
the register-file model it is just an address that happened to carry.

#### The two scales are different coordinate systems, not two units

**There is no conversion factor between them.** Endpoints are a percentage
of the *full input axis*; interior points are a position *within the span
the endpoints define*, as a fraction of 255. Established 2026-08-08
(`test64` plus a screenshot):

- Halving `deadzone_max` from 95 to 50 left the interior points untouched
  -- (40,41) (128,128) (215,214) before and after. They are not rescaled
  when an endpoint moves.
- With deadzone 5/50 and anti-deadzone 0/100, Nexus draws the curve's slope
  from ~5% to ~50% of the graph width and over the *full* height. Absolute
  positioning would have put `P3` (215/255 = 84%) well past where the line
  actually ends.

To place a control point on a graph:

```
x_pct = dz_init  + (px / 255) * (dz_max  - dz_init)
y_pct = adz_init + (py / 255) * (adz_max - adz_init)
```

1. **Do not convert between the scales.** Four captures were spent looking
   for a `p * 255/100` factor that does not exist.
2. **Points are constrained monotonic by their neighbours.** Nexus refuses
   to drag an interior point past the next one (confirmed: a point pushed
   to the top-right clamped just under its upper neighbour). They are *not*
   fenced by the endpoints, though -- an interior point was dragged to
   `(3, 3)`, well below the bottom endpoint's X of 20.

Not implemented in `pyg7/`.

## The input stream on report `0x10` (including a full 6-axis IMU)

While a vendor session is open, the device pushes a continuous stream of its
own input state on report `0x10` -- the same report `CMD_READ` answers on,
distinguished by byte 4 (`0x05` = read response, `0xE0` = input frame).

**This is how Nexus lets you drive its UI with the controller** ("Direction
Control / A Confirm / B Back" in its footer). In vendor mode the HID gamepad
interface does not exist, so the app needs its own path to read inputs.

Decoded 2026-08-08 from a manual sweep (each input moved in turn, logged
read-only over one held session):

| Offset | Contents |
|---|---|
| 5-8 | stick axes, **processed** -- rest at exactly `0x80`, full range 0-255 |
| 9, 10 | button bitfields |
| 12, 13 | triggers, 0 at rest, `0xFF` at full |
| **17-22** | **gyroscope** x, y, z -- int16 little-endian signed |
| **23-28** | **accelerometer** x, y, z -- int16 little-endian signed |
| 32 | flag, 0 or 1 -- see "Battery level" below |
| **33** | **battery percentage**, 0-100 -- see "Battery level" below |
| 51-54 | stick axes, **raw** -- rest at 134/126/133/132, i.e. uncalibrated |
| 55-60 | buttons and triggers again, raw group |

The IMU identification is not a guess. All three gyro axes have a median of
**exactly 0** (angular rate is zero at rest), and the accelerometer's vector
magnitude stays near-constant at **~8446** while its components swing --
which is gravity. At 8192 LSB/g (a ±4g range) that reads **1.03 g**.

The two axis groups differ in exactly the way calibration predicts: the
first rests at a perfect `0x80` on all four axes, the second at 134/126/133/
132. Processed versus raw ADC.

Which bit of `0x09`/`0x0A` belongs to which button is not mapped -- the
sweep did not record button order reliably.

### The gamepad and this stream are mutually exclusive

Tempting idea, ruled out 2026-08-08: the HID interface at `100a` *declares*
this protocol in its report descriptor --

```
06 f0 ff  Usage Page (Vendor-Defined 0xFFF0)
  85 10     Report ID 0x10, 63-byte INPUT
  85 12     Report ID 0x12, 63-byte INPUT
  85 0f     Report ID 0x0F, 63-byte OUTPUT
```

-- which suggests config access via `hidraw` on interface 1 while `xpad`
keeps interface 0 and the pad stays playable. **It does not work.** Writing
heartbeats and a `CMD_READ` request to report `0x0F` on `/dev/hidraw*` at
`100a` succeeds at the OS level and produces **no response of any kind**;
nothing streams there unprompted either. The firmware declares the reports
but only services them in vendor mode -- where interface 1 is isochronous
audio and the HID interface does not exist at all.

So there is no arrangement in which configuration and a working gamepad
coexist. That is a property of the firmware, and the "not usable for playing
while connected" limitation is unavoidable rather than a design choice here.

**GameSir Nexus behaves identically** -- it takes the device over completely
for the duration, on Windows, with the vendor's own software. That is the
strongest available evidence that this is the hardware's design and not a
shortcoming of this project's approach: if a workaround existed, the app
written by the people who made the firmware would use it.

## Motion / gyro

Located 2026-08-08 (`test61`), layout known, individual settings not
decoded. Nothing in `pyg7/` touches it.

Nexus's Motion tab is **structurally a stick config**: X-Axis Output Mode,
Activate Method, Activate Button, Output, Deadzone, Anti-Deadzone, Curve
Adjustment, X/Y Sensitivity Scale, and Invert toggles. It stores its
settings the same way, in a record with the same shape as a stick's, at
**stick offset + `0x61`**:

| Setting | Stick | Motion |
|---|---|---|
| deadzone initial | `0x13F` | `0x1A0` |
| anti-deadzone initial | `0x141` | `0x1A2` |
| first invert | `0x151` | `0x1B2` |
| sensitivity | `0x153` | `0x1B5` |

Everything from the inverts onward shifts by one extra byte because motion
has **three** invert toggles (Roll, Yaw, Y) where a stick has two (X, Y).

Motion edits wrote `0x19C`-`0x1B7` (page 1, prefix `03 [PROFILE] 01`),
which is exactly the region previously catalogued as "a stick-shaped block
nothing ever writes". It is not unwritten; it is the motion config.

**There are two such blocks**, at roughly `0x19D` and `0x1BF`, byte-identical
to each other in a factory profile. Nexus's Motion tab has two sub-tabs,
**Aim** and **Tilt**, so one block per sub-tab is the obvious reading --
but only one was exercised in `test61`, so which block is which, and
whether Tilt really owns the second, is **not confirmed**.

## The `CMD_READ` wedge, and what it costs

A known firmware fault: `CMD_READ` can stop answering entirely -- reads time
out with no response while heartbeats and writes keep working normally.
Triggered by rapid, repeated vendor-mode cycling. No software recovery
works: not a host reboot, not `dev.reset()`, not a cable replug. **Holding
Share+Menu on the controller clears it**, which is also the combo that
toggles the native identity.

### The Menu+Share identity flip clears remaps

**Holding Menu+Share clears every non-native button binding in the active
profile and in the shared Shift layer.** Measured 2026-08-09 with every
field on the device set to a distinctive non-default value first, so a
reset could not hide as "defaults written over defaults":

| Category | Bytes changed |
|---|---|
| Active profile | 12 -- `A` (F12), `Share` (F10), all four paddles |
| Shift layer | 6 -- `A`, `Y`, `Share` |
| The other three profiles | **0** |
| Dock (device-wide) | **0** |
| Sticks / triggers / vibration / curves | **0**, even in the active profile |

The discriminator is clean: in the same profile, `A` bound to `F12` was
cleared while `Y` bound to `native_y` survived. **Native passthrough
bindings are untouched; anything mapping to a keyboard or mouse key is
wiped.** That fits what the two share -- non-native bindings only exist via
the HID keyboard/mouse interfaces, which the identity toggle reinitialises.

Confirmed as the *active* profile rather than Profile 1 specifically by
switching the active profile with `M`+`B` and repeating: the damage moved
to Profile 2 and Profile 1 was untouched.

This matters because **Menu+Share is also the only reliable way to clear a
wedge**. Anyone recovering from one pays for it in remaps.

### What a wedge itself does to config is unmeasured

Every wedge observation is confounded: reading config after a wedge
requires clearing the wedge, and the only reliable clear is the identity
flip. The pinhole reset would have isolated it, but it does not clear
wedges (below). So "the wedge resets bindings" is **not** established --
what is established is that the recovery does.

Weak evidence either way: a wedge followed by Menu+Share changed exactly
the same 18 bytes as Menu+Share alone. That is consistent with the wedge
doing nothing, and equally consistent with both triggering one shared
mechanism.

### At least three distinct failure states

The project treated "the wedge" as one phenomenon. Deliberately inducing it
several times on 2026-08-09 produced three:

| State | Vibration | USB | Cleared by |
|---|---|---|---|
| Read wedge | one long pulse | stuck at `109b`, claimable, heartbeats fine | Menu+Share |
| Hard lock | none | off the bus entirely, LED lit, power button dead | pinhole reset |
| Silent wedge | none | at `109b`, claimable | Menu+Share |

The **vibration pulse is not a general wedge indicator** -- it accompanied
four of six failures, all of them the rapid-cycling kind. Its absence does
not mean the device is healthy.

**The pinhole reset does not clear a read wedge.** The manual documents it
for "unable to power on or off properly", and it does fix the hard lock,
but a wedge survived a forced power-off, a transport change and a replug
onto a different USB port.

One recovery sequence worth knowing, from the hard lock: the controller
came back up in 2.4GHz mode despite being cabled, refused to acknowledge
the wired connection at all, and only accepted wired again after being
allowed to connect through the dongle first.

Practical consequence for anything built on this protocol: **pace
vendor-mode transitions** (5-10s between sessions, one long session rather
than several short ones), and treat an export/snapshot before heavy write
work as cheap insurance.

## Resetting a page to factory defaults

Nexus's reset button (top-right of its toolbar) is **page-scoped**, not
device-wide -- pressing it on the Triggers tab reset both triggers and
nothing else. Captured 2026-08-08 (`test64`), it is a **single 51-byte
write** covering `0xCF`-`0x101`, i.e. the whole Triggers region for both
sides at once:

```
03 01 00 cf 33
  05 5f 00 64 01 13 00 00 00 00 0a 5a 01 00 64 00 00 39 40 80 80 c6 bf
  ff ff 00 00 01
  05 5f 00 64 01 14 00 00 00 00 0a 5a 01 00 64 00 00 39 40 80 80 c6 bf
  ^-- left trigger --^                 ^-- right, identical but for the
                                           keycode byte 0x13 -> 0x14
```

So the **application holds the defaults**, not the firmware -- a reset is an
ordinary bulk write of known bytes, with no dedicated opcode. That makes
"restore factory settings" reproducible offline. Trigger factory values,
read straight out of that payload:

| Setting | Default |
|---|---|
| Deadzone initial / max | 5 / 95 |
| Anti-Deadzone initial / max | 0 / 100 |
| Curve preset | Standard (`0x00`), scale `0x64` |
| Curve interior points | (57,64) (128,128) (198,191) |

Note those interior points are **not** the Standard preset's own
((40,41) (128,128) (215,214)) -- the factory trigger curve and the
Standard preset are different curves that both read as preset index `0x00`.

Only the Triggers page has been captured this way; whether other pages
behave identically is untested.

## Reading current config

Distinct command/response pair from every write above -- see
`pyg7/session.py:read_chunk()` and `pyg7/buttons.py` for the reference
implementation.

Request, on the normal `0x0f` OUT channel:

```
0f 00 [SEQ] 05 04 [CATEGORY] [OFFSET_HI] [OFFSET_LO] [LENGTH]
```

`CATEGORY` = same `profile + (4 if shift)` byte Buttons writes use, with the
same five valid values (`01`-`04`, `05`) -- see "Buttons". **An unimplemented
category is not rejected: it returns Profile 1's Default-layer blob.** A
reader that trusts the echoed category byte gets plausible, wrong data, so
treat any category outside those five as unreadable rather than empty.
`OFFSET` = 16-bit big-endian offset into that category's config blob.
`LENGTH` = `0x37` (55) per chunk, `0x28` (40) for a region's final chunk
(480 bytes total per profile).

Response, on a **different report ID, `0x10`**. That report also carries a
continuous stream of controller input state -- **this is how Nexus lets you
drive its own UI with the controller** (its footer shows "Direction Control
/ A Confirm / B Back"). In vendor mode the HID gamepad interface does not
exist, so the app needs its own path to read buttons and sticks, and this
is it. Match responses by content, not just report ID:

```
10 00 [SEQ] 3c [CMD_READ] [CATEGORY] [OFFSET_HI] [OFFSET_LO] [LENGTH] [...DATA...]
```

Button-binding table lives at blob offset `0x42`, one fixed 7-byte record
per slot (`01 [KEYCODE] 00 00 00 00 00`; unbound/reserved slots are
all-zero):
`DPadUp,DPadDown,DPadLeft,DPadRight,LB,RB,L3,R3,A,B,X,Y,(reserved),View,Menu,Share,L4,L5,R4,R5`
in that exact order. Native D-pad keycodes: Up=`01`,Down=`02`,Left=`03`,Right=`04`
(same small enum as the Sticks "Direction bindings" bulk write).

**LT/RT are exceptions** -- not part of the uniform table, no `0x01`
marker, no padding: a single raw keycode byte at a fixed offset sitting
*inside* the Triggers category's own deadzone-constant-block data for
that side. `LT` = offset `0xD4` (byte 4 of the `5F 00 64 01 13 00 00 00
00 0A 5A 01 00 64 00 00` constant), `RT` = offset `0xF0` (same shape,
`...01 14...`). No confirmed unbound sentinel for these two.

Implemented: `pyg7/state.py:read_state()`, CLI `g7ctl read-state`.

### Sticks/Triggers/Vibration storage offsets

Confirmed 2026-07-27 via live write+read-diff on every setting (D-pad-style
technique). General formula: `storage_offset = SETTING_ID + BASE + side_offset`,
where `BASE` depends on which `CMD_WRITE` category prefix the setting uses
-- each prefix addresses its own region of the same 480-byte blob:

| Category | Prefix | `BASE` | `side_offset` |
|---|---|---|---|
| Vibration | `03 01 00` | `0x00` | n/a (Left/Right are separate `SETTING_ID`s) |
| Triggers | `03 01 00` | `0x00` | `0x1C` for Right |
| Sticks (all except `resolution_bits`) | `03 01 01` | `0x100` | `0x20` for Right |
| Sticks `resolution_bits` | `03 01 00` | `0x00` | `0x20` for Right |

A multi-byte setting (Curve's 6-byte shape data, `direction_bindings`' 5
keycode bytes) stores starting at that same offset. Curve only needs its
1-byte preset-index (`00`/`01`/`02`/`03`=Custom) to decode -- the trailing
shape bytes are redundant confirmation, not separately needed.

**Two collateral-write landmines found while mapping** (both live-confirmed):
(1) Deadzone/Anti-deadzone's long-form suffix bytes also stomp
the Curve preset's stored bytes, on both Sticks and Triggers -- reproduced
in the real GameSir Nexus app too, genuine firmware behavior. (2) Triggers'
deadzone/anti-deadzone suffixes are Left-side-captured and NOT side-shifted
-- writing them for the Right side lands LT's own keycode byte (`0x13`)
into RT's keycode slot. Both are why the suffix must be read live rather
than hardcoded (see the note above) -- reading itself is unaffected by
either.

Implemented: `pyg7/sticks.py`/`triggers.py`/`vibration.py`'s
`decode_settings()`, wired into `read_state()`.

## Profile scoping

Every category is confirmed genuinely profile-scoped -- a write can target
any of the 4 profiles deterministically, independent of which profile is
physically active on the controller (no M-button combo ever required from
software):

- **Buttons**: explicit per-write via the `PROFILE+LAYER` byte (see above).
  The *profile* axis is fully scoped across all 4; the *layer* axis is not,
  because only Profile 1 has a Shift layer at all. Targeting a Shift layer
  on Profiles 2-4 does not fail -- it writes into Profile 1's Default
  layer. See "Buttons".
- **Sticks/Triggers/Vibration/Report Rate**: explicit per-write via the
  prefix's middle byte, a plain profile number 1-4 (see "Category
  prefixes" above). An earlier single test wrongly suggested these
  categories carried no profile targeting at all -- confirmed via a live
  Nexus capture (an edit made on Profile 2's tab sent prefix `03 02 01`,
  not the `03 01 01` every prior test happened to use) plus a direct
  hardware test (writing with the middle byte set to a profile with no
  physical switch at all landed cleanly in that profile only).

`controller_slot` in a state JSON scopes every category the same way.

## Not implemented / out of scope

- Curve control-point editing -- **decoded, not implemented.** See "Curve
  payload" above for the block layout and per-point addresses; nothing in
  `pyg7/` writes them, and the interpolation used to render a curve between
  the points is not established.
- Motion/gyro: the register block is located and its layout is known (see
  "Motion / gyro" below), but the individual settings are not decoded and
  nothing in `pyg7/` reads or writes them.
- 4 of the 5 spare bytes in each button-table record. Byte 4 is Continuous
  Trigger (see "Buttons"); bytes 2, 3, 5 and 6 remain unknown, and byte 6
  is demonstrably in use -- one profile carries `0x0A` there on every slot,
  including unbound ones and the reserved Xbox slot.
- The `0xE6`/`0xE7` keycode region (found but not chased further -- see "New keycode region: `0xE6`/`0xE7`" above).
- The native GameSir identity's own protocol (`3537:1022`, see "Device identities" above) -- found 2026-07-30, not reverse-engineered. Detected only well enough to explain it to a user, not to talk to it.
- Bluetooth mode -- a genuinely separate identity/pairing path, not investigated at all on the Linux side yet.

### Battery level -- solved

The device reports charge in **byte 33 of the input stream** (report `0x10`,
byte 4 = `0xE0`), as a plain percentage, 0-100. It is two more mapped
offsets in the table under "The input stream on report `0x10`" above -- the
same frames that carry the sticks, buttons and IMU:

```
offset 32   flag, 0 or 1  (see caveat below)
offset 33   battery percentage, 0x00-0x64  (0-100 decimal)
```

**There is no battery query.** Nothing has to be asked for. The device
pushes these frames unprompted for as long as a vendor session is open,
which is why Nexus can show a charge level immediately, before it has read
any configuration. Reading battery costs no bus traffic beyond the
heartbeats already needed to hold the session.

**Evidence.** Across 212,917 input frames spanning the whole capture corpus,
byte 33 never exceeds `0x64` (100). It is independent of stick position --
`test64`'s 29,602 frames all have the sticks off-centre and byte 33 is
constant throughout. Three captures were taken with the percentage Nexus was
displaying recorded independently at capture time:

| capture | Nexus displayed | byte 33 |
|---|---|---|
| `test55_battery_status_98pct` | 98% | 98 |
| `test56_battery_status_98pct_confirm` | 98% | 98, drifting to 97 |
| `test57_battery_status_99pct_contradicts` | 99% | 99 |

The third is the important one: it is the capture that falsified the
*previous* battery theory. The decode above matches it exactly.

**Why this was missed for so long.** The earlier investigation studied a
different periodic request/response exchange, on the assumption that a
dedicated battery query must exist because Nexus displays a battery level.
That assumption was wrong twice over: there is no battery query, and the
value was already arriving in a stream that had been decoded for sticks and
IMU without anyone looking past offset 28. The prior version of this section
concluded "we may be reading the wrong exchange entirely," and that was
correct.

**Caveat, byte 32.** It reads 1 in every capture where charge is below 100
and 0 in every capture at exactly 100. That is consistent with a charging
flag *and* with a simple "not full" flag -- every sub-100 capture in the
corpus was taken while plugged in, so the two cannot be told apart from
existing data. Distinguishing them needs one capture on battery power while
discharging. Do not label it "charging" until that exists.

Nothing in `pyg7/` reads or exposes this yet.
