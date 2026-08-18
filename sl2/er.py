"""Elden Ring."""

import json
import os
from collections import OrderedDict, defaultdict

from .reader import is_valid_name, read_utf16, u8, u32

## @brief Offset of the GaItem array inside an ER slot: past the 16-byte checksum,
#  the version and map-id words, and the 16 bytes after them.
#
#  **Measured, and it is 0x30 rather than the 0x20 this once used.** A 16-byte error
#  here does not read 16 bytes of nonsense and recover — the entries are
#  variable-length (a weapon is 21 bytes, armour 16, everything else 8), so the walk
#  takes its tail length from a misread id and drifts for the rest of the array. The
#  anchor that pins it is the handle column: from 0x30 the handles run **strictly
#  sequential** for hundreds of entries (0xc080008b, 0x8c, 0x8d, ...), which is not
#  something a misaligned read produces.
#
#  The check that settles it is the category nibble. Only 0x0/0x1/0x2/0x4/0x8 are
#  real categories and 0xF is the empty-slot marker, so any other nibble is proof the
#  walk has lost its place. Across 182 characters: **148 of them carried illegal
#  nibbles at 0x20, and none at all at 0x30** — with naming going 89.0% to 98.8% at
#  the same time.
ER_GAITEM_START = 0x30


## @brief Number of GaItem entries in the array.
ER_GAITEM_COUNT = 0x1400


## @brief In the menu (header) entry: offset of the variable-length menu-system
#         block's length field, the byte after which its data begins, the number
#         of character slots, the size of one profile summary, and the profile
#         field offsets for name and level. Layout per ClayAmore/ER-Save-Editor.
ER_MENU_LEN_OFF, ER_MENU_DATA_OFF = 352, 356


ER_SLOT_COUNT, ER_PROFILE_STRIDE = 10, 588


ER_PROFILE_NAME_LEN, ER_PROFILE_LEVEL_OFF = 16, 34


## @brief ER stat block as signed distances from the Vigor field (the anchor).
#  Eight attributes in the game's storage order, read against a real level-266
#  save (offsets checked on a second character in the same file).
ER_STAT_D = OrderedDict(
    [
        ("Vigor", 0),
        ("Mind", 4),
        ("Endurance", 8),
        ("Strength", 12),
        ("Dexterity", 16),
        ("Intelligence", 20),
        ("Faith", 24),
        ("Arcane", 28),
    ]
)


## @brief ER max HP, stamina, rune level and runes held, same anchor-relative scheme.
#  (The block also carries FP just before stamina; not surfaced.)
ER_HP_D, ER_STAM_D, ER_LEVEL_D, ER_RUNES_D = -40, -12, 44, 48


## @brief ER's rune-level identity: level == (sum of the eight attributes) - 79.
#  Wretch (all 10, sum 80) is level 1, and it holds at every level — the content
#  check that pins the stat block, whose slot offset varies from character to
#  character (variable-length data precedes it, so a fixed offset will not do).
ER_LEVEL_BASE = 79


## @brief The highest rune level the identity can produce: eight attributes at 99
#  sum to 792, minus @ref ER_LEVEL_BASE. A roster level past it is not a level.
ER_LEVEL_MAX = 8 * 99 - ER_LEVEL_BASE


##
# @brief Read the ER character roster (active flag, name, level per slot).
# @details Walks past the fixed header and the variable-length menu-system block
# to reach the active-slot bytes and the fixed-stride profile summaries. Names and
# levels here are reliable; they are the load screen's own data.
# @param menu The header entry blob (from its start, checksum included).
# @return A list of @c (active, name, level) tuples, one per slot.
def er_roster(menu):
    length = u32(menu, ER_MENU_LEN_OFF)
    if length is None:
        return []
    active_base = ER_MENU_DATA_OFF + length
    pbase = active_base + ER_SLOT_COUNT
    out = []
    for i in range(ER_SLOT_COUNT):
        active = bool(u8(menu, active_base + i))
        base = pbase + i * ER_PROFILE_STRIDE
        name = read_utf16(menu, base, ER_PROFILE_NAME_LEN)
        level = u32(menu, base + ER_PROFILE_LEVEL_OFF)
        out.append((active, name, level))
    return out


## @brief The ids that mean "this slot is empty", not "the character owns this".
#  @details Elden Ring fills an unused equipment slot with a real row rather than a
#  zero, and the game's own name tables name them: weapon row 110000 is **Unarmed**,
#  and armour rows 10000/10100/10200/10300 are the bare **Head/Body/Arms/Legs**. They
#  are in the GaItem array of every character alive, so listing them as owned gear says
#  "carries: Unarmed, Arms, Legs" about someone wearing a full set. Skipped, and not
#  counted as unrecognised either — they are recognised perfectly well, they just are
#  not items. Stored as save ids, category nibble included.
ER_EMPTY_SLOT_IDS = frozenset(
    {0x0001ADB0, 0x10002710, 0x10002774, 0x100027D8, 0x1000283C}
)


##
# @brief Walk the ER GaItem array and yield every owned item id.
# @details Each GaItem is 8 bytes (handle + id) plus a variable tail decided by
# the id's category nibble: weapons (0x0) carry 13 more bytes, armour (0x1) 8
# more, everything else none. Getting that tail right is what keeps the walk
# aligned across all 0x1400 entries.
# @param buf The ER slot data, checksum and all — @ref ER_GAITEM_START skips it.
# @return A generator of nonzero item ids.
def er_gaitems(buf):
    o = ER_GAITEM_START
    for _ in range(ER_GAITEM_COUNT):
        if o + 8 > len(buf):
            return
        iid = u32(buf, o + 4)
        o += 8
        if iid:
            cat = iid & 0xF0000000
            if cat == 0x00000000:
                o += 13
            elif cat == 0x10000000:
                o += 8
            yield iid


##
# @brief Locate the ER stat block by content, or None if none validates.
# @details The block sits at a different offset in every slot, so it is found rather
# than read from a fixed spot. The search is anchored on the level field: every place
# the slot stores @p level as a little-endian uint32 is a candidate, the block is read
# back from there, and it is accepted only where each of the eight attributes is 1..99
# and their sum minus @ref ER_LEVEL_BASE equals that level. ER's own level formula, so
# a coincidental match is not credible.
#
# **The block is NOT 4-aligned.** Variable-length data precedes it — the character name
# among it — so its offset is whatever that data leaves it at. Scanning on a 4-byte
# stride finds only the quarter of characters that happen to land on it: across a
# 182-character corpus a strided scan found 29 blocks where this finds all 182.
#
# **The roster level is required, and it is what makes the answer trustworthy.** The
# identity alone false-positives: on that same corpus five slots matched a run of bytes
# megabytes past the real block and reported levels of 2, 13, 22 and 25 for characters
# the roster puts at 125, 150 and 160. Checking against the independently stored roster
# level kills all five. Without a roster level there is nothing to check against, so
# the slot keeps its inventory tier rather than printing a number that might be junk.
# @param buf   The ER slot data.
# @param level The character's rune level from the roster.
# @return The Vigor-field offset (the anchor), or None.
def er_find_stats(buf, level):
    if level is None or not (1 <= level <= ER_LEVEL_MAX):
        return None
    dists = list(ER_STAT_D.values())
    pat = level.to_bytes(4, "little")
    at = buf.find(pat)
    while at >= 0:
        v = at - ER_LEVEL_D
        if v >= 0:
            vals = [u32(buf, v + d) for d in dists]
            if (
                all(x is not None and 1 <= x <= 99 for x in vals)
                and sum(vals) - ER_LEVEL_BASE == level
            ):
                return v
        at = buf.find(pat, at + 1)
    return None


##
# @brief Parse one ER slot into the unified dict (full where stats validate).
# @details Owned items come from the GaItem walk resolved against the id table;
# ids may carry category bits, so a direct hit is tried first, then the masked id.
# Bosses are inferred from Remembrances held. Attributes are *located by content*
# (@ref er_find_stats) — the block's slot offset varies, so it is found by the
# rune-level identity, not a fixed offset. When it validates the slot is full
# tier; otherwise stats drop and it stays inventory tier (the roster level still
# stands). Quantities and the reinforced-weapon base ids are still not read.
# @param buf   The ER slot data.
# @param iddb  Flat @c {id: name} table.
# @param name  The character name from the roster, or None.
# @param level The character level from the roster, or None.
# @return A unified character dict, or None.
def er_parse(buf, iddb, name, level):
    buckets, unknown = defaultdict(set), 0
    for iid in er_gaitems(buf):
        if iid in ER_EMPTY_SLOT_IDS:
            continue
        nm, cat = er_resolve(iid, iddb)
        if nm:
            buckets[cat].add(nm)
        elif cat:
            unknown += 1
    if not any(buckets.values()):
        return None
    inv = {c: [(n, None) for n in sorted(v)] for c, v in buckets.items()}
    remembrances = [
        (n, None) for c in buckets for n in sorted(buckets[c]) if "Remembrance" in n
    ]
    v = er_find_stats(buf, level)
    stats = (
        OrderedDict((k, u32(buf, v + d)) for k, d in ER_STAT_D.items())
        if v is not None
        else OrderedDict()
    )
    return {
        "tier": "full" if stats else "inventory",
        "game": "er",
        "name": name if (name and is_valid_name(name)) else "(unnamed slot)",
        "klass": None,
        "stats": stats,
        "soul_memory": None,
        "humanity": None,
        "ng_plus": None,
        "level": u32(buf, v + ER_LEVEL_D) if v is not None else level,
        "souls": u32(buf, v + ER_RUNES_D) if v is not None else None,
        "stamina": u32(buf, v + ER_STAM_D) if v is not None else None,
        "hp": u32(buf, v + ER_HP_D) if v is not None else None,
        "boss_souls": remembrances,
        "key_items": [],
        "inv": inv,
        "unknown_count": unknown,
    }


## @brief ER item category by id top nibble (the ItemGib type code), and the render
#  category each maps to. Weapon (0x0), Protector/armour (0x1), Accessory/talisman
#  (0x2), Goods (0x4), Gem/Ash of War (0x8). The nibble the GaItem walk already
#  trusts for its tail length is the item TYPE, so it also scopes name resolution —
#  the fix for the old flat lookup that collided base ids across types (~20% wrong).
ER_CAT = {0x0: "weapons", 0x1: "armors", 0x2: "talismans", 0x4: "goods", 0x8: "ashes"}


## @brief ER db category files (one per type), each @c {8-hex-id: name}.
ER_DB_FILES = tuple(ER_CAT.values())


## @brief Weapon ids bake affinity+reinforcement into the low digits: the id is
#  @c base + affinity*100 + level, base spaced by @ref ER_WEAPON_BASE_STEP. So
#  `id % 100` is the reinforcement level, `id - id % 100` is the affinity row (which
#  is what the table names), and `id - id % 10000` is the plain base.
ER_WEAPON_BASE_STEP = 10000
ER_WEAPON_AFFINITY_STEP = 100


## @brief Highest reinforcement ER allows (+25 on the standard path; somber stops at
#  +10). A low-digit remainder above this is not a level, so no level is claimed.
ER_MAX_REINFORCE = 25


##
# @brief Load the ER id tables, category-scoped: @c {category: {id: name}}.
# @param db_dir Folder holding one JSON per category (weapons/armors/…).
# @return The lookup, or {} if none present.
def load_er_db(db_dir):
    db = {}
    for cat in ER_DB_FILES:
        try:
            with open(os.path.join(db_dir, cat + ".json"), encoding="utf-8") as f:
                db[cat] = {int(k, 16): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            continue
    return db


##
# @brief Resolve an ER item id to (name, category), type-scoped by its nibble.
# @details The category comes from the id's top nibble (@ref ER_CAT); the name is
# looked up ONLY in that category's table, so an armour id can never resolve to a
# weapon of the same base number. A weapon miss then strips the reinforcement level
# to land on the affinity row the table actually names ("Sacred Butchering Knife"),
# and only failing that falls back to the plain base. The level is appended, so a
# reinforced weapon reads as itself rather than as its unupgraded twin.
# @return @c (name, category); name is None when unresolved, category None when the
#         nibble is not a known type.
def er_resolve(iid, db):
    cat = ER_CAT.get((iid >> 28) & 0xF)
    if cat is None:
        return None, None
    table = db.get(cat, {})
    name = table.get(iid)
    if name is not None or cat != "weapons":
        return name, cat
    level = iid % ER_WEAPON_AFFINITY_STEP
    if level > ER_MAX_REINFORCE:
        level = 0
    for step in (ER_WEAPON_AFFINITY_STEP, ER_WEAPON_BASE_STEP):
        name = table.get(iid - iid % step)
        if name is not None:
            return (f"{name} +{level}" if level else name), cat
    return None, cat
