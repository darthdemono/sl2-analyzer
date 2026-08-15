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
SDT_STEAM_OFF = 0x33E54  # u64
SDT_NG_OFF = 0x33F34  # u8, journey (New Game+) count
SDT_PLAYTIME_OFF = 0x33F80  # u32, SECONDS
SDT_ATTACK_OFF = 0x3449C  # u32, attack power
SDT_SEN_OFF = 0x344D0  # u32, Sen (the currency — alfizari's README calls it Souls)


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
# @brief Vitality, the second of Sekiro's two upgrade tracks, at the word immediately
#        before Attack Power.
# @details In no published source at all — it was pinned by the differential the old
# blocker asked for. A 21-second window in which the character used four Prayer Beads
# (the First Prayer Necklace) moved Max HP 320 → 400 and Max Posture 120 → 150, and in
# the whole player struct exactly ONE other word moved: this one, 1 → 2. Every earlier
# save on the same ladder reads 1 with no necklace used, and a characterless save reads
# 0, so the field is not a coincidence of that one window.
#
# The stored value IS the number the status screen shows — no base to subtract, unlike
# @ref SDT_ATTACK_BASE, because a fresh character reads 1 and one necklace makes it 2.
# The ceiling is the in-game cap; past it the read landed somewhere it should not have.
SDT_VITALITY_OFF = 0x34498
SDT_VITALITY_MAX = 20


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


## @brief Ceilings that make a field a field rather than noise: a value past either
#  means the read landed somewhere it should not have, and the field is dropped.
#
#  Attack power was 98 here and that was one too low — a real journey-9 save reads
#  exactly 99, so the tool was silently dropping Attack Power, and with it the Memories
#  line, on precisely the characters that have the most of it. Raised on that evidence.
#  The gate exists to reject a read in the thousands, not to tell 98 from 99.
#
#  Note the Memories arithmetic UNDERCOUNTS at the cap, because Attack Power stops
#  rising while the kills do not. It is a floor, which is what the line already says.
SDT_ATTACK_MAX, SDT_NG_MAX = 99, 99


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
    (500, 1999, "consumables"),  # Spirit Emblem, Regenerative Power, Skill Point
    (2000, 2999, "key"),  # Kusabimaru, Mortal Blade, the esoteric texts
    (3000, 3999, "consumables"),  # gourds, sugars, spiritfall, confetti, shards
    (4000, 4499, "beads"),  # Prayer Bead, the ten necklaces, Gourd Seed
    (5100, 5499, "memories"),  # Memory: / Remnant: — the boss tokens
    (5500, 5999, "key"),  # Mask Fragments, Dragon's Blood Droplet
    (6000, 6999, "upgrade"),  # scrap iron, gunpowder, wax, lapis lazuli
    (9000, 9999, "key"),  # quest items, notes, Rot Essence, shop scrolls
)


def sdt_goods_cat(iid):
    for lo, hi, cat in SDT_GOODS_RANGES:
        if lo <= iid <= hi:
            return cat
    return "goods"


##
# @brief Rows that resolve to a real name but are engine state, not inventory.
# @details Sekiro has no armour system, so `EquipParamProtector` is not an equipment
# table at all — it is the model list for the character's own body. Every row that is
# one of Wolf's own parts (`Original Memory: Wolf - Head`, and the cutscene rig beside
# it) is the engine recording which mesh is on, and printing them gave every export an
# `#### Armor` heading listing the player's limbs.
#
# The `Another's Memory:` blocks — Shura, Ashina, Tengu — are NOT suppressed, and that
# is deliberate rather than cautious. They look like the three unlockable attires, and
# no save here has one unlocked, so suppressing them would be a claim about a channel
# this repo has never observed carrying anything. Leaving them in costs nothing: the
# heading is only emitted when a row survives, so a character who has none prints no
# section, and an NG+ save will simply show them if they do surface. If they never do,
# nothing was lost either way.
#
# `Virtual Weapon:` restates a Combat Art already listed under its own name, and
# `Upgrade Menu:` rows are prosthetic upgrade-tree entries. Both are duplicates of a
# real row rather than items.
#
# Suppressed rows are counted, not hidden — see @c suppressed_count.
SDT_SUPPRESSED_PREFIXES = (
    "Original Memory:",
    "Immortal Severance Cutscene",
    "Virtual Weapon:",
    "Upgrade Menu:",
)


def sdt_suppressed(name):
    return name.startswith(SDT_SUPPRESSED_PREFIXES)


## @brief Skill points are a spendable currency, not a consumable, so the report puts
#  them beside Attack Power and Vitality instead of in with the sugars and the gourds.
SDT_SKILL_POINT_ID = 1200


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
# @return A generator of @c (which list, item id, name, category, quantity, internal).
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
            iid &= SDT_ID_MASK
            name, render_cat, internal = sdt_resolve(cat, iid, db)
            qty = u32(buf, off + 8)
            yield which, iid, name, render_cat, qty, internal


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
    suppressed, skill_points = 0, None
    for which, iid, name, cat, qty, is_internal in sdt_items(buf, db):
        if name is None:
            unknown += 1
            continue
        if is_internal:
            internal += 1
            continue
        if sdt_suppressed(name):
            suppressed += 1
            continue
        # A skill point is spendable currency, so it rides in the header beside the
        # other two upgrade tracks rather than in with the sugars. Only a CARRIED one
        # is promoted — a copy sitting in the box is genuinely in the box, and the
        # storage list would otherwise lose it with nothing saying so.
        if iid == SDT_SKILL_POINT_ID and which != "storage":
            skill_points = (skill_points or 0) + (qty or 0)
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
    vitality = u32(buf, SDT_VITALITY_OFF)
    if vitality is not None and not 1 <= vitality <= SDT_VITALITY_MAX:
        vitality = None
    ch = {
        "tier": "full",
        "game": "sdt",
        # Sekiro profiles carry no name — the game never asks for one — so the slot
        # is labelled the same way an empty Elden Ring roster entry is. What that
        # means is said once, in SDT_NOTE, rather than inside every heading and
        # every chart box that has to carry the name.
        "name": "(unnamed)",
        "klass": None,
        "stats": {},
        "level": None,
        "soul_memory": None,
        "humanity": None,
        "stamina": None,
        "hp": sdt_twin(buf, SDT_HP_OFF, SDT_HP_ALT),
        "posture": sdt_twin(buf, SDT_POSTURE_OFF, SDT_POSTURE_ALT),
        "ng_plus": ng if ng is not None and ng <= SDT_NG_MAX else None,
        "play_time": play_time,
        "souls": u32(buf, SDT_SEN_OFF),
        "attack": attack,
        "vitality": vitality,
        "skill_points": skill_points,
        "boss_souls": memories,
        "key_items": key_items,
        "inv": inv,
        "unknown_count": unknown,
        "internal_count": internal,
        "suppressed_count": suppressed,
    }
    spent = sdt_memories_spent(attack)
    if spent is not None:
        ch["memories"] = {
            "spent": spent,
            "held": len(memories),
            "cumulative": bool(ch["ng_plus"]),
        }
    return ch


##
# @brief Load the Sekiro boss-defeat flag table (boss name → event flag id).
# @details Also the source of the "of N tracked" denominator, via @c boss_roster — it
# names two bosses the Memory table alone would miss. Cached per dir.
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


##
# @brief Slot offset of the global event-flag category.
# @details Sekiro serialises its flags exactly the way Dark Souls III does — this repo
# has had that arithmetic since the DS3 bonfire work — and the only thing nobody
# published was where the region lands in the FILE. It is here, at a fixed slot offset
# like every other Sekiro field: ten 128-byte blocks of 1000 flags each, the id's
# thousands digit picking the block and its last three digits addressing a bit inside
# that block MSB-first.
#
# DERIVED, not ported. A save pair whose only act was killing Gyoubu Masataka Oniwa
# leaves his flag `9301` as the single bit in the slot that goes 0 → 1, reads 0 in all
# ten earlier saves on the ladder, and lights none of the other fourteen bosses — and it
# is the only such candidate that also sits on the `0x500` grid the rest of the region
# is spaced on. SoulSplitter, where the bit arithmetic comes from, reads process memory
# and never opens a save, which is why this had to be measured.
#
# The PER-BLOCK packing is the part worth stating, because the obvious alternative is
# wrong and looks right on every idol: read `9301` as the 9301st flag of one flat
# `0x500` span and it lands 29 bytes early, on a byte that never moves in any save here.
# An idol id's thousands digit is always 0, so idols cannot tell the two apart; a boss
# can.
SDT_FLAG_REGION = 52
## @brief Bytes per category. Ten blocks, so ten thousand flags.
SDT_FLAG_CATEGORY = 0x500
## @brief Bytes per flag block — 1000 flags at one bit each, rounded up to the word.
SDT_FLAG_BLOCK = 128
## @brief Flags the global category holds. Ten blocks of a thousand.
SDT_FLAG_GLOBAL_MAX = 10000


##
# @brief Each map's category index on the grid.
# @details MEASURED, and the gaps are the finding rather than a hole: the maps are in
# sorted order but do NOT sit in consecutive slots, because 6, 7, 10 and 12 belong to
# maps with no Sculptor's Idol in them, which no table here can see. Guessing them
# consecutive is exactly what a first pass did, and it read a save that had finished the
# game as having never lit a lamp in Fountainhead Palace.
#
# Six of the nine are identified outright by how many idols the category reports — one
# past its highest set bit — which is unique for that map. The two ties were broken
# two-sidedly rather than by preference. `(11,2)` against `(13,0)`: the local run walked
# the Ashina Reservoir in the prologue and has never entered the Abandoned Dungeon, and
# reads 18 nonzero bytes in one against 0 in the other. `(17,0)` against `(25,0)`: on a
# third-party checkpoint pack, one reads nine idols both before and after Owl while the
# other reads zero then nine — and Fountainhead is the map you cannot reach until Owl is
# dead.
SDT_FLAG_MAPS = {
    (10, 0): 2,
    (11, 0): 3,
    (11, 1): 4,
    (11, 2): 5,
    (13, 0): 8,
    (15, 0): 9,
    (17, 0): 11,
    (20, 0): 13,
    (25, 0): 14,
}


##
# @brief Byte offset and bit of an event flag, or None where it cannot be placed.
# @details The global category is `k=0` and holds ids 0..9999; a per-map flag is keyed by
# the id's area and sub-area, and `k=1` is a second global-looking category that nothing
# in either shipped table lands in, so it is left alone.
#
# THE `< SDT_FLAG_GLOBAL_MAX` GUARD IS LOAD-BEARING, not a tidy bounds check. SoulSplitter's
# runtime addressing selects a top-level group on `(id // 10000000) % 10` before it ever
# looks at the area, so the id families do not share one flat space. Item-pickup flags are
# `50000000 + item lot id`, and `area` and `sub` both come out ZERO on one of those — which
# sends it down the global branch, where without the guard it would alias onto a real
# global flag in the 0..9999 range and read somebody else's bit. The guard turns that into
# an honest None. Whether the group-5 family is even inside this region is unmeasured;
# there ARE further populated categories past the nine maps (k=35..46 at least), and
# nothing published names a single flag in them.
# @param fid The event flag id. @return @c (offset, bit) or None.
def sdt_flag_offset(fid):
    area, sub = (fid // 100000) % 100, (fid // 10000) % 10
    if area >= 90 or area + sub == 0:
        if not 0 <= fid < SDT_FLAG_GLOBAL_MAX:
            return None
        k = 0
    else:
        k = SDT_FLAG_MAPS.get((area, sub))
        if k is None:
            return None
    n = fid % 1000
    block = (
        SDT_FLAG_REGION + k * SDT_FLAG_CATEGORY + (fid // 1000) % 10 * SDT_FLAG_BLOCK
    )
    return block + (n >> 5) * 4 + 3 - ((n & 31) >> 3), 7 - (n & 7)


##
# @brief Which slots the game itself considers occupied: menu entry, one byte per slot.
# @details Sekiro DOES publish an occupancy array after all, and this repo spent a long
# time working around its absence by judging a slot from its own content (play time,
# Steam id, any item). `mi5hmash/SL2Bonfire` carries the offset in its per-game profile
# — `UserDataFileNumber` 10, `SlotsOccupancyOffset` 212 — and it is strictly better than
# the content test, because content cannot tell a live character from a DELETED one.
#
# That is not theoretical: a third-party "100% complete" save reads three slots by
# content and one by the array, and the two extra are ghosts the game does not show.
# Exactly the DS2 case, where deleting a character clears the menu entry and leaves the
# block intact — so Sekiro gets the same treatment DS2 already had.
#
# Degrades the same way DS2's does: an unreadable array, a byte that is not 0/1, or an
# array claiming nothing is occupied all return None, which turns the filter OFF rather
# than hiding real characters behind a moved offset.
# @param data The full file bytes. @param entries The BND4 entries. @param decrypt The
#        game's own decrypt callable. @return A set of slot indices, or None.
SDT_MENU_ENTRY = 10
SDT_OCCUPANCY_OFF = 212


def sdt_active_slots(data, entries, decrypt):
    if len(entries) <= SDT_MENU_ENTRY:
        return None
    e = entries[SDT_MENU_ENTRY]
    menu = decrypt(data[e.offset : e.offset + e.size])
    if menu is None:
        return None
    active = set()
    for i in range(SDT_SLOT_COUNT):
        byte = u8(menu, SDT_OCCUPANCY_OFF + i)
        if byte is None or byte > 1:
            return None
        if byte:
            active.add(i)
    return active or None


##
# @brief Load the miniboss table (area → [[entity id, name]]). Cached per dir.
# @details The entity id IS the defeat flag in Sekiro — not the separate per-map block
# Dark Souls III uses — which is why this table needs no flag column. Measured, not
# assumed; see `tools/gen_sdt_minibosses.py` and the change log for the four checks.
_MINIBOSS_CACHE = {}


def load_sdt_minibosses(base_dir):
    if base_dir not in _MINIBOSS_CACHE:
        path = os.path.join(base_dir, "db_sdt", "minibosses.json")
        try:
            with open(path, encoding="utf-8") as f:
                _MINIBOSS_CACHE[base_dir] = json.load(f)
        except (OSError, ValueError):
            _MINIBOSS_CACHE[base_dir] = {}
    return _MINIBOSS_CACHE[base_dir]


## @brief Load the Sculptor's Idol table (area → [[flag id, name]]). Cached per dir.
_IDOL_CACHE = {}


def load_sdt_idols(base_dir):
    if base_dir not in _IDOL_CACHE:
        path = os.path.join(base_dir, "db_sdt", "idols.json")
        try:
            with open(path, encoding="utf-8") as f:
                _IDOL_CACHE[base_dir] = json.load(f)
        except (OSError, ValueError):
            _IDOL_CACHE[base_dir] = {}
    return _IDOL_CACHE[base_dir]


## @brief Read one event flag. None where the id cannot be placed or the slot is
#  too short — never a raw index, same as every other read in this module.
def sdt_flag(buf, fid):
    at = sdt_flag_offset(fid)
    if at is None:
        return None
    byte = u8(buf, at[0])
    return None if byte is None else (byte >> at[1]) & 1


##
# @brief Read Sekiro's event flags: boss defeats into @c ch["bosses"] as `flag`
#        evidence, and the Sculptor's Idols into @c ch["bonfire_areas"].
# @details Must run AFTER @c attach_defeated_bosses, which refuses to do anything once
# `bosses` exists — build the Memory floor first, then lay the flags on top. Getting
# that order wrong silently drops the held-Memory kills, which is the trap DS1 already
# fell into once.
#
# The boss half is what finally lets Sekiro report a kill it can PROVE rather than
# infer: the Memory arithmetic counts tokens spent and the Memory items count tokens
# held, but neither names the boss — a held Memory resolves as a bare "Memory". A flag
# names it, and it never clears within a journey.
#
# Idols go into `bonfire_areas` rather than a field of their own, in DS3's
# `[(area, count, [names], total, [missing])]` shape, so the render, the totals and the
# combined timeline all take them with no new code — the same thing DS1's bonfire list
# does. The rows follow `idols.json`'s own area order, which is why two of its keys map
# into one flag category and one category feeds two keys: the areas are the game's, the
# categories are the map files'.
# @param ch A parsed character. @param buf The slot. @param base_dir Repo root.
def sdt_attach_flags(ch, buf, base_dir):
    bosses = ch.get("bosses") or {}
    for name, fid in load_sdt_boss_flags(base_dir).items():
        if sdt_flag(buf, fid):
            bosses[name] = sorted(set(bosses.get(name, ())) | {"flag"})
    if bosses:
        ch["bosses"] = bosses
    areas, any_lit = [], False
    for area, idols in load_sdt_idols(base_dir).items():
        named, missing = [], []
        for fid, name in idols:
            (named if sdt_flag(buf, int(fid)) else missing).append(name)
        any_lit = any_lit or bool(named)
        areas.append((area, len(named), named, len(idols), missing))
    # Every area is kept, lit or not — an area reading 0/9 is the useful half. Only a
    # character who has lit nothing anywhere gets no section, which is right: they are
    # minutes from the opening and have not reached an idol.
    if any_lit:
        ch["bonfire_areas"] = areas
    # Minibosses, in the BONFIRE shape (area, count, names, total, missing) rather than
    # the pickup one, because a miniboss is a named kill and the reader wants to know
    # WHICH — the same thing the boss section prints. Both lists want collapsing by name
    # on the way out, because four of these really are "Shura Samurai" at four different
    # entity ids and printing the name four times is faithful but unreadable.
    minis, any_dead = [], False
    for area, enemies in load_sdt_minibosses(base_dir).items():
        dead, alive = [], []
        for eid, name in enemies:
            (dead if sdt_flag(buf, int(eid)) else alive).append(name)
        any_dead = any_dead or bool(dead)
        minis.append((area, len(dead), dead, len(enemies), alive))
    if any_dead:
        ch["minibosses"] = minis
