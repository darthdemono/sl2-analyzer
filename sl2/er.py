"""Elden Ring.
"""
import json
import os
from collections import defaultdict, OrderedDict
from .reader import is_valid_name, read_utf16, u32, u8


## @brief Offset of the GaItem array inside an ER slot (ver + map_id + 0x18 pad).
ER_GAITEM_START = 0x20


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
ER_STAT_D = OrderedDict([
    ("Vigor", 0), ("Mind", 4), ("Endurance", 8), ("Strength", 12),
    ("Dexterity", 16), ("Intelligence", 20), ("Faith", 24), ("Arcane", 28)])


## @brief ER max HP, stamina, rune level and runes held, same anchor-relative scheme.
#  (The block also carries FP just before stamina; not surfaced.)
ER_HP_D, ER_STAM_D, ER_LEVEL_D, ER_RUNES_D = -40, -12, 44, 48


## @brief ER's rune-level identity: level == (sum of the eight attributes) - 79.
#  Wretch (all 10, sum 80) is level 1, and it holds at every level — the content
#  check that pins the stat block, whose slot offset varies from character to
#  character (variable-length data precedes it, so a fixed offset will not do).
ER_LEVEL_BASE = 79


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


##
# @brief Walk the ER GaItem array and yield every owned item id.
# @details Each GaItem is 8 bytes (handle + id) plus a variable tail decided by
# the id's category nibble: weapons (0x0) carry 13 more bytes, armour (0x1) 8
# more, everything else none. Getting that tail right is what keeps the walk
# aligned across all 0x1400 entries.
# @param buf The ER slot data (BND4 entry payload after the 16-byte checksum).
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
# @details ER stat offsets move, and the block sits at a different slot offset for
# every character, so it is found rather than read from a fixed spot: for each
# 4-aligned position, treat the next eight uint32 as the attributes and accept only
# where each is 1..99 and their sum minus @ref ER_LEVEL_BASE equals the stored rune
# level. That identity is ER's own level formula, so a coincidental match is not
# credible.
# @param buf The ER slot data.
# @return The Vigor-field offset (the anchor), or None.
def er_find_stats(buf):
    dists = list(ER_STAT_D.values())
    v, end = 0, len(buf) - ER_RUNES_D - 4
    while v < end:
        first = u32(buf, v)
        if first is not None and 1 <= first <= 99:
            vals = [u32(buf, v + d) for d in dists]
            lvl = u32(buf, v + ER_LEVEL_D)
            if (all(x is not None and 1 <= x <= 99 for x in vals)
                    and lvl is not None and 1 <= lvl <= 713
                    and sum(vals) - ER_LEVEL_BASE == lvl):
                return v
        v += 4
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
        nm, cat = er_resolve(iid, iddb)
        if nm:
            buckets[cat].add(nm)
        elif cat:
            unknown += 1
    if not any(buckets.values()):
        return None
    inv = {c: [(n, None) for n in sorted(v)] for c, v in buckets.items()}
    remembrances = [(n, None) for c in buckets for n in sorted(buckets[c])
                    if "Remembrance" in n]
    v = er_find_stats(buf)
    stats = OrderedDict((k, u32(buf, v + d)) for k, d in ER_STAT_D.items()) \
        if v is not None else OrderedDict()
    return {
        "tier": "full" if stats else "inventory", "game": "er",
        "name": name if (name and is_valid_name(name)) else "(unnamed slot)",
        "klass": None, "stats": stats, "soul_memory": None, "humanity": None,
        "ng_plus": None,
        "level": u32(buf, v + ER_LEVEL_D) if v is not None else level,
        "souls": u32(buf, v + ER_RUNES_D) if v is not None else None,
        "stamina": u32(buf, v + ER_STAM_D) if v is not None else None,
        "hp": u32(buf, v + ER_HP_D) if v is not None else None,
        "boss_souls": remembrances, "key_items": [],
        "inv": inv, "unknown_count": unknown,
    }


## @brief ER item category by id top nibble (the ItemGib type code), and the render
#  category each maps to. Weapon (0x0), Protector/armour (0x1), Accessory/talisman
#  (0x2), Goods (0x4), Gem/Ash of War (0x8). The nibble the GaItem walk already
#  trusts for its tail length is the item TYPE, so it also scopes name resolution —
#  the fix for the old flat lookup that collided base ids across types (~20% wrong).
ER_CAT = {0x0: "weapons", 0x1: "armors", 0x2: "talismans", 0x4: "goods", 0x8: "ashes"}


## @brief ER db category files (one per type), each @c {8-hex-id: name}.
ER_DB_FILES = tuple(ER_CAT.values())


## @brief Weapon ids bake affinity+reinforcement into the low digits; base ids are
#  spaced by this, so `id - id % step` recovers the base for a fallback lookup.
ER_WEAPON_BASE_STEP = 10000


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
# weapon of the same base number. Reinforced/affinity weapons carry the upgrade in
# their low digits and are not in the table, so on a weapon miss the base id is
# tried — giving the base weapon's name (the upgrade level itself is still not read).
# @return @c (name, category); name is None when unresolved, category None when the
#         nibble is not a known type.
def er_resolve(iid, db):
    cat = ER_CAT.get((iid >> 28) & 0xF)
    if cat is None:
        return None, None
    table = db.get(cat, {})
    name = table.get(iid)
    if name is None and cat == "weapons":
        name = table.get(iid - iid % ER_WEAPON_BASE_STEP)
    return name, cat
