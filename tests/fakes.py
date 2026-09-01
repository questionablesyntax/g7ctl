"""A stand-in for VendorSession so payload builders can be tested off-hardware.

Every set_value()/remap() in pyg7 ends the same way -- it builds a
payload and hands it to session.send_raw(). Swapping in a recorder there
makes the entire write side of the protocol testable with no controller
attached, which is the only reason these tests can run in CI.
"""


class FakeSession:
    """Records what would have been sent; serves canned bytes for reads.

    `blob` backs read_chunk()/read_live_suffix() so the Deadzone/Anti-deadzone
    paths -- the ones that read the live overlapping span before writing --
    can be exercised too.
    """

    def __init__(self, blob: bytes = b""):
        self.sent: list[tuple[int, bytes]] = []
        self.heartbeats = 0
        self.reads: list[tuple[int, int, int]] = []
        self._blob = blob

    # --- the VendorSession surface the category modules actually use ---

    def send_raw(self, cmd_byte: int, payload: bytes) -> bytes:
        self.sent.append((cmd_byte, bytes(payload)))
        pkt = bytearray(64)
        pkt[0] = 0x0F
        pkt[3] = cmd_byte
        pkt[4:4 + len(payload)] = payload
        return bytes(pkt)

    def heartbeat(self) -> bytes:
        self.heartbeats += 1
        return b""

    def send_addressed(self, prefix: bytes, setting_id: int, data: bytes,
                        interval: float = 0.3) -> bytes:
        """Mirrors VendorSession.send_addressed() (see session.py) --
        same page-crossing split, recorded the same way send_raw() is, so
        a test asserting on .sent/.payloads sees exactly what real
        hardware would."""
        from pyg7.constants import CMD_WRITE
        end = setting_id + len(data)
        if end <= 0x100:
            return self.send_raw(CMD_WRITE, prefix + bytes([setting_id, len(data)]) + data)
        fits = 0x100 - setting_id
        self.send_raw(CMD_WRITE, prefix + bytes([setting_id, fits]) + data[:fits])
        self.heartbeat()
        remainder = data[fits:]
        next_prefix = prefix[:2] + bytes([prefix[2] + 1])
        return self.send_raw(CMD_WRITE, next_prefix + bytes([0x00, len(remainder)]) + remainder)

    def read_chunk(self, category: int, offset: int, length: int, timeout: float = 2.0) -> bytes:
        self.reads.append((category, offset, length))
        chunk = self._blob[offset:offset + length]
        return chunk.ljust(length, b"\x00")

    def read_blob(self, category: int, length: int, interval: float = 0.05) -> bytes:
        """Matches VendorSession.read_blob()'s chunking (see session.py) --
        needed to exercise state.read_state() end-to-end against a fake."""
        from pyg7.constants import READ_CHUNK_LENGTH
        blob = bytearray()
        offset = 0
        while offset < length:
            chunk_len = min(READ_CHUNK_LENGTH, length - offset)
            blob.extend(self.read_chunk(category, offset, chunk_len))
            self.heartbeat()
            offset += chunk_len
        return bytes(blob)

    def read_live_suffix(self, profile: int, storage_offset: int, length: int,
                          interval: float = 0.0) -> bytes:
        return self.read_chunk(0, storage_offset + 1, length)

    def settle(self, count: int = 0, interval: float = 0.0) -> None:
        pass

    # --- assertions helpers ---

    @property
    def payloads(self) -> list[bytes]:
        """Just the payloads, in send order."""
        return [payload for _cmd, payload in self.sent]

    def only_payload(self) -> bytes:
        """The single payload sent, asserting there was exactly one."""
        assert len(self.sent) == 1, f"expected exactly 1 write, got {len(self.sent)}"
        return self.sent[0][1]


def blob_with(values: dict[int, int], size: int = 512) -> bytes:
    """Build a config blob with specific bytes at specific offsets.

    Lets a decoder test state its expectation as "byte 0x30 is 2, so the
    report rate should read 1000Hz" instead of hand-assembling 512 bytes.
    """
    buf = bytearray(size)
    for offset, value in values.items():
        buf[offset] = value
    return bytes(buf)


def button_record(keycode: int) -> bytes:
    """One bound slot in the button table: `01 [KEYCODE] 00 00 00 00 00`."""
    return bytes([0x01, keycode, 0, 0, 0, 0, 0])


UNBOUND_RECORD = bytes(7)  # leading byte != 0x01 -> decoded as unbound
