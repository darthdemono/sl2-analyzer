"""The header roster block: character names, and DS3's play-time field."""

from .keys import DS3_KEY
from .reader import read_utf16, u8

## @brief Header-entry index, occupancy-flag offset, first-descriptor offset,
#         descriptor stride, and max name length, per game.
ROSTER_PARAMS = {
    "ds3": {
        "menu": 10,
        "occ": 4244,
        "desc": 4254,
        "stride": 554,
        "namelen": 16,
        "decrypt": DS3_KEY,
    },
    "er": {
        "menu": 10,
        "occ": 6484,
        "desc": 6494,
        "stride": 588,
        "namelen": 16,
        "decrypt": None,
    },
}


##
# @brief Read the character roster from a DS3 or ER header entry.
# @details These games keep a load-screen table of ten slots — an occupancy byte
# each, then fixed-stride descriptors that begin with the character name. That
# name is trustworthy; the deeper stat and inventory blocks are not mapped in
# this build, so only the roster is returned.
# @param menu_data The decrypted header entry.
# @param game      @c "ds3" or @c "er".
# @return A list of @c (slot_index, name).
def parse_roster(menu_data, game):
    p = ROSTER_PARAMS[game]
    roster = []
    for i in range(10):
        occ = u8(menu_data, p["occ"] + i)
        if not occ:
            continue
        name = read_utf16(menu_data, p["desc"] + p["stride"] * i, p["namelen"])
        roster.append((i, name if name else "(unnamed)"))
    return roster
