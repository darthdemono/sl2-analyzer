"""Small in-memory checks for the copy-only .sl2 editor."""

import hashlib
import os
import struct
import sys
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sl2.bnd4 import checksum_ok, parse_bnd4  # noqa: E402
from sl2.convert import STEAM_ID64_HIGH, steam_owner  # noqa: E402
from sl2.edit import ER_SLOT_ENTRY_SIZE, set_steam_id, trim_er_slots  # noqa: E402
from sl2.keys import DS3_KEY  # noqa: E402


## @brief Make a minimal, non-overlapping BND4 from raw entry blobs.
def bnd(blobs):
    table = 64 + 32 * len(blobs)
    out = bytearray(max(0x100, table))
    out[:4] = b"BND4"
    struct.pack_into("<I", out, 12, len(blobs))
    for i, blob in enumerate(blobs):
        offset = len(out)
        out.extend(blob)
        base = 64 + 32 * i
        struct.pack_into("<Q", out, base + 8, len(blob))
        struct.pack_into("<I", out, base + 16, offset)
    return bytes(out)


## @brief Wrap a plaintext entry in the normal outer MD5.
def wrapped(payload):
    return hashlib.md5(payload).digest() + payload


class Editor(unittest.TestCase):
    def test_ds3_steam_id_round_trip(self):
        steam = (STEAM_ID64_HIGH << 32) | 123
        first = b"A" * 16
        first_plain = Cipher(algorithms.AES(DS3_KEY), modes.ECB()).decryptor().update(first)
        plain = bytearray(bytes(a ^ b for a, b in zip(first_plain, first)) + b"\0" * 16)
        struct.pack_into("<I", plain, 16, 12)
        struct.pack_into("<Q", plain, 24, steam)
        menu = Cipher(algorithms.AES(DS3_KEY), modes.CBC(first)).encryptor().update(plain)
        self.assertEqual(menu[:16], first)
        data = bnd([wrapped(b"\0" * 16) for _ in range(10)] + [wrapped(menu), wrapped(b"\0" * 16)])

        changed = set_steam_id(data, str(steam + 1))
        self.assertEqual(steam_owner(changed, parse_bnd4(changed), "ds3")[1], str(steam + 1))
        self.assertTrue(all(checksum_ok(changed, e) for e in parse_bnd4(changed)))
        self.assertEqual(set_steam_id(changed, steam), data)

    def test_er_trim_keeps_only_requested_slot(self):
        slots = [wrapped(bytes([i + 1]) * (ER_SLOT_ENTRY_SIZE - 16)) for i in range(10)]
        menu = bytearray(7000)
        struct.pack_into("<I", menu, 352 - 16, 0)  # offset is in the MD5-prefixed blob
        menu[356 - 16 : 366 - 16] = b"\1" + b"\0" * 9
        menu[366 - 16 + 588 : 366 - 16 + 2 * 588] = b"x" * 588
        data = bnd(slots + [wrapped(menu), wrapped(b"\0" * 16)])

        changed = trim_er_slots(data, [1])
        entries = parse_bnd4(changed)
        self.assertEqual(changed[entries[0].offset + 16], 1)
        self.assertFalse(any(changed[entries[1].offset + 16 : entries[1].offset + entries[1].size]))
        self.assertTrue(all(checksum_ok(changed, e) for e in entries))

        inactive = trim_er_slots(data)
        self.assertEqual(inactive[entries[0].offset + 16], 1)
        self.assertFalse(any(inactive[entries[1].offset + 16 : entries[1].offset + entries[1].size]))


if __name__ == "__main__":
    unittest.main()
