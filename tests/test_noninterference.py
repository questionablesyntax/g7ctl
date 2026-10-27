"""Unit tests for pyg7.noninterference -- the S0 safety net (wave 2 plan,
Track S). Snapshot/diff are pure read-and-compare logic, fully testable
off hardware; the restoration *procedure* S0 actually requires is
hardware-only by nature and lives outside pytest -- see
Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md's S0 status note.
"""
import pytest

from pyg7 import noninterference as ni
from pyg7.constants import DOCK_READ_CATEGORY, FULL_BLOB_LENGTH, READ_CHUNK_LENGTH
from pyg7.dock_settings import BLOB_LENGTH as DOCK_BLOB_LENGTH
from pyg7.session import SHIFT_CATEGORY


class _MultiCategoryFakeSession:
    """Serves distinct bytes per category.

    tests/fakes.py's shared FakeSession backs every read with one single
    `_blob`, which can't tell two categories apart -- fine for testing one
    category module in isolation, useless for S0, whose entire point is
    comparing six categories against each other. Kept local rather than
    extended into the shared fake to avoid changing behaviour every other
    test in this suite already depends on.
    """

    def __init__(self, blobs: dict[int, bytes]):
        self._blobs = blobs
        self.reads: list[tuple[int, int, int]] = []

    def read_chunk(self, category: int, offset: int, length: int, timeout: float = 2.0) -> bytes:
        self.reads.append((category, offset, length))
        blob = self._blobs[category]
        return blob[offset:offset + length].ljust(length, b"\x00")

    def read_blob(self, category: int, length: int, interval: float = 0.0) -> bytes:
        out = bytearray()
        offset = 0
        while offset < length:
            chunk_len = min(READ_CHUNK_LENGTH, length - offset)
            out.extend(self.read_chunk(category, offset, chunk_len))
            offset += chunk_len
        return bytes(out)

    def heartbeat(self) -> bytes:
        return b""


def _all_categories_blob(fill: int = 0) -> dict[int, bytes]:
    return {category: bytes([fill]) * length for category, length in ni.RAW_CATEGORIES.items()}


def test_raw_categories_matches_the_six_real_blobs():
    assert set(ni.RAW_CATEGORIES) == {1, 2, 3, 4, SHIFT_CATEGORY, DOCK_READ_CATEGORY}
    assert ni.RAW_CATEGORIES[1] == FULL_BLOB_LENGTH
    assert ni.RAW_CATEGORIES[DOCK_READ_CATEGORY] == DOCK_BLOB_LENGTH


def test_snapshot_reads_every_category_at_its_own_length():
    sess = _MultiCategoryFakeSession(_all_categories_blob(fill=0x11))
    snap = ni.snapshot(sess)
    assert set(snap) == set(ni.RAW_CATEGORIES)
    for category, length in ni.RAW_CATEGORIES.items():
        assert len(snap[category]) == length
        assert snap[category] == bytes([0x11]) * length


def test_diff_finds_nothing_when_nothing_changed():
    sess = _MultiCategoryFakeSession(_all_categories_blob(fill=0x22))
    before = ni.snapshot(sess)
    after = ni.snapshot(sess)
    assert ni.diff(before, after) == {}


def test_diff_finds_exactly_the_changed_bytes():
    before_blobs = _all_categories_blob(fill=0x00)
    before = ni.snapshot(_MultiCategoryFakeSession(before_blobs))

    after_blobs = {k: bytearray(v) for k, v in before_blobs.items()}
    after_blobs[2][10] = 0x7B
    after_blobs[SHIFT_CATEGORY][0] = 0x01
    after = ni.snapshot(_MultiCategoryFakeSession({k: bytes(v) for k, v in after_blobs.items()}))

    changes = ni.diff(before, after)
    assert set(changes) == {2, SHIFT_CATEGORY}
    assert changes[2] == [(10, 0x00, 0x7B)]
    assert changes[SHIFT_CATEGORY] == [(0, 0x00, 0x01)]


def test_diff_rejects_mismatched_lengths():
    before = {1: b"\x00" * FULL_BLOB_LENGTH}
    after = {1: b"\x00" * (FULL_BLOB_LENGTH - 1)}
    with pytest.raises(ValueError):
        ni.diff(before, after)


def test_format_diff_reports_no_change():
    assert ni.format_diff({}) == "no change"


def test_format_diff_renders_offsets_and_bytes_in_hex():
    out = ni.format_diff({1: [(0x10, 0x00, 0xFF)]})
    assert "0x10" in out
    assert "0x00" in out
    assert "0xff" in out


def test_save_then_load_snapshot_round_trips_exactly(tmp_path):
    sess = _MultiCategoryFakeSession(_all_categories_blob(fill=0x33))
    snap = ni.snapshot(sess)
    path = tmp_path / "snapshot.json"

    ni.save_snapshot(str(path), snap)
    loaded = ni.load_snapshot(str(path))

    assert loaded == snap


def test_a_loaded_snapshot_diffs_the_same_as_the_original(tmp_path):
    """The actual point: g7ctl noninterference-diff compares two FILES,
    not two live snapshots -- diff() must not care which."""
    before_blobs = _all_categories_blob(fill=0x00)
    before = ni.snapshot(_MultiCategoryFakeSession(before_blobs))

    after_blobs = {k: bytearray(v) for k, v in before_blobs.items()}
    after_blobs[SHIFT_CATEGORY][3] = 0x9A
    after = ni.snapshot(_MultiCategoryFakeSession({k: bytes(v) for k, v in after_blobs.items()}))

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    ni.save_snapshot(str(before_path), before)
    ni.save_snapshot(str(after_path), after)

    file_diff = ni.diff(ni.load_snapshot(str(before_path)), ni.load_snapshot(str(after_path)))

    assert file_diff == ni.diff(before, after)
    assert file_diff[SHIFT_CATEGORY] == [(3, 0x00, 0x9A)]
