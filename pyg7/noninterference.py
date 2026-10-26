"""Raw, byte-exact snapshot and diff of every config category the device
holds -- the S0 safety net the GUI redesign's wave 2 plan requires before
any semantic/write-path change lands (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S, S0).

Deliberately dumb: `snapshot()` is `read_blob()` six times, `diff()` is a
byte-for-byte comparison. No decoding, so no category's "unidentified
bytes" (state.py's own term for bytes read_state()/write_state() don't
model) are silently dropped the way a JSON round-trip would drop them.

Restoration is **not** implemented here as a new raw writer. The plan is
explicit that S0 must prove restoration using *existing, proven* write
commands (remap/unbind/set_value/etc.), never a new one invented for the
occasion -- send_addressed() only handles a single setting's own
page-crossing split (see its docstring), not an arbitrary multi-page bulk
write, and nothing in this codebase has ever confirmed what the firmware
does with one. Writing and testing that primitive would be exactly the
kind of guess this project's own history warns against (see PROTOCOL.md's
many "confirmed on the wire" notes -- nothing here is). The actual
restoration proof is a hardware procedure, run and recorded by category
module, not a library function; see Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md's S0 status note for the run and its result.
"""
from __future__ import annotations

from .constants import DOCK_READ_CATEGORY, FULL_BLOB_LENGTH
from .dock_settings import BLOB_LENGTH as DOCK_BLOB_LENGTH
from .session import SHIFT_CATEGORY

# The six distinct blobs the firmware actually holds -- profile_layer_byte()'s
# own docstring, confirmed on the wire 2026-08-07: every other category byte
# 0x00-0xFF falls back to Profile 1's Default-layer blob, so reading any of
# those would just re-read category 1 under a different name.
RAW_CATEGORIES: dict[int, int] = {
    1: FULL_BLOB_LENGTH,
    2: FULL_BLOB_LENGTH,
    3: FULL_BLOB_LENGTH,
    4: FULL_BLOB_LENGTH,
    SHIFT_CATEGORY: FULL_BLOB_LENGTH,  # 0x05
    DOCK_READ_CATEGORY: DOCK_BLOB_LENGTH,  # 0x20
}


def snapshot(session, interval: float = 0.05) -> dict[int, bytes]:
    """Read every category's full raw blob, unmodified, undecoded."""
    return {
        category: session.read_blob(category, length, interval=interval)
        for category, length in RAW_CATEGORIES.items()
    }


def diff(before: dict[int, bytes], after: dict[int, bytes]) -> dict[int, list[tuple[int, int, int]]]:
    """Byte-level diff per category: `{category: [(offset, before, after), ...]}`.

    Only categories with at least one differing byte appear, so
    `not diff(a, b)` is the "nothing else moved" check both S0 and S7
    need. Raises if a category's two snapshots disagree on length --
    that means they weren't taken with the same `RAW_CATEGORIES`
    mapping, not that a byte changed.
    """
    changes: dict[int, list[tuple[int, int, int]]] = {}
    for category, before_blob in before.items():
        after_blob = after[category]
        if len(before_blob) != len(after_blob):
            raise ValueError(
                f"category {category:#04x}: snapshot length changed "
                f"({len(before_blob)} -> {len(after_blob)}); both snapshots "
                "must be taken against the same RAW_CATEGORIES lengths")
        cat_changes = [
            (offset, b, a)
            for offset, (b, a) in enumerate(zip(before_blob, after_blob))
            if b != a
        ]
        if cat_changes:
            changes[category] = cat_changes
    return changes


def format_diff(changes: dict[int, list[tuple[int, int, int]]]) -> str:
    """Human-readable rendering for a terminal or a run log."""
    if not changes:
        return "no change"
    lines = []
    for category, cat_changes in sorted(changes.items()):
        lines.append(f"category {category:#04x}: {len(cat_changes)} byte(s) differ")
        for offset, before_byte, after_byte in cat_changes:
            lines.append(f"  offset {offset:#04x}: {before_byte:#04x} -> {after_byte:#04x}")
    return "\n".join(lines)
