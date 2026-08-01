"""Dark Souls II, vanilla and Scholar of the First Sin.
"""
import json
import os
from collections import defaultdict, OrderedDict
from .reader import is_valid_name, read_utf16, u16, u32, u8
from .crypto import decrypt_ds2
from .itemdb import merge_qty


## @brief The two DS2 releases. Vanilla (the DX9 original) and Scholar of the First
#  Sin share the ENTIRE save layout — only the AES key differs. Verified field by
#  field on a real DARKSII0000.sl2 against a real DS2SOFS0000.sl2: identical BND4
#  entry count and sizes (bar one non-character block), the name at DS2_NAME_OFF, and
#  DS2's own level identity (sum of the nine attributes minus level == 53) holding on
#  both. So every DS2 table below is shared; anything keyed by game id resolves
#  vanilla through DS2_FAMILY rather than carrying a duplicate entry.
DS2_GAMES = ("ds2sotfs", "ds2vanilla")


## @brief Game id to the id whose lookup tables it uses (attribute reference, derived
#  stats, themes). DS1's two releases already collapse this way; DS2's now do too.
DS2_FAMILY = {"dsr": "ds1", "ptde": "ds1", "ds2vanilla": "ds2sotfs"}


## @brief DS2 character-slot offsets (absolute, into decrypted game data).
DS2_NAME_OFF, DS2_SOULS_OFF, DS2_SOULMEM_OFF, DS2_HP_OFF, DS2_NG_OFF = 960, 60, 64, 72, 1028


## @brief DS2 header (BND4 entry 0) title-list layout: each menu slot's name sits at
#  DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * title_index. Block entry i maps to title
#  index (i - slots.start). Used to tell active characters from deleted ghosts.
DS2_TITLE_NAME_OFF, DS2_TITLE_STRIDE = 1286, 496


## @brief Play time (u32 seconds) inside a header title record: name is at record
#  base +0, the play-time counter at +66. Pinned by a real ~1-minute differential
#  pair (40:10:25 → 40:11:27, the u32 rose by exactly 62). Per-character, since each
#  title record is one slot. This is DS2's play time, which no editor exposed and an
#  earlier differential missed; it lives in the header, not the character block.
DS2_TITLE_PLAYTIME_OFF = 66


## @brief Starting class (byte) and current covenant (byte) offsets in the slot
#  block. Pinned by differential saves: class read 2 (Knight) on one character and
#  8 (Explorer) on another at +1024; covenant read 3 (Brotherhood of Blood) then 0
#  (None) after leaving the covenant at +189, cross-checked against a third char.
DS2_CLASS_OFF, DS2_COVENANT_OFF = 1024, 189


## @brief DS2 starting-class and covenant id→name (from the SOTFS Cheat Engine table
#  dropdowns). Id 0 / unknown is absent, so `.get` yields None and the field is
#  omitted rather than shown wrong. Covenant 0 = not in a covenant (omitted).
DS2_CLASS = {1: "Warrior", 2: "Knight", 4: "Bandit", 6: "Cleric", 7: "Sorcerer",
             8: "Explorer", 9: "Swordsman", 10: "Deprived"}


DS2_COVENANT = {1: "Heirs of the Sun", 2: "Blue Sentinels", 3: "Brotherhood of Blood",
                4: "Way of Blue", 5: "Rat King", 6: "Bell Keepers",
                7: "Dragon Remnants", 8: "Company of Champions", 9: "Pilgrims of Dark"}


## @brief Per-covenant discovered flag and rank, as two dense byte runs in covenant-id
#  order just past the current-covenant byte. DS2S-META puts CurrentCovenant at 0x1AD
#  with Discovered at 0x1AF.. and Rank at 0x1B9.., so relative to our own (differential-
#  verified) DS2_COVENANT_OFF the runs start +2 and +12 — the absolute bases differ
#  between that editor and this tool, but the layout inside the struct does not.
#  Checked across Joy's ladder: the flags read a clean 0/1, rank is never nonzero for
#  an undiscovered covenant, and the only two she ranked to 3 are Way of Blue and
#  Pilgrims of Dark — the two cheapest ladders in the game (1/5/10 and 1/2/3).
DS2_COV_DISC_D, DS2_COV_RANK_D, DS2_COV_MAX_RANK = 2, 12, 3


## @brief Gender (u8) and hollowing level (u8) offsets in the slot block. From the
#  Jappi88 DS2 save editor: its player block reads Gender then HollowLv at block[0]
#  0x15A/0x15B, and that block starts at slot flat +32 (Level/Souls/Soul-Memory/Health
#  line up), so Gender is 0x15A+32 = 378 and HollowLv 0x15B+32 = 379. HollowLv verified
#  on a 30h character (Hollow Lv 1). Gender polarity verified by a real F→M differential
#  save pair (the byte flipped 1→0), so 1 = Female, 0 = Male.
DS2_GENDER_OFF, DS2_HOLLOW_OFF = 378, 379


## @brief Total deaths (u32) in the slot block. Pinned by a real 201→202 death
#  differential: the u32 rose by exactly 1, and it climbs monotonically with play time
#  across the whole backup set (181 at 37h → 202 at 40.4h), reaching the labelled death
#  counts. DS2 mirrors it at three offsets (+104, +184, +7272) that always agree; +104
#  is used. This is the deaths counter no editor exposed and an earlier differential
#  could not find in the player region.
DS2_DEATHS_OFF = 104


## @brief DS2 gender enum. Female = 1, Male = 0 (see DS2_GENDER_OFF). Any other value
#  yields None via `.get` and the field is omitted rather than shown wrong.
DS2_GENDER = {0: "Male", 1: "Female"}


## @brief Bonfire (rest-point) progression lives in a separate WORLD block, not the
#  character-status block. In the SOTFS `.sl2` the world block for status entry i is
#  entry i + DS2_WORLD_ENTRY_DELTA. Inside it (per the Jappi88 editor's MapData: ids
#  at block 0x1598, unlock flags at 0x1798) a contiguous u16 array of bonfire ids is
#  followed DS2_BONFIRE_FLAG_DELTA bytes later by one unlock byte each. The array's
#  slot offset is not fixed across saves, so it is found by content (a long run of
#  known bonfire ids). Verified: a fresh mule shows 1 bonfire (the start), a 30h save
#  shows 49 across the whole game.
DS2_WORLD_ENTRY_DELTA, DS2_BONFIRE_FLAG_DELTA, DS2_BONFIRE_MIN_RUN = 10, 0x200, 16


## @brief DS2 attribute offsets (uint16 each), in display order; Level last.
#  Adaptability, Intelligence and Faith are NOT stored in display order: memory
#  keeps Intelligence @44, Faith @46, Adaptability @48 (verified against a known
#  SL88 character whose real ADP/INT/FTH were 15/3/6 but read out as 3/6/15 under
#  the naive contiguous mapping). The dict below lists them in display order with
#  their true offsets, so the table reads ADP, INT, FTH while pointing at 48/44/46.
DS2_STAT_OFF = OrderedDict([
    ("Vigor", 32), ("Endurance", 34), ("Vitality", 36), ("Attunement", 38),
    ("Strength", 40), ("Dexterity", 42), ("Adaptability", 48),
    ("Intelligence", 44), ("Faith", 46), ("Level", 0x38)])


## @brief DS2 derived-stat bases (values BEFORE rings/equipment). Each derived stat is
#  a pure function of one/two attributes, verified byte-exact against a real save's
#  in-game Level-Up screen (Lv155 char: END 31 -> 131 stamina, VIT 30 -> 83.0 equip
#  load, ADP 20 / ATN 4 -> 96 agility / 11 roll i-frames). Unlike HP — which carries a
#  class/base offset the flat table misses (so HP is read from the save, not computed;
#  see STAT_CAPS note) — these three start from a universal base with no class variance,
#  so the formula reproduces the game exactly. Sources: fextralife Endurance /
#  Equipment Load / Agility pages.
DS2_STAMINA_BASE, DS2_EQUIP_BASE, DS2_AGL_BASE = 80, 38.5, 80


## @brief Roll i-frames by Agility value (fextralife/community breakpoints). Look up the
#  highest key <= AGL; below 85 the count is undocumented, so i-frames are omitted there.
DS2_IFRAMES = OrderedDict([(85, 5), (86, 8), (88, 9), (92, 10), (96, 11),
                           (99, 12), (105, 13), (111, 14), (114, 15), (116, 16)])


## @brief Attunement values at which a spell slot is unlocked (fextralife Attunement).
#  Slot count = how many of these are <= ATN. ATN 4 -> 0 slots (first slot at 10).
DS2_SLOT_BREAKS = (10, 13, 16, 20, 25, 30, 40, 50, 60, 75, 94)


## @brief Physical attack bonus (ATK: Str / ATK: Dex) by stat value — decade
#  breakpoints of the weapon-independent curve (the weapon then applies its own scaling
#  on top). Base 50 at 0, soft caps 40/50/80. From the DS2 wikidot/fextralife scaling
#  table; verified STR 50 -> 155 and DEX 16 -> 70 (interpolated) against a real save.
#  ATK: Str and ATK: Dex share this identical curve.
DS2_PHYS_ATK_BP = OrderedDict([(0, 50), (10, 57), (20, 80), (30, 102), (40, 140),
                               (50, 155), (60, 162), (70, 170), (80, 185),
                               (90, 192), (99, 200)])


## @brief Shared elemental-defence curve breakpoint rates (per stat point): +6 (1-10),
#  +8 (11-20), +1 (21-60), +0.5 (61-99); base 0. Magic DEF uses INT, Lightning DEF FTH,
#  Dark DEF min(INT,FTH), Fire DEF the floor-average of INT & FTH ("scales with both").
#  Verified: INT 3 -> Magic DEF 18, FTH 10 -> Lightning DEF 60, min 3 -> Dark DEF 18,
#  avg 6 -> Fire DEF 36. (fextralife Magic/defence pages.)
## @brief DS2 inventory regions (start, end); 16-byte slots throughout.
DS2_INV_RANGE, DS2_KEY_RANGE = (0x1E2C, 0x10E1C), (0x10E30, 0x11DF0)


## @brief DS2 categories whose slot +8 field is a real count (float durability
#         elsewhere). Weapons/armour/rings/emotes are one instance per slot.
DS2_STACKABLE = {"consumables", "online", "bolts", "spells", "upgrade", "keys",
                 "bosssouls"}


## @brief Categories whose slot +12 field carries a reinforcement level. Only
#  weapons and armour reinforce in DS2; other categories keep other state there.
DS2_UPGRADEABLE = {"weapons", "armors"}


## @brief Byte offsets inside the uint32 upgrade field of a 16-byte item record:
#  the LOW byte (+12) is the reinforcement level (0..10); the next byte (+13) is the
#  infusion id. Both verified on a mule save whose high bytes were 1/2/3/4/8.
DS2_REINF_OFF, DS2_INFUSE_OFF = 12, 13


## @brief DS2 infusion ids to names. From Atvaark's DS2 SOTFS Cheat Engine guide
#  attachments (the "Infusion IDs" list). 0 (None) carries no prefix.
DS2_INFUSION = {1: "Fire", 2: "Magic", 3: "Lightning", 4: "Dark", 5: "Poison",
                6: "Bleed", 7: "Raw", 8: "Enchanted", 9: "Mundane"}


## @brief The four DS2 "Old" great souls (from the Lost Sinner, the Rotten, the
#  Old Iron King, and the Duke's Dear Freja). The game treats these apart from the
#  ordinary boss souls, so the output does too.
DS2_GREAT_SOULS = {"Old Witch Soul", "Old Dead One Soul", "Old King Soul",
                   "Old Paledrake Soul"}


## @brief Read a DS2 name, or None for an empty slot.
def ds2_name(buf):
    name = read_utf16(buf, DS2_NAME_OFF, 16)
    return name if is_valid_name(name) else None


##
# @brief Sort both DS2 inventory regions into categories.
# @return @c (buckets, unknown_count).
def ds2_inventory(buf, item_db):
    buckets, unknown = defaultdict(list), 0
    for start, end in (DS2_INV_RANGE, DS2_KEY_RANGE):
        o = start
        while o + 16 <= min(end, len(buf)):
            # Count is the low uint16 of the +8 field, not a full uint32: special
            # items pack extra state into the high two bytes. The Estus Flask keeps
            # its current/max charges there, e.g. 01 00 07 07 = one flask, 7/7
            # charges. No stackable count exceeds 65535, so the low uint16 is the
            # real total, and the high two bytes are the flask's charge pair.
            iid, qty = u32(buf, o), u16(buf, o + 8)
            cur, mx = u8(buf, o + 10), u8(buf, o + 11)
            reinf = u8(buf, o + DS2_REINF_OFF)
            infuse = u8(buf, o + DS2_INFUSE_OFF)
            o += 16
            if not iid:
                continue
            info = item_db.get(iid)
            if info is None:
                unknown += 1
                continue
            name, cat = info
            if name == "Estus Flask" and mx:
                name = f"{name} ({cur}/{mx} charges)"
            if cat in DS2_UPGRADEABLE:
                # Reinforcement and infusion are baked into a separate record field,
                # not the id (unlike DS1), so a +10 weapon carries the plain base id.
                # Prefix the infusion (weapons only — armour cannot be infused) and
                # suffix the +N level; the id table stays base-keyed.
                if cat == "weapons" and infuse in DS2_INFUSION:
                    name = f"{DS2_INFUSION[infuse]} {name}"
                if reinf:
                    name = f"{name} +{reinf}"
            buckets[cat].append((name, qty if cat in DS2_STACKABLE else 1))
    return buckets, unknown


## @brief Physical attack bonus (ATK: Str/Dex) at a stat value: linear-interpolate the
#  decade breakpoints of @ref DS2_PHYS_ATK_BP, floored to the game's integer display.
def ds2_phys_atk(stat):
    stat = max(0, min(stat, 99))
    lo = min((stat // 10) * 10, 90)
    hi = 99 if lo == 90 else lo + 10
    vlo, vhi = DS2_PHYS_ATK_BP[lo], DS2_PHYS_ATK_BP[hi]
    return vlo if hi == lo else int(vlo + (vhi - vlo) * (stat - lo) / (hi - lo))


## @brief Shared DS2 elemental-defence curve: +6/pt to 10, +8/pt to 20, +1/pt to 60,
#  +0.5/pt (one every other) to 99. Base 0. See @ref DS2_PHYS_ATK_BP note for the map.
def ds2_elem_def(stat):
    stat = max(0, min(stat, 99))
    d = 6 * min(stat, 10)
    if stat > 10:
        d += 8 * (min(stat, 20) - 10)
    if stat > 20:
        d += 1 * (min(stat, 60) - 20)
    if stat > 60:
        d += (min(stat, 99) - 60) // 2  # +0.5/pt = one point every other level
    return d


##
# @brief Compute DS2 base derived stats from the attribute block.
# @details Base = before rings/equipment; the in-game screen adds ring/gear bonuses on
#  top (e.g. a +HP ring, a load ring). Stamina, equip load and agility are pure
#  attribute functions verified against a real save; i-frames come from the agility
#  breakpoint table (@ref DS2_IFRAMES), omitted below AGL 85 (undocumented).
# @return dict: stamina (int), equip_load (float), agility (int), iframes (int|None).
def ds2_derived_stats(stats):
    end = stats.get("Endurance", 0) or 0
    vit = stats.get("Vitality", 0) or 0
    adp = stats.get("Adaptability", 0) or 0
    atn = stats.get("Attunement", 0) or 0
    stg = stats.get("Strength", 0) or 0
    dex = stats.get("Dexterity", 0) or 0
    intel = stats.get("Intelligence", 0) or 0
    fth = stats.get("Faith", 0) or 0
    stamina = DS2_STAMINA_BASE + 2 * min(end, 20) + max(0, min(end, 99) - 20)
    if end >= 99:
        stamina += 1  # the 98->99 step is +2, not +1
    load = DS2_EQUIP_BASE + 1.5 * min(vit, 29)
    if vit > 29:
        load += 1.0 * (min(vit, 49) - 29)
    if vit > 49:
        load += 0.5 * (min(vit, 70) - 49)
    if vit > 70:
        load += 0.5 * ((min(vit, 99) - 70) // 2)  # +0.5 per two points past 70
    agl = DS2_AGL_BASE + int(0.75 * adp + 0.25 * atn + 1e-9)
    iframes = None
    for k, v in DS2_IFRAMES.items():
        if agl >= k:
            iframes = v
    slots = sum(1 for b in DS2_SLOT_BREAKS if atn >= b)
    # Base poise: scales on the LOWER of Endurance/Adaptability. 0.3/pt to 30, 0.2 to
    # 50, 0.1 to 98, +0.2 at 99. Verified: min(END31,ADP20)=20 -> 0.3*20 = 6.0.
    n = min(end, adp)
    poise = 0.3 * min(n, 30)
    if n > 30:
        poise += 0.2 * (min(n, 50) - 30)
    if n > 50:
        poise += 0.1 * (min(n, 98) - 50)
    if n >= 99:
        poise += 0.2
    return {"stamina": stamina, "equip_load": load, "agility": agl,
            "iframes": iframes, "slots": slots, "poise": poise,
            "atk_str": ds2_phys_atk(stg), "atk_dex": ds2_phys_atk(dex),
            "magic_def": ds2_elem_def(intel), "fire_def": ds2_elem_def((intel + fth) // 2),
            "lightning_def": ds2_elem_def(fth), "dark_def": ds2_elem_def(min(intel, fth))}


##
# @brief Every DS2 covenant the character has discovered, with its rank.
# @details Two dense byte runs in covenant-id order (@ref DS2_COV_DISC_D /
# @ref DS2_COV_RANK_D past the current-covenant byte). Both runs are validated as a
# whole before anything is returned — a discovered flag must be 0 or 1, a rank must be
# 0..3, and a rank cannot be nonzero where the covenant was never discovered. If any
# of that fails the offsets have moved, so the feature turns itself off rather than
# printing a wrong rank.
# @return An OrderedDict {covenant: [description]}, or None.
def ds2_covenants(buf):
    out = OrderedDict()
    for cid, name in sorted(DS2_COVENANT.items()):
        disc = u8(buf, DS2_COVENANT_OFF + DS2_COV_DISC_D + cid - 1)
        rank = u8(buf, DS2_COVENANT_OFF + DS2_COV_RANK_D + cid - 1)
        if disc is None or rank is None or disc > 1 or rank > DS2_COV_MAX_RANK:
            return None
        if rank and not disc:
            return None
        if disc:
            out[name] = [f"rank {rank} of {DS2_COV_MAX_RANK}" if rank else "discovered"]
    return out or None


## @brief Parse one DS2 slot into the unified character dict, or None if empty.
#  @param game Which DS2 release this slot came from. The layout is identical for
#              both (see DS2_GAMES), so this only labels the output.
def ds2_parse(buf, item_db, game="ds2sotfs"):
    if ds2_name(buf) is None:
        return None
    stats = OrderedDict((k, u16(buf, o) or 0) for k, o in DS2_STAT_OFF.items())
    buckets, unknown = ds2_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    return {
        "tier": "full", "game": game, "name": ds2_name(buf),
        "klass": DS2_CLASS.get(u8(buf, DS2_CLASS_OFF)),
        "covenant": DS2_COVENANT.get(u8(buf, DS2_COVENANT_OFF)),
        "covenants": ds2_covenants(buf),
        "gender": DS2_GENDER.get(u8(buf, DS2_GENDER_OFF)),
        "level": stats.pop("Level"), "stats": stats,
        "souls": u32(buf, DS2_SOULS_OFF), "soul_memory": u32(buf, DS2_SOULMEM_OFF),
        "humanity": None, "stamina": None, "hp": u32(buf, DS2_HP_OFF),
        "ng_plus": max(0, (u16(buf, DS2_NG_OFF) or 1) - 1),
        "hollow_lvl": u8(buf, DS2_HOLLOW_OFF),
        "deaths": u32(buf, DS2_DEATHS_OFF),
        # DS2 boss souls are a real inventory category (bosssouls), rendered and
        # graded there, so the top boss-souls section is left empty for DS2.
        "boss_souls": [], "key_items": inv.pop("keys", []),
        "inv": inv, "unknown_count": unknown,
    }


## @brief Load the DS2 bonfire id→name table (db_ds2/bonfires.json, keyed by the
#  low-16-bit id as 4-hex). Cached after first read. Returns {} if the file is absent.
_DS2_BONFIRE_CACHE = {}


def load_ds2_bonfires(base_dir):
    if base_dir not in _DS2_BONFIRE_CACHE:
        path = os.path.join(base_dir, "db_ds2", "bonfires.json")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            _DS2_BONFIRE_CACHE[base_dir] = {int(k, 16): v for k, v in raw.items()}
        except (OSError, ValueError):
            _DS2_BONFIRE_CACHE[base_dir] = {}
    return _DS2_BONFIRE_CACHE[base_dir]


## @brief Load the DS2 bonfire→area table (db_ds2/bonfire_areas.json): bonfire id →
#  the area it belongs to, so discovered bonfires group the way DS1's and DS3's do
#  instead of listing 77 flat names. Generated from the fextralife Bonfires page,
#  which lists every bonfire under its location; the two bonfires sharing the name
#  "Tower of Prayer" are split by the id's own map cluster. Cached. Returns {} if
#  absent, and the grouping then falls back to the flat list.
_DS2_AREA_CACHE = {}


def load_ds2_bonfire_areas(base_dir):
    if base_dir not in _DS2_AREA_CACHE:
        path = os.path.join(base_dir, "db_ds2", "bonfire_areas.json")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            _DS2_AREA_CACHE[base_dir] = {int(k, 16): v for k, v in raw.items()}
        except (OSError, ValueError):
            _DS2_AREA_CACHE[base_dir] = {}
    return _DS2_AREA_CACHE[base_dir]


## @brief Load the DS2 boss-defeat flag table (db_ds2/boss_flags.json, world-block
#  byte offset as hex → boss name). Cached. Returns {} if the file is absent.
_DS2_BOSS_CACHE = {}


def load_ds2_bosses(base_dir):
    if base_dir not in _DS2_BOSS_CACHE:
        path = os.path.join(base_dir, "db_ds2", "boss_flags.json")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            _DS2_BOSS_CACHE[base_dir] = {int(k, 16): v for k, v in raw.items()}
        except (OSError, ValueError):
            _DS2_BOSS_CACHE[base_dir] = {}
    return _DS2_BOSS_CACHE[base_dir]


## @brief Load the DS2 boss-soul → boss-name table (db_ds2/boss_souls.json). Cached.
_DS2_BOSS_SOUL_CACHE = {}


def load_ds2_boss_souls(base_dir):
    if base_dir not in _DS2_BOSS_SOUL_CACHE:
        path = os.path.join(base_dir, "db_ds2", "boss_souls.json")
        try:
            with open(path, encoding="utf-8") as f:
                _DS2_BOSS_SOUL_CACHE[base_dir] = json.load(f)
        except (OSError, ValueError):
            _DS2_BOSS_SOUL_CACHE[base_dir] = {}
    return _DS2_BOSS_SOUL_CACHE[base_dir]


## @brief Progression gates: a boss proven dead by something the character has. Only
#  DS2's STRICTLY-LINEAR endgame qualifies — the mid-game is four parallel, largely
#  skippable paths, so a mid-game gate would risk a false kill (the core rule). The
#  endgame is unskippable: Drangleic Castle → Looking Glass Knight → Shrine of Amana →
#  Demon of Song → Undead Crypt → Velstadt → (King's Ring, behind him) → King's Gate →
#  Throne → Throne Watcher & Defender → Nashandra. Sources: fextralife Game Progress
#  Route + King's Ring page.
## @brief Bonfire present ⇒ these bosses dead (the bonfire is only reachable past them).
DS2_BOSS_GATE = {
    "Undead Crypt Entrance": ("Looking Glass Knight", "Demon of Song"),
    "Throne Floor": ("Looking Glass Knight", "Demon of Song", "Velstadt, the Royal Aegis"),
}


## @brief Inventory item held ⇒ boss dead (item only obtainable past it). The King's
#  Ring sits in the room behind Velstadt and cannot be had otherwise.
## @brief Item ⇒ boss it sits behind. Each item has exactly one documented source, and
#  that source is past the boss's fog gate, so holding it is a certain kill. The two DLC
#  gank bosses drop no soul at all, which is why they need this route:
#  Pharros Mask lies on a corpse past the (Blue) Smelter Demon's arena in Iron Passage,
#  and the Flower Skirt is in the chest between Cave of the Dead's trio and the exit.
DS2_ITEM_GATE = {
    "King's Ring": ("Velstadt, the Royal Aegis",),
    "Pharros Mask": ("Blue Smelter Demon",),
    "Flower Skirt": ("Graverobber, Varg, and Cerah",),
}


## @brief Boss defeated ⇒ its mandatory predecessors also defeated (each list is the
#  full transitive set, so a single pass closes it). Endgame only, where the order is
#  forced.
DS2_BOSS_PREREQ = {
    "Nashandra": ("Throne Watcher", "Throne Defender", "Velstadt, the Royal Aegis",
                  "Demon of Song", "Looking Glass Knight"),
    "Throne Watcher": ("Velstadt, the Royal Aegis", "Demon of Song", "Looking Glass Knight"),
    "Throne Defender": ("Velstadt, the Royal Aegis", "Demon of Song", "Looking Glass Knight"),
    "Velstadt, the Royal Aegis": ("Demon of Song", "Looking Glass Knight"),
    "Demon of Song": ("Looking Glass Knight",),
}


##
# @brief An inventory name with its " +N" reinforcement suffix removed.
# @details Gate matching compares against the plain db name, and armour/weapons render
# upgraded. Only strips a trailing " +digits", so a name that genuinely ends that way is
# untouched (none does).
def ds2_base_name(name):
    head, sep, tail = name.rpartition(" +")
    return head if sep and tail.isdigit() else name


##
# @brief Bosses this character has defeated, as @c {boss: [evidence]}, or None.
# @details A FLOOR from three independent, positive-only signals — each is certain
# when it fires, none is exhaustive:
#   - @b flag: a mapped defeat event flag is set (world block; see boss_flags.json).
#     Verified by the 41-boss differential matrix. Only a handful are mapped.
#   - @b soul: the boss's soul is still in inventory. Cannot be obtained without the
#     kill, but a consumed/traded soul goes invisible.
#   - @b progression: a bonfire the character has can only be reached past this boss
#     (@ref DS2_BOSS_GATE).
# A boss absent here may still be defeated (its soul consumed and not gated). Sources
# are merged per boss so overlap reads as corroboration.
def ds2_infer_bosses(world, ch, base_dir):
    out = defaultdict(set)
    for off, name in load_ds2_bosses(base_dir).items():
        if world and u8(world, off):
            out[name].add("flag")
    soul_db = load_ds2_boss_souls(base_dir)
    for name, _qty in ch["inv"].get("bosssouls", []):
        boss = soul_db.get(name)
        if boss:
            out[boss].add("soul")
    for bonfire in (ch.get("bonfires") or []):
        for boss in DS2_BOSS_GATE.get(bonfire, ()):
            out[boss].add("gate")
    # Armour and weapons render with a " +N" reinforcement suffix, so strip it before
    # matching — an upgraded Pharros Mask is still the same gate item.
    held = {ds2_base_name(n) for items in ch["inv"].values() for n, _ in items}
    held.update(n for n, _ in ch.get("key_items", []))
    for item, bosses in DS2_ITEM_GATE.items():
        if item in held:
            for boss in bosses:
                out[boss].add("gate")
    # NG+ proves the game was finished, so its final boss (and, via the closure below,
    # the whole forced endgame chain) is dead — even if the soul was long since spent.
    if (ch.get("ng_plus") or 0) > 0:
        out["Nashandra"].add("clear")
    # Close over mandatory predecessors: any boss reached above implies the bosses
    # the game forces you through before it. One pass suffices (lists are transitive).
    for boss in list(out):
        for pre in DS2_BOSS_PREREQ.get(boss, ()):
            out[pre].add("gate")
    if not out:
        return None
    return {b: sorted(out[b]) for b in sorted(out)}


##
# @brief Names of the bonfires this character has discovered, or None.
# @details The world block holds a contiguous u16 array of bonfire ids and, exactly
# DS2_BONFIRE_FLAG_DELTA bytes later, one unlock byte per id (non-zero = discovered).
# The array's offset shifts between saves, so it is located by content: the start of
# the longest run of known bonfire ids (a false run is astronomically unlikely given
# the ~78-id vocabulary in the u16 space). Returns the discovered names in world
# order, or None when the array can't be found (no world block / unknown layout).
def ds2_visited_bonfires(world, bf_db):
    if not world or not bf_db:
        return None
    best_start, best_run, run, run_start, o = -1, 0, 0, 0, 0
    while o + 2 <= len(world):
        if u16(world, o) in bf_db:
            run_start = o if run == 0 else run_start
            run += 1
            if run > best_run:
                best_run, best_start = run, run_start
        else:
            run = 0
        o += 2
    if best_run < DS2_BONFIRE_MIN_RUN:
        return None
    ids = []
    o = best_start
    while o + 2 <= len(world) and len(ids) < DS2_BONFIRE_FLAG_DELTA // 2:
        v = u16(world, o)
        if v == 0:
            break
        ids.append(v)
        o += 2
    flag_base = best_start + DS2_BONFIRE_FLAG_DELTA
    visited = []
    for idx, bid in enumerate(ids):
        if u8(world, flag_base + idx):
            visited.append((bid, bf_db.get(bid, f"(bonfire {bid:#06x})")))
    return visited


##
# @brief Group discovered bonfires by area, in the (area, count, names) shape DS1
#        and DS3 already emit, so all three render through the same section.
# @param visited The (id, name) pairs from ds2_visited_bonfires.
# @param area_db Bonfire id → area, from load_ds2_bonfire_areas.
# @return The grouped list, or None when no id has a known area (the caller then
#         keeps the flat list rather than inventing an "Unknown" bucket).
def ds2_bonfire_areas(visited, area_db, bf_db):
    if not visited or not area_db:
        return None
    seen = {bid for bid, _n in visited}
    order = [area_db[bid] for bid, _n in visited if bid in area_db]
    areas = OrderedDict((a, ([], [])) for a in order)
    # Walk the whole area table, not just what was visited, so an area the character
    # has not reached still prints as 0/N rather than vanishing.
    for bid, area in area_db.items():
        got, miss = areas.setdefault(area, ([], []))
        name = bf_db.get(bid)
        if name is None:
            continue
        (got if bid in seen else miss).append(name)
    out = [(a, len(got), got, len(got) + len(miss), miss)
           for a, (got, miss) in areas.items()]
    return out if any(c for _a, c, _n, _t, _m in out) else None


## @brief DS2-only augment: attach world-block progression (bonfires, bosses) to a
#  parsed character. The world block for status entry @c i is entry
#  @c i+DS2_WORLD_ENTRY_DELTA; a missing/undecryptable block leaves both fields None
#  (sections omitted). Decrypts the world block once for both reads.
def ds2_augment(ch, data, entries, i, base_dir, dec=decrypt_ds2):
    # Play time lives in the header title record (one per slot), not the character
    # block. Title index for block entry i is i - slots.start, and DS2 starts at 1.
    if entries:
        hdr = dec(data[entries[0].offset:entries[0].offset + entries[0].size])
        if hdr is not None:
            base = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - 1)
            ch["play_time"] = u32(hdr, base + DS2_TITLE_PLAYTIME_OFF)
    w = i + DS2_WORLD_ENTRY_DELTA
    if w >= len(entries):
        return
    world = dec(data[entries[w].offset:entries[w].offset + entries[w].size])
    visited = ds2_visited_bonfires(world, load_ds2_bonfires(base_dir))
    # The flat name list stays: DS2_BOSS_GATE is keyed by bonfire name, so the boss
    # inference below reads it. The grouped view is what gets rendered.
    ch["bonfires"] = [name for _, name in visited] if visited else visited
    areas = ds2_bonfire_areas(visited, load_ds2_bonfire_areas(base_dir),
                              load_ds2_bonfires(base_dir))
    if areas:
        ch["bonfire_areas"] = areas
    ch["bosses"] = ds2_infer_bosses(world, ch, base_dir)


##
# @brief Which DS2 block entries hold a character still listed in the menu.
# @details Deleting a character in-game only clears its entry in the header title
# list (BND4 entry 0) — the encrypted slot block is left untouched, so a plain scan
# resurrects deleted "ghost" characters. The title list is the menu's source of
# truth: block entry @c i owns title index @c i-slots.start, occupied only when that
# title name field holds a valid name. Reads through the bounds-checked helpers, so
# a short/garbled header yields None and the caller then skips the filter (degrade
# to showing everything rather than wrongly hiding a real character). An empty
# result is treated the same way: more likely a shifted offset on a future patch
# than a save the user would bother converting with every character deleted.
# @return The set of active entry indices, or None if the header can't be read or
#         the list came back empty (caller then applies no filter).
def ds2_active_slots(data, entries, slots, dec=decrypt_ds2):
    if not entries:
        return None
    hdr = dec(data[entries[0].offset:entries[0].offset + entries[0].size])
    if hdr is None:
        return None
    active = set()
    for i in slots:
        off = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - slots.start)
        if is_valid_name(read_utf16(hdr, off, 16)):
            active.add(i)
    return active or None
