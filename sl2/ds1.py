"""Dark Souls 1 family: Remastered and Prepare to Die Edition.
"""
import json
import os
from collections import defaultdict, OrderedDict
from .reader import is_valid_name, read_utf16, u16, u32, u8
from .itemdb import merge_qty
from .progress import attach_defeated_bosses, find_boss_souls, find_key_goods


##
# @brief DS1 base derived stats that are closed-form functions of attributes only.
# @details Only the two the equipment screen shows that need no gear: base Equip Load
# (@c 40 + Endurance — fextralife's table is dead linear, END 10 -> 50.0, 99 -> 139.0)
# and attunement slots (@ref DS1_SLOT_BREAKS). Stamina and Max HP are read from the
# save, so they are not recomputed; poise comes from armour alone and item discovery
# needs covenant/gear, so neither is derived. @param stats The attribute dict.
def ds1_derived_stats(stats):
    end = stats.get("Endurance", 0) or 0
    atn = stats.get("Attunement", 0) or 0
    return {"slots": sum(1 for b in DS1_SLOT_BREAKS if atn >= b),
            "equip_load": float(DS1_EQUIP_BASE + end)}


## @brief Load the DS1 bonfire table (db_ds1/bonfires.json, NetBonfireDb id → [name,
#  area]). Cached. Returns {} if absent.
_DS1_BONFIRE_CACHE = {}


def load_ds1_bonfires(base_dir):
    if base_dir not in _DS1_BONFIRE_CACHE:
        path = os.path.join(base_dir, "db_ds1", "bonfires.json")
        try:
            with open(path, encoding="utf-8") as f:
                _DS1_BONFIRE_CACHE[base_dir] = {int(k): tuple(v)
                                                for k, v in json.load(f).items()}
        except (OSError, ValueError):
            _DS1_BONFIRE_CACHE[base_dir] = {}
    return _DS1_BONFIRE_CACHE[base_dir]


## @brief Load the DS1 boss-defeat flag table (db_ds1/boss_flags.json, canonical boss
#  name → [region byte offset, uint32 mask]). Cached. Returns {} if absent.
_DS1_BOSSFLAG_CACHE = {}


def load_ds1_boss_flags(base_dir):
    if base_dir not in _DS1_BOSSFLAG_CACHE:
        path = os.path.join(base_dir, "db_ds1", "boss_flags.json")
        try:
            with open(path, encoding="utf-8") as f:
                _DS1_BOSSFLAG_CACHE[base_dir] = json.load(f)
        except (OSError, ValueError):
            _DS1_BOSSFLAG_CACHE[base_dir] = {}
    return _DS1_BOSSFLAG_CACHE[base_dir]


## @brief Where the event-flag region starts in a decrypted DS1 slot, per game. The
#  published DS1 flag addressing (group base + area*0x500 + section*128 + number/8,
#  MSB-first mask) gives offsets INSIDE the region; the region's own position is not
#  published, so it was searched for. In the DSR mule — an NG+2 character with all 43
#  bonfires — exactly ONE offset in the whole 393216-byte slot has all twelve boss
#  flags and both Bells of Awakening set, and both PtDE saves independently agree on
#  their own single value, so the base is a per-game constant rather than a per-save
#  search.
DS1_FLAG_BASE = {"dsr": 127721, "ptde": 127273}


## @brief Sanity gate on that base. A real flag region is overwhelmingly zero — it
#  measures ~0.006 set bits at the true base against ~0.32 for ordinary save data — so
#  anything denser than this means the region moved and the feature turns itself off
#  rather than reporting bosses off the wrong bytes.
DS1_FLAG_MAX_DENSITY, DS1_FLAG_SPAN = 0.05, 23156


##
# @brief Merge DS1 boss-defeat FLAGS into @c ch["bosses"] as @c flag evidence.
# @details Unlike the held-soul floor this sees a boss whose soul was long since
# consumed. Guarded twice: the region base must be known for the game, and the region
# must actually read sparse (@ref DS1_FLAG_MAX_DENSITY) — a moved region fails that
# and nothing is reported. Boss names are canonicalised to the boss_souls.json
# spelling in the db, so a flag kill and a soul kill dedup onto one boss.
def ds1_attach_flags(ch, buf, base_dir, game):
    base = DS1_FLAG_BASE.get(game)
    table = load_ds1_boss_flags(base_dir)
    if base is None or not table or base + DS1_FLAG_SPAN > len(buf):
        return
    region = buf[base:base + DS1_FLAG_SPAN]
    if sum(bin(b).count("1") for b in region) > len(region) * 8 * DS1_FLAG_MAX_DENSITY:
        return
    bosses = {b: set(s) for b, s in (ch.get("bosses") or {}).items()}
    for name, (off, mask) in table.items():
        v = u32(buf, base + off)
        if v is not None and v & mask:
            bosses.setdefault(name, set()).add("flag")
    if bosses:
        ch["bosses"] = {b: sorted(bosses[b]) for b in bosses}


## @brief DS1 bonfire record: 20 bytes, id then state (the rest is unread flags).
#  Unlike DS2 and DS3, DS1 does NOT keep bonfires as event flags — they are a
#  NetBonfireDb list of {id, state} records, so this walks records rather than bits.
DS1_BONFIRE_REC, DS1_BONFIRE_STATE_D = 20, 4


## @brief The state values a real record can hold, and what each means. Anything else
#  ends the walk, which is what keeps a misaligned start from inventing bonfires.
DS1_BONFIRE_STATE = {0: "discovered", 10: "lit", 20: "kindled +1",
                     30: "kindled +2", 40: "kindled +3"}


## @brief Shortest believable run, so a stray id in unrelated data cannot pass.
DS1_BONFIRE_MIN_RUN = 5


##
# @brief DS1 bonfires the character has found, grouped by area.
# @details The list's offset moves between saves, so it is located BY CONTENT: the
# longest run of consecutive 20-byte records whose id is a real bonfire and whose
# state is one of @ref DS1_BONFIRE_STATE, with no id repeating. Shared by DSR and
# PtDE — the layout is identical, only the decryption differs.
# @return @c [(area, count, [names])] in the DS3 shape so it renders the same way,
#         or None when no believable run exists.
def ds1_bonfires(buf, db):
    if not db:
        return None
    best, o = [], 0
    while o + DS1_BONFIRE_REC <= len(buf):
        if u32(buf, o) in db:
            run, p, seen = [], o, set()
            while p + DS1_BONFIRE_REC <= len(buf):
                bid = u32(buf, p)
                state = u32(buf, p + DS1_BONFIRE_STATE_D)
                if bid not in db or state not in DS1_BONFIRE_STATE or bid in seen:
                    break
                seen.add(bid)
                run.append((bid, state))
                p += DS1_BONFIRE_REC
            if len(run) > len(best):
                best = run
            o = max(p, o + 1)
        else:
            o += 1
    if len(best) < DS1_BONFIRE_MIN_RUN:
        return None
    found = {bid: state for bid, state in best}
    areas = OrderedDict()
    for bid, (name, area) in db.items():
        got, miss = areas.setdefault(area, ([], []))
        if bid in found:
            got.append(f"{name} ({DS1_BONFIRE_STATE[found[bid]]})")
        else:
            miss.append(name)
    return [(a, len(got), got, len(got) + len(miss), miss)
            for a, (got, miss) in areas.items()]


## @brief DS1-only augment: attach the bonfire list, which needs the db folder the
#  parse function never sees. Re-decrypts the slot rather than threading the buffer
#  through, so the generic loop keeps its (ch, data, entries, i, base_dir) shape.
#  @param dec The game's decrypt callable (DSR is encrypted, PtDE is not).
def ds1_augment(ch, data, entries, i, base_dir, dec):
    if i >= len(entries):
        return
    buf = dec(data[entries[i].offset:entries[i].offset + entries[i].size])
    if buf is None:
        return
    if DS1_MENU_ENTRY < len(entries):
        e = entries[DS1_MENU_ENTRY]
        ds1_attach_playtime(ch, dec(data[e.offset:e.offset + e.size]))
    areas = ds1_bonfires(buf, load_ds1_bonfires(base_dir))
    if areas:
        ch["bonfire_areas"] = areas
    # Order matters: attach_defeated_bosses refuses to run once `bosses` exists (that
    # guard is what stops it trampling DS2's richer inference), so the soul/NG+ floor
    # has to be built BEFORE the flags are merged on top. The caller's own call then
    # no-ops on the same guard.
    attach_defeated_bosses(ch, base_dir)
    ds1_attach_flags(ch, buf, base_dir, ch.get("game"))


## @brief Anchor pattern that sits next to the DSR character block. Stats are read
#         at signed distances from wherever this is found.
DSR_MAGIC = bytes.fromhex("00FFFFFFFF000000000000000000000000FFFFFFFF")


## @brief DSR field distances from the anchor.
DSR_SOULS_D, DSR_HP_D, DSR_STAM_D, DSR_LEVEL_D, DSR_CLASS_D, DSR_HUM_D = -291, -419, -391, -295, -233, -307


DSR_NG_D, DSR_NAME_D = 0x1E3A7, -271


## @brief Gender (u8) distance from the anchor. Two independent sources agree, which
#  is what makes this shippable without a differential save: alfizari's DSR editor puts
#  Gender at magic-237, and tarvitz/dsfp (a PtDE parser) has a boolean `male` field 34
#  bytes past the name — the same byte, since the name sits at magic-271. Both call 1
#  Male, so DS1's polarity is the OPPOSITE of DS2's (where 1 is Female). Cross-read on
#  a real save: dsfp's frame and ours both report male=1 for the same character.
DSR_GENDER_D = -237


## @brief DS1 gender enum. Note the inverted polarity against DS2_GENDER.
DS1_GENDER = {0: "Female", 1: "Male"}


## @brief Total deaths (u32), at a slot-absolute offset per release rather than a
#  distance from the moving anchor — the counter lives in a fixed struct near the
#  event-flag region, not in the character block. PtDE's offset is dsfp's (0x1F128 in
#  its frame, which is 16 bytes ahead of ours), verified on two real saves: an
#  all-items mule reads 459 and a real playthrough reads 39. DSR shifts this struct by
#  the same 448 bytes its event-flag region moves (see DS1_FLAG_BASE), and the
#  neighbouring fields confirm it: both releases read [deaths][0xFFFFFFFF][~1.5M][2048]
#  in that order. DS1_DEATHS_SENTINEL is checked before the value is used, so a moved
#  struct omits the field instead of printing whatever is there.
DS1_DEATHS_OFF = {"ptde": 0x1F118, "dsr": 0x1F2D8}


DS1_DEATHS_SENTINEL, DS1_DEATHS_SENTINEL_D = 0xFFFFFFFF, 4


## @brief DS1's load-screen roster lives in BND4 entry 10, one fixed record per slot:
#  name at +0 (UTF-16), soul level at +36, play time at +40 as a uint32 of SECONDS.
#  dsfp documents the 0x170 record stride, which its own play-time constant confirms
#  (its file-absolute index minus the record base is exactly this +40). The block's
#  start differs between the releases, so the record is located by the character's own
#  name and only accepted when the level at +36 matches the level parsed from the
#  slot — a self-consistency gate, the same trick DS3's equip slots use. Verified on
#  three saves: 25:16:39 at level 95 (DSR), 19:25:30 at 81 (PtDE), 151h on a mule.
DS1_MENU_ENTRY = 10


DS1_MENU_LEVEL_D, DS1_MENU_PLAYTIME_D = 36, 40


## @brief DS1 derived values that are pure functions of one attribute, so they can be
#  computed exactly rather than guessed. Equip Load is 40 + Endurance (fextralife's
#  table: END 10 -> 50.0, 40 -> 80.0, 99 -> 139.0, dead linear with base 40).
#  Attunement slots are the documented breakpoints, 10 slots max at 50. Stamina and HP
#  are NOT computed — DS1 stores both in the save, so they are read. Poise is armour-
#  only and everything else is gear-scaled, so nothing else is derived.
DS1_EQUIP_BASE = 40


DS1_SLOT_BREAKS = (10, 12, 14, 16, 19, 23, 28, 34, 41, 50)


## @brief DSR attribute distances from the anchor (uint8 each), in display order.
DSR_STAT_D = OrderedDict([
    ("Vitality", -375), ("Attunement", -367), ("Endurance", -359),
    ("Strength", -351), ("Dexterity", -343), ("Resistance", -303),
    ("Intelligence", -335), ("Faith", -327)])


## @brief DS1 class ids to names.
DS1_CLASS = {0: "Warrior", 1: "Knight", 2: "Wanderer", 3: "Thief", 4: "Bandit",
             5: "Hunter", 6: "Sorcerer", 7: "Pyromancer", 8: "Cleric", 9: "Deprived"}


## @brief DS1 inventory slot type (top nibble) to category.
DS1_CAT = {0x00000000: "weapons", 0x10000000: "armors",
           0x20000000: "rings", 0x40000000: "goods"}


## @brief Where the DS1 inventory scan begins, and the anchor that marks the first
#         real slot.
DS1_INV_START, DS1_INV_ANCHOR = 0x988, bytes.fromhex("0000000000000000A0BB0D00")


## @brief End-of-inventory marker.
DS1_INV_END = bytes.fromhex("00000000FFFFFFFFFFFFFFFF")


## @brief DS1 weapon infusion paths, keyed by the hundreds digit of the id's
#  upgrade suffix (id = base + path*100 + level). Path 0 is plain reinforcement.
DS1_INFUSION = {1: "Crystal", 2: "Lightning", 3: "Raw", 4: "Magic", 5: "Enchanted",
                6: "Divine", 7: "Occult", 8: "Fire", 9: "Chaos"}


##
# @brief Resolve a DS1 item id to a display name, unwrapping any upgrade baked in.
# @details Weapons and armour store their reinforcement — and, for weapons, their
# infusion — inside the id as @c base+path*100+level, where @c base ends in 000. A
# direct hit is tried first; failing that, the base is looked up and a "+N" (with
# the infusion name for weapons) suffix is appended. Rings and goods do not upgrade,
# so they only ever match directly.
# @return The display name, or None if even the base is unknown.
def ds1_resolve(item_db, cat, iid):
    table = item_db.get(cat, {})
    if iid in table:
        return table[iid]
    # Rings carry no upgrade, and the table keeps them at 1/1000 of the stored id.
    if cat == "rings":
        return table.get(iid // 1000)
    if cat not in ("weapons", "armors"):
        return None
    base, path, level = iid - iid % 1000, (iid % 1000) // 100, iid % 100
    name = table.get(base)
    if name is None:
        return None
    infusion = DS1_INFUSION.get(path) if cat == "weapons" else None
    suffix = f" +{level}" if level else ""
    return f"{name}{suffix} ({infusion})" if infusion else f"{name}{suffix}"


##
# @brief Find the true DSR stat anchor.
# @details The magic pattern recurs inside runs of empty inventory slots, so a
# match is not enough — the right one is where the whole stat block also reads as
# plausible (level in range, every attribute 0..99). This is why a wrong anchor
# never slips through on an all-items save.
# @param buf The decrypted slot data.
# @return The anchor offset, or None if no sane one exists.
def dsr_find_anchor(buf):
    o = 0
    while True:
        m = buf.find(DSR_MAGIC, o)
        if m == -1:
            return None
        lvl = u16(buf, m + DSR_LEVEL_D)
        stats = [u8(buf, m + d) for d in DSR_STAT_D.values()]
        if (lvl is not None and 1 <= lvl <= 838
                and all(v is not None and 0 <= v <= 99 for v in stats)):
            return m
        o = m + 1


##
# @brief Sort the DS1 inventory into categories. Shared by DSR and PtDE.
# @return @c (buckets, unknown_count).
def ds1_inventory(buf, item_db):
    buckets, unknown = defaultdict(list), 0
    start = buf.find(DS1_INV_ANCHOR, DS1_INV_START)
    if start == -1:
        return buckets, unknown
    end = buf.find(DS1_INV_END, start)
    if end == -1:
        end = len(buf)
    o = start
    while o + 28 <= end:
        stype, iid, qty = u32(buf, o + 4), u32(buf, o + 8), u32(buf, o + 12)
        o += 28
        if not iid:
            continue
        cat = DS1_CAT.get(stype & 0xF0000000) if stype is not None else None
        # A spell IS a good as far as the slot type is concerned — only the id says
        # otherwise, which is why the spell table is separate and consulted here.
        if cat == "goods" and iid in item_db.get("spells", {}):
            cat = "spells"
        name = ds1_resolve(item_db, cat, iid) if cat else None
        if name is None:
            unknown += 1
            continue
        buckets[cat].append((name, qty))
    return buckets, unknown


##
# @brief Build the unified full-tier dict from a located DS1 stat anchor.
# @details Shared by DSR and PtDE: the two games carry the *same* stat block —
# same fields at the same signed distances from the same anchor point (proven by
# reading a real PtDE save byte-for-byte against the DSR distances). Only the way
# the anchor is *found* differs, and NG+ is DSR-file-specific, so the caller
# passes it (PtDE has no calibrated NG+ field and passes None).
# @param m  The stat anchor (a DSR-equivalent anchor position).
# @param ng New Game+ count, or None to omit the field.
##
# @brief Total deaths for a DS1 slot, or None when the struct isn't where expected.
# @details Guarded by the sentinel that follows the counter in both releases: if the
# uint32 at +4 isn't 0xFFFFFFFF the struct has moved and the field is dropped rather
# than read from the wrong place.
# @param buf  The decrypted slot.
# @param game "dsr" or "ptde".
# @return The death count, or None.
def ds1_deaths(buf, game):
    off = DS1_DEATHS_OFF.get(game)
    if off is None:
        return None
    if u32(buf, off + DS1_DEATHS_SENTINEL_D) != DS1_DEATHS_SENTINEL:
        return None
    return u32(buf, off)


##
# @brief Attach play time from DS1's load-screen roster block.
# @details The roster record is found by the character's own name and accepted only
# when the level stored beside it matches the level already parsed from the slot, so a
# renamed/duplicate name or a shifted block turns the field off instead of attaching
# another character's clock.
# @param ch    The parsed character (read for name/level, written for play_time).
# @param menu  The decrypted menu block, or None.
def ds1_attach_playtime(ch, menu):
    if not menu or not ch.get("name") or ch.get("level") is None:
        return
    want = ch["name"].encode("utf-16-le")
    pos = menu.find(want)
    while pos >= 0:
        if u32(menu, pos + DS1_MENU_LEVEL_D) == ch["level"]:
            ch["play_time"] = u32(menu, pos + DS1_MENU_PLAYTIME_D)
            return
        pos = menu.find(want, pos + 2)


def ds1_character(buf, item_db, m, game, ng):
    stats = OrderedDict((k, u8(buf, m + d)) for k, d in DSR_STAT_D.items())
    buckets, unknown = ds1_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    name = read_utf16(buf, m + DSR_NAME_D, 13)
    return {
        "tier": "full", "game": game,
        "name": name if is_valid_name(name) else "(unnamed slot)",
        "klass": DS1_CLASS.get(u8(buf, m + DSR_CLASS_D)),
        "gender": DS1_GENDER.get(u8(buf, m + DSR_GENDER_D)),
        "deaths": ds1_deaths(buf, game),
        "level": u16(buf, m + DSR_LEVEL_D), "stats": stats,
        "souls": u32(buf, m + DSR_SOULS_D), "soul_memory": None,
        "humanity": u8(buf, m + DSR_HUM_D), "stamina": u32(buf, m + DSR_STAM_D),
        "hp": u32(buf, m + DSR_HP_D), "ng_plus": ng,
        "boss_souls": find_boss_souls(inv.get("goods", [])),
        "key_items": find_key_goods(inv.get("goods", [])),
        "inv": inv, "unknown_count": unknown,
    }


## @brief Parse one DSR slot into the unified dict (full tier), or None if empty.
def dsr_parse(buf, item_db):
    m = dsr_find_anchor(buf)
    if m is None:
        return None
    return ds1_character(buf, item_db, m, "dsr", u8(buf, m + DSR_NG_D) or 0)


##
# @brief Find the PtDE stat anchor (full tier).
# @details PtDE has no DSR_MAGIC to key on, but its stat block is laid out
# exactly like DSR's around the character name. So the name *is* the anchor: for
# each position that decodes as a valid name, treat it as DSR's name field, back
# out the equivalent anchor, and accept it only if the whole stat block there
# also reads sane (level in range, every attribute 0..99). Requiring a valid name
# *and* a valid stat block is what stops a false match inside the repeating
# inventory runs of an all-items save — the real block sits before the inventory,
# so the first such match from the top is the character.
# @return The anchor offset, or None if no sane one exists.
def ptde_find_anchor(buf):
    o, n = 0, len(buf) - 1
    while o < n:
        name = read_utf16(buf, o, 13)
        if len(name) >= 2 and is_valid_name(name):
            m = o - DSR_NAME_D
            lvl = u16(buf, m + DSR_LEVEL_D)
            stats = [u8(buf, m + d) for d in DSR_STAT_D.values()]
            if (lvl is not None and 1 <= lvl <= 838
                    and all(v is not None and 0 <= v <= 99 for v in stats)):
                return m
        o += 1
    return None


##
# @brief Parse one PtDE slot (full tier).
# @details Unencrypted DS1. Same stat layout as DSR (see @ref ds1_character),
# found via the name anchor. NG+ is not calibrated for PtDE, so it is omitted.
def ptde_parse(buf, item_db):
    m = ptde_find_anchor(buf)
    if m is None:
        return None
    return ds1_character(buf, item_db, m, "ptde", None)
