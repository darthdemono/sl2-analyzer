"""Which game a save belongs to, from its header signature and entry count."""

import sys

from .crypto import _aes_cbc
from .keys import DS2_KEY, DS2_VANILLA_KEY
from .reader import u32

## @brief The BND4 signature DS2 stamps into its header.
DS2_SIGNATURE = b"14e503cb"


## @brief Size of one Sekiro character slot's BND4 entry: 0x100000 of payload behind
#  the 16-byte MD5. This is what identifies the game, because its entry COUNT does
#  not: 11 on the published layout (DS1's count) and 12 on the current patch, which
#  adds a reserved, all-zero twelfth entry (DS3's and Elden Ring's count).
SDT_SLOT_ENTRY_SIZE = 0x100010


## @brief Size of one Elden Ring Nightreign character slot's BND4 entry, and the
#  number of entries the file carries.
# @details Nightreign is the only save here with fourteen entries, so the count alone
# would do; the slot size is checked as well because it sits **0x20 away from
# Sekiro's** (`0x100030` against `0x100010`), and a size test that close is worth
# stating rather than leaving to a reader to notice.
NR_SLOT_ENTRY_SIZE, NR_ENTRY_COUNT = 0x100030, 14


##
# @brief Identify which game wrote this save, from the bytes alone.
# @details The header signature and entry count narrow it down; the remaining
# ambiguities are settled by content — SOTFS is the DS2 variant whose key produces a
# sane length prefix, Sekiro is the one whose slots are 0x100010, and ER's entries are
# far larger than DS3's. Nightreign is the only one with fourteen entries.
# @param data    The full file bytes.
# @param entries The parsed entry table.
# @return One of @c "ds2vanilla", @c "ds2sotfs", @c "dsr", @c "ptde",
#         @c "ds3", @c "er", @c "sdt", @c "nr".
def detect_game(data, entries):
    sig = data[24:32]
    n = len(entries)
    if sig == DS2_SIGNATURE:
        # Both DS2 variants share the signature, so they are told apart by which key
        # decrypts: the length prefix at plaintext +0 must fit the block. A wrong key
        # yields noise, which fails that test essentially always.
        blob = data[entries[1].offset : entries[1].offset + entries[1].size]
        for key, game in ((DS2_KEY, "ds2sotfs"), (DS2_VANILLA_KEY, "ds2vanilla")):
            pt = _aes_cbc(key, blob[16:32], blob[32:])
            dlen = u32(pt, 0)
            if dlen is not None and 0 < dlen <= len(pt) - 4:
                return game
        sys.exit(
            "Dark Souls II save found, but neither the Scholar nor the vanilla "
            "key decrypts it."
        )
    # Sekiro's entry count is shared with DS1 and with DS3/ER, so the slot SIZE is
    # what settles it, and it is unambiguous: DSR 0x60030, PtDE 0x60014, DS3 0xC0030,
    # ER 0x280010, Sekiro 0x100010.
    if n >= 11 and entries[0].size == SDT_SLOT_ENTRY_SIZE:
        return "sdt"
    if n == 11:
        return "dsr" if sig == b"\x00" * 8 else "ptde"
    if n == 12:
        return "er" if entries[0].size > 2_000_000 else "ds3"
    if n == NR_ENTRY_COUNT and entries[0].size == NR_SLOT_ENTRY_SIZE:
        return "nr"
    sys.exit("Unrecognised .sl2 — not a supported Souls save.")
