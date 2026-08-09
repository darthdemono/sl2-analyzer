"""Sekiro: Shadows Die Twice.

The odd one out in three ways, and each of them makes the read simpler rather than
harder. The save is NOT encrypted (plaintext BND4 entries behind a plain MD5, like
PtDE and Elden Ring), the slot offsets do NOT move between patches (so there is no
content scan and no level identity to check), and reinforcement is NOT baked into an
item id — a prosthetic tool's upgrade tier is its own id, so a straight lookup names
"Lazulite Shuriken" with no arithmetic.

What it does not have is a character name — Sekiro's profiles are unnamed by design —
or attributes. Its numbers are Attack Power, max HP and max Posture; the Vitality LEVEL
behind the last two is in no published source and is not read.

Offsets from uberhalit/SimpleSekiroSavegameHelper (the container) and
alfizari/Sekiro-Save-Editor (the slot fields), every one of them verified against a real
S0000.sl2 — and two of that editor's labels corrected against a differential, because
they point at the current value rather than the maximum.
"""
import json
import os
from .reader import u8, u32, u64


## @brief How many character slots the game has. Entry 10 is the settings/profile
#  block and entry 11 (present on the current patch, absent in the published layout)
#  is reserved and reads all zeros.
SDT_SLOT_COUNT = 10


##
# @brief Slot fields, at fixed offsets into the decrypted (plaintext) slot payload.
# @details These do not move between patches — Sekiro has no equivalent of the DS3
# stat block that drifts — so they are read directly rather than searched for. The
# Steam id is NOT printed anywhere; it is read only as the occupancy test, because an
# unused slot is all zeros and a used one carries its owner's id. That was checked
# both ways: the id matches the save's own folder name, and the nine unused slots (and
# a second, characterless save file) read zero.
SDT_STEAM_OFF = 0x33E54     # u64
SDT_NG_OFF = 0x33F34        # u8, journey (New Game+) count
SDT_PLAYTIME_OFF = 0x33F80  # u32, SECONDS
SDT_ATTACK_OFF = 0x3449C    # u32, attack power
SDT_SEN_OFF = 0x344D0       # u32, Sen (the currency — alfizari's README calls it Souls)


##
# @brief Max HP and max Posture, each stored TWICE, and neither at the offset the
#        published source names.
# @details Both live in the same four-word shape — @c [0][current][max][max] — and
# alfizari's editor labels the CURRENT field of each as the maximum. A real differential
# settles it: across a 42-minute window the word at @c 0x3446C moved 32 → 160 while
# @c 0x34470 and @c 0x34474 both held at 320. A value that moves while its neighbours do
# not is the current one; the pair that holds is the maximum. Posture sits in the
# identical shape one group along (its zero word at @c 0x34484), so its maximum is the
# same two fields over — which also explains why all three of its words read 120: posture
# is a pool that depletes, and an undamaged character is at full.
#
# Each is read only where BOTH copies agree and the value is nonzero. That is the same
# self-consistency gate the DS3 equipment slots use, and here it costs nothing: the game
# writes both, so a disagreement means the read landed somewhere it should not have.
SDT_HP_OFF, SDT_HP_ALT = 0x34470, 0x34474
SDT_POSTURE_OFF, SDT_POSTURE_ALT = 0x3448C, 0x34490


##
# @brief Read a field the game stores twice, or None unless both copies agree.
# @param buf The slot payload. @param off The field. @param alt Its second copy.
def sdt_twin(buf, off, alt):
    value = u32(buf, off)
    return value if value and value == u32(buf, alt) else None


## @brief Attack power on a character who has consumed no Memory. Read off a real
#  save that is minutes from the opening — no Memory held, no gourd, one key item —
#  which is what makes the base a measurement rather than an assumption. It matters
#  because @ref sdt_memories_spent subtracts it.
SDT_ATTACK_BASE = 1


## @brief Ceilings that make a field a field rather than noise. Attack power caps at
#  98 in game and the journey counter cannot plausibly run to 256, so a value past
#  either means the read landed somewhere it should not have and the field is dropped.
SDT_ATTACK_MAX, SDT_NG_MAX = 98, 99


## @brief One inventory-style list: where it starts and how long it runs. Records are
#  16 bytes, `[u32 handle][u32 item id][u32 quantity][u32 index]`. `key` items get
#  their own region in Sekiro (every other game needs them filtered out of a bucket),
#  and the storage box is kept apart because an item in the box is owned but not
#  carried — a distinction the report can only make if the read makes it too.
SDT_LISTS = (
    ("inv", 0x8F70C, 0x7000),
    ("key", 0x9670C, 0x2000),
    ("storage", 0x987A0, 0x9000),
    ("storage", 0xA1958, 0x4000),
)


SDT_RECORD = 16


## @brief Item type, from the top nibble of the record's HANDLE. Scoped by
#  construction, the same property Elden Ring's id nibble gives: an armour handle
#  cannot resolve to a weapon of the same number. 0x0 is an empty record.
SDT_CAT = {0x8: "weapons", 0x9: "armors", 0xB: "goods"}


## @brief The item id proper is the low 24 bits; the rest is the type code.
SDT_ID_MASK = 0x00FFFFFF


##
# @brief Category refinement for the weapons table, applied at load time.
# @details Sekiro keeps combat arts, prosthetic tools and a pile of engine-internal
# rows in one param table, so one heading for all of them would be useless. The split
# is by id block, read off the table sorted rather than guessed: the prosthetic tools
# are exactly the ids in @c prosthetics.json (the 7xxxx range, one id per upgrade
# tier), the combat arts are the five-digit ids below them, and everything above is
# the skill tree plus the "Virtual Weapon:" / "Upgrade Menu:" internals.
SDT_ARTS_MAX = 9999


def sdt_weapon_cat(iid, prosthetics):
    if iid in prosthetics:
        return "prosthetics"
    return "arts" if iid <= SDT_ARTS_MAX else "skills"


##
# @brief Category refinement for the goods table, by id block.
# @details Same method as @ref sl2.ds3.ds3_goods_cat and the same justification: the
# ids block out cleanly by kind when the table is read in order, so the report can
# mirror the in-game menu instead of dumping 279 rows under one heading. Ranges are
# inclusive on both ends.
SDT_GOODS_RANGES = (
    (500, 1999, "consumables"),    # Spirit Emblem, Regenerative Power, Skill Point
    (2000, 2999, "key"),           # Kusabimaru, Mortal Blade, the esoteric texts
    (3000, 3999, "consumables"),   # gourds, sugars, spiritfall, confetti, shards
    (4000, 4499, "beads"),         # Prayer Bead, the ten necklaces, Gourd Seed
    (5100, 5499, "memories"),      # Memory: / Remnant: — the boss tokens
    (5500, 5999, "key"),           # Mask Fragments, Dragon's Blood Droplet
    (6000, 6999, "upgrade"),       # scrap iron, gunpowder, wax, lapis lazuli
    (9000, 9999, "key"),           # quest items, notes, Rot Essence, shop scrolls
)


def sdt_goods_cat(iid):
    for lo, hi, cat in SDT_GOODS_RANGES:
        if lo <= iid <= hi:
            return cat
    return "goods"


## @brief The db_sdt files that carry real English names, one per item type.
SDT_DB_FILES = ("weapons", "armors", "goods")


##
# @brief Load the Sekiro id tables, type-scoped: @c {category: {id: name}}.
# @details A fourth id scheme, and the simplest of the four: decimal id keys, one file
# per type, no category collisions to design around because the handle nibble already
# says which table to look in.
#
# The @c *_devnames.json files are loaded into their own table and never merged. They
# hold Paramdex's machine-translated Japanese dev strings for the ids with no English
# name ("ID monitoring item 1", "Right-handed sword_style: None"), and most of them are
# engine internals a player never sees — merging them would put debug rows in the
# inventory under the same heading as real items. Anything that resolves only there is
# reported as an internal entry instead, so it is neither hidden nor dressed up.
# @param db_dir Folder holding the tables.
# @return @c {"names": {cat: {id: name}}, "dev": {cat: {id: name}}, "prosthetics": set}.
def load_sdt_db(db_dir):
    def table(stem):
        try:
            with open(os.path.join(db_dir, stem + ".json"), encoding="utf-8") as f:
                return {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            return {}
    names = {cat: table(cat) for cat in SDT_DB_FILES}
    dev = {cat: table(cat + "_devnames") for cat in SDT_DB_FILES}
    return {"names": names, "dev": dev, "prosthetics": set(table("prosthetics"))}


##
# @brief Resolve one item id to @c (name, category, internal).
# @details The type nibble decides which table is consulted, so a lookup cannot cross
# types. A hit in the named table gives the render category; a hit only in the dev-name
# table is flagged @c internal, which is how the caller knows to count it rather than
# print it. A miss in both is left to the caller to count as unknown.
# @param cat  The type from the handle nibble (weapons/armors/goods).
# @param iid  The masked item id.
# @param db   The bundle from @ref load_sdt_db.
def sdt_resolve(cat, iid, db):
    name = db["names"].get(cat, {}).get(iid)
    if name is not None:
        if cat == "weapons":
            return name, sdt_weapon_cat(iid, db["prosthetics"]), False
        if cat == "goods":
            return name, sdt_goods_cat(iid), False
        return name, cat, False
    name = db["dev"].get(cat, {}).get(iid)
    return (name, "internal", True) if name is not None else (None, None, False)


##
# @brief Walk Sekiro's four item lists.
# @details Each region is a flat array of 16-byte records and the game leaves the tail
# zeroed, so an empty record (handle 0) is skipped rather than treated as the end —
# the count that matters is which records carry a known type nibble. That gate is what
# keeps a mis-located region from inventing items: random bytes clear it three times in
# sixteen, and a zeroed tail never clears it at all.
# @param buf The slot payload. @param db The bundle from @ref load_sdt_db.
# @return A generator of @c (which list, name, category, quantity, internal).
def sdt_items(buf, db):
    for which, start, length in SDT_LISTS:
        for off in range(start, start + length, SDT_RECORD):
            handle = u32(buf, off)
            if not handle:
                continue
            cat = SDT_CAT.get((handle >> 28) & 0xF)
            if cat is None:
                continue
            iid = u32(buf, off + 4)
            if iid is None:
                continue
            name, render_cat, internal = sdt_resolve(cat, iid & SDT_ID_MASK, db)
            qty = u32(buf, off + 8)
            yield which, name, render_cat, qty, internal


##
# @brief How many Memories this character has consumed, or None.
# @details Sekiro's boss tokens are Memories, and consuming one at an idol raises
# Attack Power by exactly one — so a stored Attack Power is a COUNT of the Memories
# already spent, which is the one thing no other game in this repo can recover. Every
# other boss floor here goes blind the moment the token is used; this one does not.
#
# Two honest limits, both stated where it is rendered. The base is 1, not 0
# (@ref SDT_ATTACK_BASE), and Attack Power carries across New Game+ while the Memories
# do not, so past journey 0 the number counts every lap rather than this one.
# @param attack The stored attack power, or None. @return The count, or None.
def sdt_memories_spent(attack):
    if attack is None or not SDT_ATTACK_BASE <= attack <= SDT_ATTACK_MAX:
        return None
    return attack - SDT_ATTACK_BASE


##
# @brief Parse one Sekiro slot into the unified character dict.
# @details No name and no attributes: both are absent from the game, not missing from
# the tool, and the report says so rather than leaving a blank. An unused slot is all
# zeros, which is how a populated one is told apart — the game publishes no occupancy
# array, so the test is the slot's own content.
#
# Max HP and max Posture are read from the second of each field's two copies, NOT from
# the offset alfizari names — see @ref sdt_twin for the differential that settles it.
#
# **Spirit emblems** is still deliberately NOT read. The documented @c uint16 at
# @c 0x3459A reads 15 on a character who owns no Spirit Emblem item and has no prosthetic
# at all, and stayed 15 across a window in which the inventory grew by four items — so it
# is the carry CAP (which starts at 15), not the count. It needs a save either side of
# actually spending emblems, and a wrong number is worse than none.
# @param buf The slot payload. @param db The bundle from @ref load_sdt_db.
# @return A unified character dict, or None if the slot is empty.
def sdt_parse(buf, db):
    inv, key_items, memories, unknown, internal = {}, [], [], 0, 0
    for which, name, cat, qty, is_internal in sdt_items(buf, db):
        if name is None:
            unknown += 1
            continue
        if is_internal:
            internal += 1
            continue
        row = (name, qty)
        # The box wins over the category: a key item sitting in storage is in
        # storage, and saying otherwise would report it as carried.
        if which == "storage":
            inv.setdefault("storage", []).append(row)
        elif which == "key" or cat == "key":
            key_items.append(row)
        else:
            inv.setdefault(cat, []).append(row)
            if cat == "memories":
                memories.append(row)

    play_time = u32(buf, SDT_PLAYTIME_OFF)
    steam_id = u64(buf, SDT_STEAM_OFF)
    if not any((inv, key_items, play_time, steam_id)):
        return None

    attack = u32(buf, SDT_ATTACK_OFF)
    if attack is not None and attack > SDT_ATTACK_MAX:
        attack = None
    ng = u8(buf, SDT_NG_OFF)
    ch = {
        "tier": "full", "game": "sdt",
        # Sekiro profiles carry no name — the game never asks for one — so the slot
        # is labelled the same way an empty Elden Ring roster entry is. What that
        # means is said once, in SDT_NOTE, rather than inside every heading and
        # every chart box that has to carry the name.
        "name": "(unnamed)",
        "klass": None, "stats": {}, "level": None, "soul_memory": None,
        "humanity": None, "stamina": None,
        "hp": sdt_twin(buf, SDT_HP_OFF, SDT_HP_ALT),
        "posture": sdt_twin(buf, SDT_POSTURE_OFF, SDT_POSTURE_ALT),
        "ng_plus": ng if ng is not None and ng <= SDT_NG_MAX else None,
        "play_time": play_time,
        "souls": u32(buf, SDT_SEN_OFF),
        "attack": attack,
        "boss_souls": memories, "key_items": key_items,
        "inv": inv, "unknown_count": unknown, "internal_count": internal,
    }
    spent = sdt_memories_spent(attack)
    if spent is not None:
        ch["memories"] = {"spent": spent, "held": len(memories),
                          "cumulative": bool(ch["ng_plus"])}
    return ch


##
# @brief Load the Sekiro boss-defeat flag table (boss name → event flag id).
# @details Shipped for its NAMES, which are the denominator behind "Bosses Defeated
# (N of M tracked)". The flags themselves are NOT read: Sekiro's within-group bit maths
# is the same as DS3's, but where the flag region sits in the SAVE is not published
# anywhere and has not been derived here, so nothing reads them yet. Cached per dir.
_BOSS_FLAG_CACHE = {}


def load_sdt_boss_flags(base_dir):
    if base_dir not in _BOSS_FLAG_CACHE:
        path = os.path.join(base_dir, "db_sdt", "boss_flags.json")
        try:
            with open(path, encoding="utf-8") as f:
                _BOSS_FLAG_CACHE[base_dir] = json.load(f)
        except (OSError, ValueError):
            _BOSS_FLAG_CACHE[base_dir] = {}
    return _BOSS_FLAG_CACHE[base_dir]
