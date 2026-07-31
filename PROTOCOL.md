# GameSir G7 Pro vendor protocol -- quick reference

Confirmed wire format only, organized for lookup, and self-contained. The
reference implementation lives in [`pyg7/`](pyg7/).

Everything here was derived by observing USB traffic to and from a
controller we own. Where a value is confirmed, it was seen on the wire or
verified by a write/read-back round trip against real hardware; where it is
predicted from a confirmed pattern, it says so explicitly. Nothing below is
guesswork presented as fact.

## Device identities

| Identity | VID:PID | Role |
|---|---|---|
| Default runtime | `3537:100a` | "Xbox 360 Controller for Windows" -- standard XInput pad. Interface 1 also exposes a genuine HID keyboard+mouse device (`xpad` + `usbhid`) -- this is what actually emits remapped key/mouse events. |
| Vendor/config | `3537:109b` | "GameSir-G7 Pro" -- config/telemetry protocol lives here. Interface 1 is isochronous audio in this mode, no HID keyboard/mouse. |
| Wireless dongle | `3537:109c` | Same physical unit, same serial. Only one identity (no separate XInput PID -- can't re-enumerate over RF). Interface 0 accepts vendor writes directly, **no handshake needed**, while simultaneously working as a plain gamepad (`xpad` binds it). See `pyg7/device.py:find_writable_device()`. |
| Native GameSir identity | `3537:1022` | "GameSir-G7 Pro" (no manufacturer string, unlike `109b`). Reached by holding **Menu+Share** on the controller (documented in GameSir's manual as an XInput/native-identity toggle -- the same combo that clears a rare `CMD_READ` wedge). Two plain HID-class interfaces (`0x82`/`0x02` and `0x84`/`0x04`, no vendor-specific class-255 interface at all) -- **not the same protocol as `109b`/`109c`**: neither interface answers the standard `CMD_HEARTBEAT` payload or streams anything unprompted. Not reverse-engineered. `pyg7/device.py:find_native_identity()` recognizes this PID so a user stuck here gets a "hold Menu+Share" message instead of a generic "device not found." |

## Switching `100a` -> `109b` (wired only)

Send ASCII `"gamesirapp"` as 5 chunks of 2 characters, each an 8-byte OUT
report on endpoint `0x02`: `00 08 00 [c1] [c2] 00 00 00`, with an empty
flush packet `00 08 00 00 00 00 00 00` between each chunk. Device goes
silent ~1.3-1.5s after the last chunk, then re-enumerates as `109b`. No
prior handshake/negotiation steps are required (confirmed: this step
alone is sufficient). See `pyg7/device.py:enter_vendor_mode()`.

The wireless dongle (`109c`) needs none of this -- it's already reachable
for vendor writes as soon as it's plugged in and the controller is
powered on/paired to it. `find_writable_device()` tries `109b` first, then
falls back to `109c`.

## Packet framing (once in `109b`)

64-byte interrupt OUT reports on endpoint `0x02`:

```
byte 0:   0x0f      fixed report ID
byte 1:   0x00      fixed
byte 2:   SEQ       increments per command, shared counter (heartbeat + writes)
byte 3:   CMD       0x02 = heartbeat, 0x3c = config write,
                    0x05 = config read (see "Reading current config")
bytes 4+: payload, zero-padded to 64 bytes
```

**Every write needs an active heartbeat session.** An isolated write with
no heartbeat before/after is silently discarded and the device reverts to
`100a` almost immediately. Wrap every write with heartbeats before *and*
after (`pyg7/session.py:VendorSession`, `~0.316s` cadence matches the
real app).

**Heartbeat** (`CMD=0x02`): payload `f2 00`, fixed.

## Category prefixes

All config writes use `CMD=0x3c`. The first bytes of the payload identify
the category:

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

**PROFILE+LAYER** -- one byte, both axes combined:
```
byte = profile_number(1-4) + (4 if Shift Layer else 0)
```
Confirmed: 1+Default=`01`, 2+Default=`02`, 1+Shift=`05`. Formula predicts
the rest. This is the only category confirmed to carry a profile-targeting
byte at all (see "Profile scoping" below).

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

## Curve preset payload (shared: Sticks `0x44`, Triggers `0xDC`)

```
Custom (mode-select only):  [SETTING_ID] 01 03 00
Standard/Concave/S-Curve:   [SETTING_ID] 0A [preset_index] [9 bytes shape data]
```
`preset_index`: Standard=`00`, Concave=`01`, S-Curve=`02`. Shape data is
fixed per preset (see `pyg7/curves.py`), identical across Sticks and
Triggers and across Left/Right -- only the `SETTING_ID` differs. Actual
curve *point* editing (dragging points on Custom) uses an undecoded
`SETTING_ID=0x4A` write -- out of scope, not implemented.

## Reading current config

Distinct command/response pair from every write above -- see
`pyg7/session.py:read_chunk()` and `pyg7/buttons.py` for the reference
implementation.

Request, on the normal `0x0f` OUT channel:

```
0f 00 [SEQ] 05 04 [CATEGORY] [OFFSET_HI] [OFFSET_LO] [LENGTH]
```

`CATEGORY` = same `profile + (4 if shift)` byte Buttons writes use.
`OFFSET` = 16-bit big-endian offset into that category's config blob.
`LENGTH` = `0x37` (55) per chunk, `0x28` (40) for a region's final chunk
(480 bytes total per profile).

Response, on a **different report ID, `0x10`** (also carries unrelated
continuous analog telemetry -- match by content, not just report ID):

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

- Curve control-point editing (`0x4A`, undecoded).
- Motion/gyro tab.
- The `0xE6`/`0xE7` keycode region (found but not chased further -- see "New keycode region: `0xE6`/`0xE7`" above).
- The native GameSir identity's own protocol (`3537:1022`, see "Device identities" above) -- found 2026-07-30, not reverse-engineered. Detected only well enough to explain it to a user, not to talk to it.
- Bluetooth mode -- a genuinely separate identity/pairing path, not investigated at all on the Linux side yet.

### Battery level -- investigated, not solved

Worth stating explicitly, since it's an obvious thing to want. There *is* a
real periodic request/response exchange that the Nexus app performs and that
the device answers, and a byte in that response was initially a promising
candidate for charge level. It doesn't hold up: across readings taken at
known-different charge states, the value did not track the charge the app
itself was displaying, and at one point moved in the direction opposite to
the actual state. Whatever that byte encodes, it is not a straightforward
battery percentage, and no other field in the exchange decoded as one
either.

So: the transport is understood, the semantics are not. Anyone picking this
up should treat the candidate byte as unidentified rather than as a
percentage that needs scaling. Nothing in `pyg7/` reads or exposes it.
