"""The BND4 archive every .sl2 is, and its entry table."""

import hashlib
import sys

from .reader import u32, u64

## @brief Size of the fixed BND4 file header, in bytes.
BND4_HEADER_LEN = 64


## @brief Size of one BND4 entry header, in bytes.
BND4_ENTRY_LEN = 32


##
# @brief One decoded BND4 entry: its index and where its blob lives in the file.
class Bnd4Entry:
    ## @brief Construct from already-validated fields.
    #  @param index The entry's position in the archive.
    #  @param offset Byte offset of the entry blob inside the file.
    #  @param size   Length of the entry blob in bytes.
    def __init__(self, index, offset, size):
        self.index = index
        self.offset = offset
        self.size = size


##
# @brief Parse and validate the BND4 entry table.
# @details Refuses anything that is not a well-formed BND4 archive: bad magic, a
# silly entry count, or an entry whose blob would fall outside the file. This is
# the boundary check that lets everything downstream trust its offsets.
# @param data The full `.sl2` bytes.
# @return A list of @ref Bnd4Entry.
# @exception SystemExit on any structural problem.
def parse_bnd4(data):
    if len(data) < BND4_HEADER_LEN or data[:4] != b"BND4":
        sys.exit("Not a BND4 / .sl2 file.")
    count = u32(data, 12)
    if count is None or not (0 < count <= 64):
        sys.exit(f"Implausible BND4 entry count: {count}")
    entries = []
    for i in range(count):
        base = BND4_HEADER_LEN + BND4_ENTRY_LEN * i
        if base + BND4_ENTRY_LEN > len(data):
            sys.exit(f"Truncated entry header #{i}.")
        size = u64(data, base + 8)
        offset = u32(data, base + 16)
        if size is None or offset is None or offset + size > len(data) or size <= 0:
            sys.exit(
                f"Entry #{i} points outside the file (offset={offset}, size={size})."
            )
        entries.append(Bnd4Entry(i, offset, size))
    return entries


##
# @brief Does this entry blob carry a valid MD5 checksum wrapper?
# @details Every Souls game prefixes each entry with @c MD5(rest). It is not a
# game discriminator (they all have it), but it is a cheap integrity check.
# @param data  The full file bytes.
# @param entry The entry to check.
# @return True if @c blob[0:16] equals the MD5 of the remaining blob bytes.
def checksum_ok(data, entry):
    blob = data[entry.offset : entry.offset + entry.size]
    return len(blob) >= 16 and hashlib.md5(blob[16:]).digest() == blob[:16]
