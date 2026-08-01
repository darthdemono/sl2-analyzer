"""Safe, bounds-checked readers.

Nothing anywhere in the package indexes a buffer without going through these. A
read that would run off the end returns None (or "") instead of raising or
reading whatever happens to sit past it.
"""


##
# @brief Read a little-endian unsigned integer, or None if it would run past the
#        end of the buffer.
# @param buf  The bytes to read from.
# @param off  Byte offset. A negative offset is treated as out of range.
# @param size Width in bytes (1, 2, 4, or 8).
# @return The integer value, or None if the read is out of range.
def read_uint(buf, off, size):
    if off is None or off < 0 or off + size > len(buf):
        return None
    return int.from_bytes(buf[off:off + size], "little")


## @brief One-byte read. @see read_uint
def u8(buf, off):
    return read_uint(buf, off, 1)


## @brief Two-byte read. @see read_uint
def u16(buf, off):
    return read_uint(buf, off, 2)


## @brief Four-byte read. @see read_uint
def u32(buf, off):
    return read_uint(buf, off, 4)


## @brief Eight-byte read. @see read_uint
def u64(buf, off):
    return read_uint(buf, off, 8)


##
# @brief Decode a UTF-16LE string that ends at the first null pair.
# @details Souls names are UTF-16LE and not always fixed-length, so this reads a
# bounded window and stops at the first @c 0x0000. Returns an empty string on a
# bad read rather than raising.
# @param buf      The bytes to read from.
# @param off      Where the string starts.
# @param max_char Maximum characters to consider.
# @return The decoded string, stripped of trailing nulls.
def read_utf16(buf, off, max_char):
    if off is None or off < 0 or off >= len(buf):
        return ""
    raw = buf[off:off + max_char * 2]
    end = raw.find(b"\x00\x00")
    if end != -1:
        raw = raw[:end + (end & 1)]  # keep byte pairs aligned
    try:
        return raw.decode("utf-16-le", "ignore").rstrip("\x00")
    except (UnicodeDecodeError, ValueError):
        return ""


## @brief The only characters a real player name may contain. Anything outside
#         this set means the bytes are not a name — usually an empty slot.
NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_'")


##
# @brief Decide whether a decoded string is a plausible character name.
# @param name The candidate string.
# @return True if it is non-empty and every character is allowed.
def is_valid_name(name):
    return bool(name) and all(c in NAME_OK for c in name)
