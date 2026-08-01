"""Which game a save belongs to, from its header signature and entry count.
"""
import sys
from .reader import u32
from .keys import DS2_KEY, DS2_VANILLA_KEY
from .crypto import _aes_cbc


## @brief The BND4 signature DS2 stamps into its header.
DS2_SIGNATURE = b"14e503cb"


##
# @brief Identify which game wrote this save, from the bytes alone.
# @details The header signature and entry count narrow it down; the last
# ambiguity — vanilla DS2 versus SOTFS (same signature) and DS3 versus ER (same
# count) — is settled by content: SOTFS is the DS2 variant whose key produces a
# sane length prefix, and ER's entries are far larger than DS3's.
# @param data    The full file bytes.
# @param entries The parsed entry table.
# @return One of @c "ds2vanilla", @c "ds2sotfs", @c "dsr", @c "ptde",
#         @c "ds3", @c "er".
def detect_game(data, entries):
    sig = data[24:32]
    n = len(entries)
    if sig == DS2_SIGNATURE:
        # Both DS2 variants share the signature, so they are told apart by which key
        # decrypts: the length prefix at plaintext +0 must fit the block. A wrong key
        # yields noise, which fails that test essentially always.
        blob = data[entries[1].offset:entries[1].offset + entries[1].size]
        for key, game in ((DS2_KEY, "ds2sotfs"), (DS2_VANILLA_KEY, "ds2vanilla")):
            pt = _aes_cbc(key, blob[16:32], blob[32:])
            dlen = u32(pt, 0)
            if dlen is not None and 0 < dlen <= len(pt) - 4:
                return game
        sys.exit("Dark Souls II save found, but neither the Scholar nor the vanilla "
                 "key decrypts it.")
    if n == 11:
        return "dsr" if sig == b"\x00" * 8 else "ptde"
    if n == 12:
        return "er" if entries[0].size > 2_000_000 else "ds3"
    sys.exit("Unrecognised .sl2 — not a supported Souls save.")
