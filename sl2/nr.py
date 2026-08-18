"""Elden Ring Nightreign.

What is read here is identity, and the module says so rather than implying more. The
save is fully decrypted (see @ref sl2.crypto.decrypt_nr) and every entry verifies its
own MD5, so the bytes are not in question — the layout past the roster is. Nightreign
does not persist a character level, attributes or souls the way the other games do:
progression lives in relics, unlocked Nightfarers and Nightlord kills, and none of
those has been pinned against a second save yet.
"""

from .reader import is_valid_name, read_utf16, u32

## @brief Number of character slots, matching the ten slot entries in the container.
NR_SLOT_COUNT = 10


## @brief The four-byte marker that opens each profile's appearance block.
#  @details The roster is found by this rather than by a fixed offset. Nightreign
#  writes a variable-length block ahead of the profile table exactly as Elden Ring
#  does, so an offset measured on one save is an offset measured on one save. Ten of
#  these at a constant stride is a shape nothing else in the file reproduces.
NR_FACE_MAGIC = b"FACE"


## @brief Bytes between one profile and the next, and where a name sits relative to
#  the appearance marker that anchors it.
#  @details Measured: the ten markers in the test save are 632 bytes apart, and the
#  name ends 54 bytes before each one. The name is UTF-16 in a 32-byte field, so
#  @ref NR_NAME_CHARS is sixteen — @ref sl2.reader.read_utf16 counts characters, not
#  bytes, and reading it as 32 would run a name into the appearance block behind it.
NR_PROFILE_STRIDE, NR_NAME_BACK_FROM_FACE, NR_NAME_CHARS = 632, 54, 16


## @brief Which entry carries the account, and where in it.
#  @details Entry 10 is the menu block; the SteamID64 is a little-endian uint64 eight
#  bytes in. Checked against the folder the test save shipped in — the file reads
#  76561197960272671 and the folder is named 76561197960272671.
NR_STEAM_ENTRY, NR_STEAM_OFF = 10, 0x08


## @brief A slot this empty holds no character.
#  @details An unused Nightreign slot is not all zero — it carries about thirty
#  nonzero bytes of scaffolding in a megabyte. A used one is half nonzero, so the
#  threshold is nowhere near anything, and counting is cheap next to decrypting.
NR_EMPTY_SLOT_MAX_NONZERO = 4096


##
# @brief Locate the profile table in a decrypted menu entry.
# @details Finds the run of @ref NR_SLOT_COUNT appearance markers spaced exactly
# @ref NR_PROFILE_STRIDE apart and returns where the first profile's name starts. A
# single marker proves nothing — character data elsewhere in the file could spell the
# same four bytes — so the whole run has to hold before anything is returned.
# @param menu The decrypted menu entry.
# @return Offset of slot 0's name field, or None if no such run exists.
def nr_find_profiles(menu):
    at = menu.find(NR_FACE_MAGIC)
    while at >= 0:
        if all(
            menu[at + NR_PROFILE_STRIDE * i : at + NR_PROFILE_STRIDE * i + 4]
            == NR_FACE_MAGIC
            for i in range(1, NR_SLOT_COUNT)
        ):
            start = at - NR_NAME_BACK_FROM_FACE
            return start if start >= 0 else None
        at = menu.find(NR_FACE_MAGIC, at + 1)
    return None


##
# @brief Read the Nightreign roster: one name per slot, empty where unused.
# @param menu The decrypted menu entry.
# @return A list of @ref NR_SLOT_COUNT names, each possibly None.
def nr_roster(menu):
    base = nr_find_profiles(menu)
    if base is None:
        return [None] * NR_SLOT_COUNT
    out = []
    for i in range(NR_SLOT_COUNT):
        name = read_utf16(menu, base + NR_PROFILE_STRIDE * i, NR_NAME_CHARS)
        out.append(name if name and is_valid_name(name) else None)
    return out


##
# @brief Read the account this save belongs to.
# @param menu The decrypted menu entry.
# @return @c (low dword, high dword) of the SteamID64, or None.
# @details Returned as two halves rather than one integer for the same reason every
# other game here does it: a SteamID64 does not survive a JavaScript double, and the
# two front ends have to agree byte for byte.
def nr_steam_id(menu):
    lo, hi = u32(menu, NR_STEAM_OFF), u32(menu, NR_STEAM_OFF + 4)
    return None if lo is None or hi is None else (lo, hi)


##
# @brief Is this decrypted slot occupied?
# @param slot The decrypted slot entry.
# @return True if the slot holds a character.
def nr_slot_used(slot):
    return sum(1 for b in slot[:0x20000] if b) > NR_EMPTY_SLOT_MAX_NONZERO


##
# @brief Build the unified character dict for one Nightreign slot.
# @details Identity only, and every other key is None on purpose so the writers can
# treat this like any other character without inventing fields. The tier is
# @c "roster", which is the whole claim: this save was opened, decrypted and its
# character named, and nothing further is asserted.
# @param name The roster name for this slot.
# @return A unified character dict.
def nr_parse(name):
    return {
        "tier": "roster",
        "game": "nr",
        "name": name if (name and is_valid_name(name)) else "(unnamed slot)",
        "klass": None,
        "stats": {},
        "soul_memory": None,
        "humanity": None,
        "ng_plus": None,
        "level": None,
        "souls": None,
        "stamina": None,
        "hp": None,
        "boss_souls": [],
        "key_items": [],
        "inv": {},
        "unknown_count": 0,
    }
