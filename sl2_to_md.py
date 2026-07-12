#!/usr/bin/env python3
##
# @file sl2_to_md.py
# @brief FromSoftware `.sl2` save to Markdown converter for the whole Souls line:
#        Dark Souls (PtDE and Remastered), Dark Souls II (vanilla and SOTFS),
#        Dark Souls III, and Elden Ring.
#
# @details
# A Souls save is a locked box. This script reads it and hands you back one plain
# Markdown file describing the playthrough, so you can paste it into an LLM that
# cannot read a `.sl2` but reads Markdown fine. Per character it pulls whatever
# the game reliably exposes: name, class, level, attributes, souls, and the full
# inventory with real item names, plus a progress section built from boss souls
# and key items.
#
# It reads the save. It never writes to it. Point it at your live save if you
# want; the worst case is a bad Markdown file, not a bricked character.
#
# ### Not every game is equal, and this file says so instead of guessing
# Six save variants share one archive format but diverge in the details, and
# not all of them are fully mapped in public tooling. Each game is handled at the
# highest tier it can be trusted at, and the output states the tier plainly:
#
# | Game            | Tier   | What comes out                                     |
# |-----------------|--------|----------------------------------------------------|
# | DS2: SOTFS      | full   | identity, stats, souls, inventory, progress        |
# | Dark Souls R.   | full   | identity, stats, souls, inventory, progress        |
# | Dark Souls PtDE | full   | identity, stats, souls, inventory, progress        |
# | Dark Souls III  | full   | identity, stats, souls, inventory, progress        |
# | Elden Ring      | full*  | identity, stats, runes, owned items, remembrances  |
#
# A tier is a promise: everything printed at any tier is read from the save, not
# inferred and not guessed. Stat offsets are calibrated for every supported game;
# DS3 and ER locate their stat block by content (the level == sum-of-attributes
# identity) and drop stats for a slot rather than print a wrong one if it fails to
# validate. Elden Ring's `full*` is full identity/stats but a partial item list:
# owned items are read, quantities and reinforced-weapon variants are not. Vanilla
# DS2 is detected but unsupported: its AES key is not public.
#
# ### Reading defensively
# Every integer read goes through a bounds-checked helper that returns @c None
# rather than raising or reading past the end of a buffer, and the archive
# structure is validated before any offset is trusted. A malformed or truncated
# save degrades to "unknown" fields; it does not crash and it does not print
# garbage. Constants are named, functions stay single-purpose, and the tool fails
# loudly on anything it cannot read rather than limping on.
#
# @note Encryption keys and offsets come from the community: DS2 tables from
#       alfizari/Dark-Souls-2-Save-Editor-PS4-PC; DSR decryption from
#       jtesta/souls_givifier; DSR/DS1 tables and anchor offsets from
#       alfizari/Dark-Souls-Remastered-Save-Editor; DS3/ER keys and header layout
#       from jtesta/souls_givifier; DS2 key from mi5hmash/SL2Bonfire.
#
# @author Jubair Hasan (Joy) / DarthDemono
# @see https://github.com/darthdemono/SL2-TO-MD
#
import argparse
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict, OrderedDict
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.exit("Missing dependency: pip install cryptography")


# ═════════════════════════════════════════════════════════════════════════════
#  Safe, bounds-checked readers
#
#  Nothing below indexes a buffer without going through these. A read that would
#  fall off the end returns None, and callers treat None as "unknown" — the one
#  place a missing field is allowed to travel, rather than a wrong one.
# ═════════════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════════════
#  Encryption keys (all shipped inside the games — none of these is a secret)
# ═════════════════════════════════════════════════════════════════════════════

## @brief AES-128 key for Dark Souls II: Scholar of the First Sin.
DS2_KEY = bytes.fromhex("599F9B699640A55236EE2D70835EC744")
## @brief AES-128 key for Dark Souls Remastered.
DSR_KEY = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")
## @brief AES-128 key for Dark Souls III.
DS3_KEY = bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")


# ═════════════════════════════════════════════════════════════════════════════
#  BND4 archive
# ═════════════════════════════════════════════════════════════════════════════

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
            sys.exit(f"Entry #{i} points outside the file (offset={offset}, size={size}).")
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
    blob = data[entry.offset:entry.offset + entry.size]
    return len(blob) >= 16 and hashlib.md5(blob[16:]).digest() == blob[:16]


# ═════════════════════════════════════════════════════════════════════════════
#  Game detection
# ═════════════════════════════════════════════════════════════════════════════

## @brief The BND4 signature DS2 stamps into its header.
DS2_SIGNATURE = b"14e503cb"


##
# @brief Identify which game wrote this save, from the bytes alone.
# @details The header signature and entry count narrow it down; the last
# ambiguity — vanilla DS2 versus SOTFS (same signature) and DS3 versus ER (same
# count) — is settled by content: SOTFS is the DS2 variant whose key produces a
# sane length prefix, and ER's entries are far larger than DS3's.
# @param data    The full file bytes.
# @param entries The parsed entry table.
# @return One of @c "ds2vanilla", @c "ds2sotfs", @c "dsr", @c "ptde",
#         @c "ds3", @c "er".
def detect_game(data, entries):
    sig = data[24:32]
    n = len(entries)
    if sig == DS2_SIGNATURE:
        # Both DS2 variants share the signature. SOTFS is the one whose key works;
        # vanilla DS2 uses a key that is not public, so it is not supported.
        blob = data[entries[1].offset:entries[1].offset + entries[1].size]
        pt = _aes_cbc(DS2_KEY, blob[16:32], blob[32:])
        dlen = u32(pt, 0)
        if dlen is not None and 0 < dlen <= len(pt) - 4:
            return "ds2sotfs"
        sys.exit("Vanilla Dark Souls II (DARKSII0000.sl2) is not supported — its "
                 "AES key is not public. Re-save in Scholar of the First Sin.")
    if n == 11:
        return "dsr" if sig == b"\x00" * 8 else "ptde"
    if n == 12:
        return "er" if entries[0].size > 2_000_000 else "ds3"
    sys.exit("Unrecognised .sl2 — not a supported Souls save.")


##
# @brief AES-128-CBC decrypt, truncated to a whole number of blocks.
# @param key The 16-byte key.
# @param iv  The 16-byte initialisation vector.
# @param ct  The ciphertext.
# @return The decrypted bytes.
def _aes_cbc(key, iv, ct):
    ct = ct[:len(ct) // 16 * 16]
    return Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor().update(ct)


# ═════════════════════════════════════════════════════════════════════════════
#  Per-game entry decryption
#
#  Each returns the plaintext game data for one entry, or None on a bad read.
# ═════════════════════════════════════════════════════════════════════════════

##
# @brief Decrypt a DS2 entry: [16B MD5][16B IV][ciphertext], plaintext prefixed
#        by a uint32 length.
# @param blob The raw entry bytes.
# @return The game data, or None if the length prefix is unreadable.
def decrypt_ds2(blob):
    pt = _aes_cbc(DS2_KEY, blob[16:32], blob[32:])
    dlen = u32(pt, 0)
    return None if dlen is None else pt[4:4 + dlen]


##
# @brief Decrypt a DSR or DS3 entry. The IV doubles as the first ciphertext
#        block, so the first 16 decrypted bytes are discarded; the length sits at
#        offset 16 and the data starts at 20.
# @param blob The raw entry bytes.
# @param key  DSR or DS3 key.
# @return The game data, or None if the length is unreadable.
def decrypt_iv_prefixed(blob, key):
    dec = _aes_cbc(key, blob[16:32], blob[16:])
    dlen = u32(dec, 16)
    return None if dlen is None else dec[20:20 + dlen]


##
# @brief "Decrypt" an unencrypted entry (PtDE, Elden Ring). Only the MD5+IV
#        header is stripped; the rest is already plaintext.
# @param blob The raw entry bytes.
# @return The game data.
def decrypt_none(blob):
    return blob[16:]


# ═════════════════════════════════════════════════════════════════════════════
#  Item databases
# ═════════════════════════════════════════════════════════════════════════════

## @brief DS2 tables: filename stem to category. Ids are unique across categories.
#  Categories are finer than the game's raw tabs so the output can mirror the
#  in-game menu: consumables, trade goods, emotes and boss souls each stand alone.
DS2_DB_FILES = {"weapons": "weapons", "armors": "armors", "rings": "rings",
                "spells": "spells", "key": "keys", "bolts": "bolts",
                "upgrade": "upgrade", "consumables": "consumables",
                "online": "online", "emotes": "emotes", "bosssouls": "bosssouls"}
## @brief DS1 (DSR and PtDE) tables. Ids repeat across categories, so lookups stay
#         category-scoped and the slot type decides which table to use.
DS1_DB_FILES = {"MeleeWeapons": "weapons", "Armor": "armors",
                "Rings": "rings", "Consumables": "goods"}


##
# @brief Load item-name tables for a game family.
# @param db_dir Folder holding the JSON tables.
# @param flat   True for DS2 (one id-to-(name,category) dict); False for DS1
#               (a dict per category).
# @param files  The filename-stem to category mapping to load.
# @return The lookup structure, or an empty container if the folder is missing.
def load_item_db(db_dir, flat, files):
    if not os.path.isdir(db_dir):
        return {} if flat else {}
    if flat:
        # DS2 tables are id-keyed ({"<little-endian-hex>": name}), not name-keyed:
        # the game gives one item name several ids (base + reinforced/infused/variant
        # forms), which a name-keyed file cannot hold without dropping all but one.
        db = {}
        for stem, cat in files.items():
            path = os.path.join(db_dir, stem + ".json")
            if os.path.exists(path):
                for hx, name in json.load(open(path, encoding="utf-8")).items():
                    db.setdefault(int.from_bytes(bytes.fromhex(hx), "little"), (name, cat))
        return db
    db = {}
    for stem, cat in files.items():
        path = os.path.join(db_dir, stem + ".json")
        if os.path.exists(path):
            db[cat] = {int(v): k for k, v in json.load(open(path, encoding="utf-8")).items()}
    return db


##
# @brief Collapse duplicate stackable items into one line, summing counts, in
#        first-seen order.
# @param items A list of @c (name, qty) pairs.
# @return A list of @c (name, total_qty).
def merge_qty(items):
    order, agg = [], {}
    for name, q in items:
        if name not in agg:
            agg[name] = 0
            order.append(name)
        agg[name] += q
    return [(n, agg[n]) for n in order]


# ═════════════════════════════════════════════════════════════════════════════
#  Progress inference (shared)
# ═════════════════════════════════════════════════════════════════════════════

## @brief Ordinary soul consumables that are NOT boss souls. A boss soul in your
#         pack means the boss is dead; a "Soul of a Lost Undead" just means you
#         killed something ordinary.
GENERIC_SOULS = {
    "Fading Soul", "Soul of a Lost Undead", "Large Soul of a Lost Undead",
    "Soul of a Nameless Soldier", "Large Soul of a Nameless Soldier",
    "Soul of a Proud Knight", "Large Soul of a Proud Knight",
    "Soul of a Brave Warrior", "Large Soul of a Brave Warrior",
    "Soul of a Hero", "Soul of a Great Hero", "Soul of a Old Hero",
    "Wandering Soul", "Old Soul",
    # Dark Souls III generic farm souls — not bosses.
    "Soul of a Deserted Corpse", "Large Soul of a Deserted Corpse",
    "Soul of an Unknown Traveler", "Large Soul of an Unknown Traveler",
    "Soul of a Weary Warrior", "Large Soul of a Weary Warrior",
    "Soul of a Crestfallen Knight", "Large Soul of a Crestfallen Knight",
    "Soul of a Venerable Old Hand", "Soul of a Champion", "Soul of a Great Champion",
    "Soul of a Seasoned Warrior", "Large Soul of a Seasoned Warrior",
    "Soul of an Intrepid Hero", "Large Soul of an Intrepid Hero",
}
## @brief DS1 progression goods that gate the world but do not read as "keys".
DS1_PROGRESSION = {"Lordvessel", "Peculiar Doll", "Broken Pendant", "Rite of Kindling"}


## @brief Pull the likely boss / lord souls out of a goods list.
def find_boss_souls(goods):
    out = []
    for n, q in goods:
        if n in GENERIC_SOULS:
            continue
        if ("Soul of " in n or "Lord Soul" in n
                or n in ("Core of an Iron Golem", "Guardian Soul")):
            out.append((n, q))
    return out


## @brief Pull key / progression items out of a goods list (DS1 keeps keys here).
def find_key_goods(goods):
    return [(n, q) for n, q in goods if "Key" in n or n in DS1_PROGRESSION]


# ═════════════════════════════════════════════════════════════════════════════
#  Dark Souls II (SOTFS) — full tier
# ═════════════════════════════════════════════════════════════════════════════

## @brief DS2 character-slot offsets (absolute, into decrypted game data).
DS2_NAME_OFF, DS2_SOULS_OFF, DS2_SOULMEM_OFF, DS2_HP_OFF, DS2_NG_OFF = 960, 60, 64, 72, 1028
## @brief DS2 header (BND4 entry 0) title-list layout: each menu slot's name sits at
#  DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * title_index. Block entry i maps to title
#  index (i - slots.start). Used to tell active characters from deleted ghosts.
DS2_TITLE_NAME_OFF, DS2_TITLE_STRIDE = 1286, 496
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
## @brief Hollowing level (u8) offset in the slot block. From the Jappi88 DS2 save
#  editor: its player block reads Gender then HollowLv at block[0] 0x15A/0x15B, and
#  that block starts at slot flat +32 (Level/Souls/Soul-Memory/Health line up), so
#  HollowLv is at flat 0x15B+32 = 379. Verified: a 30h character read Hollow Lv 1.
DS2_HOLLOW_OFF = 379
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


## @brief Parse one DS2 slot into the unified character dict, or None if empty.
def ds2_parse(buf, item_db):
    if ds2_name(buf) is None:
        return None
    stats = OrderedDict((k, u16(buf, o) or 0) for k, o in DS2_STAT_OFF.items())
    buckets, unknown = ds2_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    return {
        "tier": "full", "game": "ds2sotfs", "name": ds2_name(buf),
        "klass": DS2_CLASS.get(u8(buf, DS2_CLASS_OFF)),
        "covenant": DS2_COVENANT.get(u8(buf, DS2_COVENANT_OFF)),
        "level": stats.pop("Level"), "stats": stats,
        "souls": u32(buf, DS2_SOULS_OFF), "soul_memory": u32(buf, DS2_SOULMEM_OFF),
        "humanity": None, "stamina": None, "hp": u32(buf, DS2_HP_OFF),
        "ng_plus": max(0, (u16(buf, DS2_NG_OFF) or 1) - 1),
        "hollow_lvl": u8(buf, DS2_HOLLOW_OFF),
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
DS2_ITEM_GATE = {"King's Ring": ("Velstadt, the Royal Aegis",)}
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
    held = {n for items in ch["inv"].values() for n, _ in items}
    held.update(n for n, _ in ch.get("key_items", []))
    for item, bosses in DS2_ITEM_GATE.items():
        if item in held:
            for boss in bosses:
                out[boss].add("gate")
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
            visited.append(bf_db.get(bid, f"(bonfire {bid:#06x})"))
    return visited


## @brief DS2-only augment: attach world-block progression (bonfires, bosses) to a
#  parsed character. The world block for status entry @c i is entry
#  @c i+DS2_WORLD_ENTRY_DELTA; a missing/undecryptable block leaves both fields None
#  (sections omitted). Decrypts the world block once for both reads.
def ds2_augment(ch, data, entries, i, base_dir):
    w = i + DS2_WORLD_ENTRY_DELTA
    if w >= len(entries):
        return
    world = decrypt_ds2(data[entries[w].offset:entries[w].offset + entries[w].size])
    ch["bonfires"] = ds2_visited_bonfires(world, load_ds2_bonfires(base_dir))
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
def ds2_active_slots(data, entries, slots):
    if not entries:
        return None
    hdr = decrypt_ds2(data[entries[0].offset:entries[0].offset + entries[0].size])
    if hdr is None:
        return None
    active = set()
    for i in slots:
        off = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - slots.start)
        if is_valid_name(read_utf16(hdr, off, 16)):
            active.add(i)
    return active or None


# ═════════════════════════════════════════════════════════════════════════════
#  Dark Souls 1 family: DSR (full) and PtDE (inventory tier)
# ═════════════════════════════════════════════════════════════════════════════

## @brief Anchor pattern that sits next to the DSR character block. Stats are read
#         at signed distances from wherever this is found.
DSR_MAGIC = bytes.fromhex("00FFFFFFFF000000000000000000000000FFFFFFFF")
## @brief DSR field distances from the anchor.
DSR_SOULS_D, DSR_HP_D, DSR_STAM_D, DSR_LEVEL_D, DSR_CLASS_D, DSR_HUM_D = -291, -419, -391, -295, -233, -307
DSR_NG_D, DSR_NAME_D = 0x1E3A7, -271
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
def ds1_character(buf, item_db, m, game, ng):
    stats = OrderedDict((k, u8(buf, m + d)) for k, d in DSR_STAT_D.items())
    buckets, unknown = ds1_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    name = read_utf16(buf, m + DSR_NAME_D, 13)
    return {
        "tier": "full", "game": game,
        "name": name if is_valid_name(name) else "(unnamed slot)",
        "klass": DS1_CLASS.get(u8(buf, m + DSR_CLASS_D)),
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


# ═════════════════════════════════════════════════════════════════════════════
#  Dark Souls III — inventory tier by id-scan
#
#  DS3 keeps stats behind offsets that shift between patches, but its item ids are
#  full 32-bit and sparse, so they can be found by scanning the slot for known ids
#  instead of trusting a fixed offset. Each held item is a 16-byte record: the id,
#  then the quantity. The inventory is a set of contiguous, category-sorted runs
#  of these records, which is exactly what the scan keys on.
# ═════════════════════════════════════════════════════════════════════════════

## @brief DS3 held-item record size and the offset of the quantity within it.
DS3_RECORD, DS3_QTY_OFF = 16, 4

## @brief DS3 stat block as signed distances from the Vigor field (the anchor).
#  Nine attributes — eight contiguous uint32, then Luck after a two-field gap —
#  in the game's own storage order. Read against a real save (all offsets checked
#  on both a maxed and a fresh character in the same file).
DS3_STAT_D = OrderedDict([
    ("Vigor", 0), ("Attunement", 4), ("Endurance", 8), ("Vitality", 12),
    ("Strength", 16), ("Dexterity", 20), ("Intelligence", 24), ("Faith", 28),
    ("Luck", 40)])
## @brief DS3 max HP, stamina, soul level and souls, same anchor-relative scheme.
DS3_HP_D, DS3_STAM_D, DS3_LEVEL_D, DS3_SOULS_D = -40, -12, 44, 48
## @brief DS3's soul-level identity: level == (sum of all nine attributes) - 89.
#  Deprived (all 10, sum 90) is level 1, and it holds at every level. This is the
#  content check that pins the stat block without a per-patch offset table.
DS3_LEVEL_BASE = 89
## @brief Shortest run of consecutive records that counts as real inventory. Long
#         enough to shrug off a stray id landing in unrelated data.
SCAN_MIN_RUN = 3


##
# @brief Load an id-scan database: per-category JSON of @c {name: id}, flattened
#        to @c {id: (name, category)}.
# @param db_dir Folder of category JSON files.
# @param files  Filename-stem to category mapping.
# @return The flat lookup, or {} if the folder is absent.
def load_scan_db(db_dir, files):
    if not os.path.isdir(db_dir):
        return {}
    db = {}
    for stem, cat in files.items():
        path = os.path.join(db_dir, stem + ".json")
        if os.path.exists(path):
            for name, iid in json.load(open(path, encoding="utf-8")).items():
                db.setdefault(int(iid), (name, cat))
    return db


##
# @brief Find inventory by scanning for known item ids in fixed-size records.
# @details Collects every offset whose uint32 is a known id, groups those that sit
# one record apart into runs, and keeps runs of at least @c SCAN_MIN_RUN. Each
# surviving record contributes its id and quantity. Duplicate ids are summed. A
# quantity outside a sane range drops the record — a cheap guard against a false
# run of look-alike bytes.
# @param buf  The decrypted slot data.
# @param iddb The flat id lookup from @ref load_scan_db.
# @return @c (buckets, unknown_count), buckets mapping category to @c (name, qty).
def scan_inventory(buf, iddb):
    positions = [o for o in range(0, len(buf) - 8)
                 if int.from_bytes(buf[o:o + 4], "little") in iddb]
    buckets, seen, unknown = defaultdict(dict), set(), 0
    i, n = 0, len(positions)
    while i < n:
        j = i
        while j + 1 < n and positions[j + 1] - positions[j] == DS3_RECORD:
            j += 1
        if j - i + 1 >= SCAN_MIN_RUN:
            for k in range(i, j + 1):
                o = positions[k]
                if o in seen:
                    continue
                seen.add(o)
                iid = int.from_bytes(buf[o:o + 4], "little")
                qty = u32(buf, o + DS3_QTY_OFF) or 0
                if 1 <= qty <= 9999:
                    name, cat = iddb[iid]
                    bucket = buckets[cat]
                    bucket[name] = bucket.get(name, 0) + qty
        i = j + 1
    return {c: list(v.items()) for c, v in buckets.items()}, unknown


##
# @brief Locate the DS3 stat block by content, or None if none validates.
# @details DS3's stat offsets move between patches, so the block is not read from
# a fixed offset — it is found. For each 4-aligned position, treat the next nine
# uint32 as the attributes and accept only where each is 1..99 *and* their sum
# minus @ref DS3_LEVEL_BASE equals the stored soul level. That identity is DS3's
# own level formula, so a coincidental match on unrelated bytes is not credible.
# @param buf The decrypted slot data.
# @return The Vigor-field offset (the anchor), or None.
def ds3_find_stats(buf):
    dists = list(DS3_STAT_D.values())
    v, end = 0, len(buf) - DS3_SOULS_D - 4
    while v < end:
        first = u32(buf, v)
        if first is not None and 1 <= first <= 99:
            vals = [u32(buf, v + d) for d in dists]
            lvl = u32(buf, v + DS3_LEVEL_D)
            if (all(x is not None and 1 <= x <= 99 for x in vals)
                    and lvl is not None and 1 <= lvl <= 802
                    and sum(vals) - DS3_LEVEL_BASE == lvl):
                return v
        v += 4
    return None


##
# @brief Parse one DS3 slot into the unified dict (full tier where stats validate).
# @details Inventory comes from the id-scan; the name is supplied by the caller
# from the load-screen roster. Stats are located by content (@ref ds3_find_stats)
# and, when the level identity confirms them, promote the slot to full tier. When
# it does not (an unrecognised patch), stats are dropped and the slot stays
# inventory tier — a missing number beats a wrong one. Origin class and NG+ are
# not calibrated and are omitted. Returns None when the slot has no inventory.
# @param buf  The decrypted slot data.
# @param iddb The flat DS3 id lookup.
# @param name The character name from the roster, or None.
# @return A unified character dict, or None if the slot is empty.
def ds3_parse(buf, iddb, name):
    inv = scan_inventory(buf, iddb)[0]
    if not inv:
        return None
    goods = inv.get("goods", [])
    v = ds3_find_stats(buf)
    stats = OrderedDict((k, u32(buf, v + d)) for k, d in DS3_STAT_D.items()) \
        if v is not None else OrderedDict()
    return {
        "tier": "full" if stats else "inventory", "game": "ds3",
        "name": name if (name and is_valid_name(name)) else "(unnamed slot)",
        "klass": None, "stats": stats, "soul_memory": None, "humanity": None,
        "ng_plus": None,
        "level": u32(buf, v + DS3_LEVEL_D) if v is not None else None,
        "souls": u32(buf, v + DS3_SOULS_D) if v is not None else None,
        "stamina": u32(buf, v + DS3_STAM_D) if v is not None else None,
        "hp": u32(buf, v + DS3_HP_D) if v is not None else None,
        "boss_souls": find_boss_souls(goods), "key_items": find_key_goods(goods),
        "inv": inv, "unknown_count": 0,
    }


## @brief DS3 id-scan tables: filename stem to category.
DS3_DB_FILES = {"weapons": "weapons", "armors": "armors", "rings": "rings",
                "goods": "goods", "bolts": "bolts", "spells": "spells"}


# ═════════════════════════════════════════════════════════════════════════════
#  Elden Ring — inventory tier by GaItem walk
#
#  Elden Ring's held-inventory list is patch-fragile (a sequential parse where one
#  wrong field size derails everything), but the GaItem array near the slot start
#  is not: it is every item instance the character owns, {handle, item_id}, and it
#  is reachable in the first 0x20 bytes. Walking it yields the owned-item set by
#  name. Structure and field layout follow ClayAmore/ER-Save-Editor.
# ═════════════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════════════
#  Elden Ring — roster (name lookup, still used for the slot label)
# ═════════════════════════════════════════════════════════════════════════════

## @brief Header-entry index, occupancy-flag offset, first-descriptor offset,
#         descriptor stride, and max name length, per game.
ROSTER_PARAMS = {
    "ds3": {"menu": 10, "occ": 4244, "desc": 4254, "stride": 554, "namelen": 16, "decrypt": DS3_KEY},
    "er":  {"menu": 10, "occ": 6484, "desc": 6494, "stride": 588, "namelen": 16, "decrypt": None},
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


# ═════════════════════════════════════════════════════════════════════════════
#  Markdown rendering
# ═════════════════════════════════════════════════════════════════════════════

## @brief Short attribute headers for the table.
STAT_ABBR = {"Vigor": "VGR", "Endurance": "END", "Vitality": "VIT",
             "Attunement": "ATN", "Strength": "STR", "Dexterity": "DEX",
             "Adaptability": "ADP", "Intelligence": "INT", "Faith": "FTH",
             "Resistance": "RES", "Luck": "LCK", "Mind": "MND", "Arcane": "ARC"}
## @brief Category id to printed heading (covers every id scheme / game).
CAT_TITLE = {"weapons": "Weapons", "armors": "Armor", "rings": "Rings",
             "talismans": "Talismans", "spells": "Spells", "bolts": "Ammunition",
             "upgrade": "Upgrade Materials", "consumables": "Consumables",
             "online": "Summon & Covenant Items", "goods": "Consumables & Goods",
             "ashes": "Ashes of War", "emotes": "Gestures",
             "bosssouls": "Boss Souls", "items": "Items Owned"}
## @brief Print order for inventory categories, mirroring the in-game item menu.
#  (`goods` is the lumped consumables bucket the non-DS2 games still use.)
CAT_ORDER = ["weapons", "armors", "rings", "talismans", "spells", "bolts", "upgrade",
             "consumables", "goods", "ashes", "online", "bosssouls", "emotes", "items"]


##
# @brief Guess a build label from the attribute spread. A rough label, not gospel.
# @param stats The character's attribute dict.
# @return A short description, or None if there are no stats to judge.
def guess_build(stats):
    if not stats:
        return None
    g = lambda k: stats.get(k) or 0
    phys, cast = g("Strength") + g("Dexterity"), g("Intelligence") + g("Faith") + g("Attunement")
    if cast > phys:
        return "caster / hybrid (high INT/FTH/ATN)"
    if g("Strength") >= g("Dexterity") + 6:
        return "strength-focused melee"
    if g("Dexterity") >= g("Strength") + 6:
        return "dexterity-focused melee"
    return "quality / balanced melee"


## @brief Format a value, or "—" when it is unknown (None).
def fmt(value):
    return "—" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


##
# @brief Render one full/inventory-tier character as a Markdown section.
# @param ch      A unified character dict.
# @param slot_no The 1-based save-slot number.
# @return The Markdown for this character.
def md_for_character(ch, slot_no):
    L = [f"## Slot {slot_no}: {ch['name']}", ""]
    if ch["level"] is not None:
        L.append(f"- **{'Level' if ch['game'] == 'er' else 'Soul Level'}:** {ch['level']}")
    if ch["klass"]:
        L.append(f"- **Class:** {ch['klass']}")
    if ch.get("covenant"):
        L.append(f"- **Covenant:** {ch['covenant']}")
    if ch["ng_plus"] is not None:
        ng = "New Game" if ch["ng_plus"] == 0 else f"New Game +{ch['ng_plus']}"
        L.append(f"- **Playthrough:** {ng}")
    if ch["soul_memory"] is not None:
        L.append(f"- **Soul Memory:** {fmt(ch['soul_memory'])}  _(total souls earned — main progress metric)_")
    if ch["souls"] is not None:
        L.append(f"- **{'Runes' if ch['game'] == 'er' else 'Souls'} held:** {fmt(ch['souls'])}")
    if ch["humanity"] is not None:
        L.append(f"- **Humanity:** {ch['humanity']}")
    if ch["hp"] is not None:
        L.append(f"- **Max HP:** {fmt(ch['hp'])}")
    if ch.get("hollow_lvl"):
        L.append(f"- **Hollowing:** {ch['hollow_lvl']}  _(higher = more deaths without an effigy)_")
    if ch["stamina"] is not None:
        L.append(f"- **Stamina:** {fmt(ch['stamina'])}")
    build = guess_build(ch["stats"])
    if build:
        L.append(f"- **Build:** {build}")
    L.append("")

    if ch["stats"]:
        keys = list(ch["stats"].keys())
        L += ["### Attributes", "",
              "| " + " | ".join(STAT_ABBR.get(k, k[:3].upper()) for k in keys) + " |",
              "|" + "----|" * len(keys),
              "| " + " | ".join(str(ch["stats"][k]) for k in keys) + " |", ""]
    elif ch["tier"] == "inventory":
        L += ["_Attributes are not printed for this slot: its stat block did not "
              "validate (an unrecognised patch or an edited save), and a wrong "
              "number is worse than none. Inventory and progress below are read "
              "directly._", ""]

    def bullets(items):
        return [f"- {n}" + (f" ×{q}" if q and q > 1 else "") for n, q in items]

    # Boss souls / remembrances that live in their own top section (every game but
    # DS2, whose boss souls are a proper inventory category — see below).
    if ch["boss_souls"]:
        header = ("### Remembrances Held  _(major bosses defeated, not yet traded)_"
                  if ch["game"] == "er"
                  else "### Boss Souls Held  _(bosses defeated, soul not yet consumed)_")
        L += [header, ""] + bullets(ch["boss_souls"]) + [""]
    if ch["key_items"]:
        L += ["### Key Items  _(progress / areas & shortcuts unlocked)_", ""]
        L += bullets(ch["key_items"]) + [""]
    if ch.get("bonfires"):
        L += [f"### Bonfires Discovered ({len(ch['bonfires'])})  _(areas reached — a "
              "floor on progress)_", ""]
        L += [f"- {b}" for b in ch["bonfires"]] + [""]
    if ch.get("bosses"):
        SRC = {"flag": "confirmed", "soul": "soul held", "gate": "progression"}
        L += [f"### Bosses Defeated ({len(ch['bosses'])})  _(a floor — from defeat "
              "flags, held boss souls, and progression; a boss whose soul was consumed "
              "and isn't gated may still be missing)_", ""]
        for boss, srcs in ch["bosses"].items():
            L.append(f"- {boss}  _({', '.join(SRC[s] for s in srcs)})_")
        L.append("")

    L += ["### Inventory", ""]
    for cat in CAT_ORDER:
        items = ch["inv"].get(cat)
        if not items:
            continue
        # Boss souls split into the game's own two grades: the four "Old" great
        # souls, then the ordinary boss souls. Everything else is one heading.
        if cat == "bosssouls":
            great = [it for it in items if it[0] in DS2_GREAT_SOULS]
            normal = [it for it in items if it[0] not in DS2_GREAT_SOULS]
            for title, group in (("Great Boss Souls", great), ("Boss Souls", normal)):
                if group:
                    L += [f"#### {title}", ""] + bullets(group) + [""]
        else:
            L += [f"#### {CAT_TITLE[cat]}", ""] + bullets(items) + [""]
    if ch["unknown_count"]:
        L += [f"_{ch['unknown_count']} inventory item(s) had IDs not in the name "
              "database (upgraded / infused variants) and were omitted._", ""]
    return "\n".join(L)


# ═════════════════════════════════════════════════════════════════════════════
#  Driver
# ═════════════════════════════════════════════════════════════════════════════

## @brief Public source repository, printed in every generated file.
REPO_URL = "https://github.com/darthdemono/SL2-TO-MD"

## @brief Per-game config: title, tier, db, decrypt/parse, slot range, and a
#         one-line "how it works" for the file header.
GAMES = {
    "ds2sotfs": {"title": "Dark Souls II: Scholar of the First Sin", "tier": "full",
                 "db": ("db_ds2", True, DS2_DB_FILES), "decrypt": decrypt_ds2,
                 "parse": ds2_parse, "slots": range(1, 11),
                 "active": ds2_active_slots, "augment": ds2_augment,
                 "how": "the save is scrambled with a lock (AES-128 encryption) "
                        "whose key ships inside the game itself, so the tool applies "
                        "that key to unlock the raw data. From there each character's "
                        "details sit at fixed, known positions: name, level, the nine "
                        "attributes, and souls are read straight from those spots. "
                        "Every inventory entry stores a numeric item ID, which the "
                        "tool looks up in a name table built from the community's "
                        "SOTFS ID list, so you read 'Longsword' instead of a number; "
                        "reinforcement level and infusion sit in a separate field of "
                        "each item record and are shown as a '+N' suffix and an "
                        "infusion prefix (e.g. 'Fire Longsword +6')"},
    "dsr": {"title": "Dark Souls Remastered", "tier": "full",
            "db": ("db_ds1", False, DS1_DB_FILES),
            "decrypt": lambda b: decrypt_iv_prefixed(b, DSR_KEY),
            "parse": dsr_parse, "slots": range(0, 10),
            "how": "the save is locked the same way (AES-128 encryption, key shipped "
                   "inside the game), so the tool unlocks it first. The character "
                   "block does not sit at a fixed spot — it shifts as the save grows "
                   "— so the tool locates it by a fixed marker (a 'magic' byte "
                   "pattern) that always sits beside it, then reads the level, stats, "
                   "and souls at known distances from that marker. The inventory is "
                   "found by a second, separate marker, and every item ID is matched "
                   "to its real name"},
    "ptde": {"title": "Dark Souls: Prepare to Die Edition", "tier": "full",
             "db": ("db_ds1", False, DS1_DB_FILES), "decrypt": decrypt_none,
             "parse": ptde_parse, "slots": range(0, 10),
             "how": "this original edition does not encrypt its save at all, so "
                    "there is nothing to unlock. It stores a character the same way "
                    "Remastered does but without that version's marker, so the tool "
                    "finds the character by locating the name text and reads the "
                    "level, stats, souls, and inventory that sit at known distances "
                    "around it"},
    "ds3": {"title": "Dark Souls III", "tier": "full",
            "db": ("db_ds3", DS3_DB_FILES),
            "decrypt": lambda b: decrypt_iv_prefixed(b, DS3_KEY),
            "menu": 10, "slots": range(0, 10),
            "how": "the save is locked with AES-128 encryption, key shipped in the "
                   "game, so the tool unlocks it first. The stats do not sit at a "
                   "fixed position, and that position moves between game patches, so "
                   "instead of trusting a location the tool searches for the stat "
                   "block by its content: it looks for the run of nine numbers that, "
                   "added together, equal the character's stored level — a rule the "
                   "game itself follows, which makes a wrong match almost impossible. "
                   "Items are found by scanning the slot for known IDs and matched to "
                   "names"},
    "er": {"title": "Elden Ring", "tier": "full", "db": "db_er",
           "decrypt": decrypt_none, "menu": 10, "slots": range(0, 10),
           "how": "the save is not encrypted, so the tool reads it directly. Like "
                  "Dark Souls III, the stats are found by content rather than a fixed "
                  "spot — the tool looks for the eight numbers that add up to the "
                  "character's level — which matters more here because that stat "
                  "block sits in a different place for every character. Every item "
                  "the character owns is read from the game's item array and matched "
                  "to its real name"},
}


## @brief One-line header note for a generated file: the repo, and how this game
#         is read. Replaces the old boilerplate; states the source, not caveats.
def disclaimer_for(cfg):
    return (f"> Automated dump of the save. Code Repo: {REPO_URL} . "
            f"How it works for {cfg['title']}: {cfg['how']}.")


##
# @brief Build the Markdown document for one save file.
# @param data     The full file bytes.
# @param filename The source filename, for the header line.
# @param base_dir Folder holding the @c db_* item-table directories.
# @return The complete Markdown string.
def convert(data, filename, base_dir):
    entries = parse_bnd4(data)
    game = detect_game(data, entries)
    cfg = GAMES[game]
    disclaimer = disclaimer_for(cfg)

    head = [f"# {cfg['title']} — Playthrough Save Summary", "",
            f"_Source: `{filename}` · generated {datetime.now():%Y-%m-%d %H:%M} · sl2_to_md_",
            "", f"- **Game:** {cfg['title']}", f"- **Support tier:** {cfg['tier']}", ""]

    # Elden Ring: identity + stats (content-scan) + owned items (GaItem walk).
    # Item coverage is partial — see the closing note.
    if game == "er":
        iddb = load_er_db(os.path.join(base_dir, cfg["db"]))
        if not iddb:
            sys.exit(f"No item database found in {os.path.join(base_dir, cfg['db'])}")
        menu_entry = entries[cfg["menu"]]
        roster = er_roster(data[menu_entry.offset:menu_entry.offset + menu_entry.size])
        characters = []
        for i in cfg["slots"]:
            if i >= len(entries):
                continue
            active, name, level = roster[i] if i < len(roster) else (True, None, None)
            if not active:
                continue
            slot = cfg["decrypt"](data[entries[i].offset:entries[i].offset + entries[i].size])
            if slot is None:
                continue
            ch = er_parse(slot, iddb, name, level)
            if ch is not None:
                characters.append((i, ch))
        head += [f"- **Characters found:** {len(characters)}", "", disclaimer, "", "---", ""]
        body = ["_No populated character slots found._"] if not characters else []
        for i, ch in characters:
            body.append(md_for_character(ch, i - cfg["slots"].start + 1))
            body += ["---", ""]
        body += ["_Elden Ring identity, attributes, and runes are read directly; the "
                 "**item list is partial**. Owned items come from the GaItem array, "
                 "which holds weapons, armour and Ashes of War — each named against "
                 "its own type table (so no cross-type mis-naming) and reinforced/"
                 "affinity weapons resolve to the base weapon (the upgrade level "
                 "itself is not read). Talismans, spells and consumable goods live in "
                 "a separate held-inventory that shifts between patches and is not "
                 "parsed, so they are not listed. What is listed is really owned._"]
        return "\n".join(head + body)

    # DS3: names from the header, inventory by id-scan, stats by content-scan.
    if game == "ds3":
        db_dir = os.path.join(base_dir, cfg["db"][0])
        iddb = load_scan_db(db_dir, cfg["db"][1])
        if not iddb:
            sys.exit(f"No item database found in {db_dir}")
        menu_entry = entries[cfg["menu"]]
        menu = cfg["decrypt"](data[menu_entry.offset:menu_entry.offset + menu_entry.size])
        names = dict(parse_roster(menu or b"", game)) if menu is not None else {}
        characters = []
        for i in cfg["slots"]:
            if i >= len(entries):
                continue
            slot = cfg["decrypt"](data[entries[i].offset:entries[i].offset + entries[i].size])
            if slot is None:
                continue
            ch = ds3_parse(slot, iddb, names.get(i))
            if ch is not None:
                characters.append((i, ch))
        head += [f"- **Characters found:** {len(characters)}", "", disclaimer, "", "---", ""]
        body = ["_No populated character slots found._"] if not characters else []
        for i, ch in characters:
            body.append(md_for_character(ch, i - cfg["slots"].start + 1))
            body += ["---", ""]
        return "\n".join(head + body)

    # Full / inventory tier: decrypt each slot and parse it.
    db_dir = os.path.join(base_dir, cfg["db"][0])
    item_db = load_item_db(db_dir, cfg["db"][1], cfg["db"][2])
    if not item_db:
        sys.exit(f"No item database found in {db_dir}")

    # Some games keep a deleted character's block intact and only drop it from the
    # menu; an "active" hook returns the still-listed entries so ghosts are skipped.
    active = cfg["active"](data, entries, cfg["slots"]) if "active" in cfg else None

    characters = []
    for i in cfg["slots"]:
        if i >= len(entries):
            continue
        if active is not None and i not in active:
            continue
        blob = data[entries[i].offset:entries[i].offset + entries[i].size]
        game_data = cfg["decrypt"](blob)
        if game_data is None:
            continue
        ch = cfg["parse"](game_data, item_db)
        if ch is not None:
            if "augment" in cfg:
                cfg["augment"](ch, data, entries, i, base_dir)
            characters.append((i, ch))

    head += [f"- **Characters found:** {len(characters)}", "", disclaimer, "", "---", ""]
    body = []
    if not characters:
        body.append("_No populated character slots found._")
    for i, ch in characters:
        body.append(md_for_character(ch, i - cfg["slots"].start + 1))
        body += ["---", ""]
    return "\n".join(head + body)


## @brief Folders a Souls save can live in, per OS. Each game keeps its `.sl2` in
#  a game-named subfolder, hence the trailing `*/`. Steam/Proton, Heroic, Lutris,
#  and plain Wine all mirror the Windows `%APPDATA%` tree inside a prefix, so the
#  tail of every glob is the same `.../AppData/Roaming/<game>/*.sl2`.
def _save_globs():
    globs = ["*.sl2", os.path.join("*", "*.sl2")]      # cwd and one level down
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA")
    if appdata:                                        # native Windows
        globs.append(os.path.join(appdata, "*", "*.sl2"))
    roaming = "drive_c/users/steamuser/AppData/Roaming/*/*.sl2"
    user_roaming = "drive_c/users/*/AppData/Roaming/*/*.sl2"
    # Steam through Proton.
    for steam in (".local/share/Steam", ".steam/steam", ".steam/root"):
        globs.append(os.path.join(home, steam, "steamapps/compatdata/*/pfx", roaming))
    # Heroic (Epic / GOG) Wine prefixes.
    for heroic in ("Games/Heroic/Prefixes/default/*/pfx",
                   ".config/heroic/prefixes/default/*/pfx", "Games/Heroic/*/pfx"):
        globs.append(os.path.join(home, heroic, roaming))
    # Lutris and a plain ~/.wine prefix (user-named, not always "steamuser").
    globs.append(os.path.join(home, ".local/share/lutris/*/pfx", user_roaming))
    globs.append(os.path.join(home, ".wine", user_roaming))
    return globs


##
# @brief Find a `.sl2` when none was given on the command line.
# @details Globs the current folder and the usual Steam/Proton and Windows save
# locations, and returns the most recently modified match — the live character is
# almost always the newest file. Exits with a clear message if nothing is found.
# @return The path to the chosen save.
def auto_find_save():
    found = []
    for pat in _save_globs():
        found += glob.glob(pat)
    found = sorted(set(found), key=lambda p: os.path.getmtime(p), reverse=True)
    if not found:
        sys.exit("No .sl2 found in the current folder or the usual save locations. "
                 "Pass the path explicitly: sl2_to_md.py <save.sl2>")
    if len(found) > 1:
        print(f"Auto-detected {len(found)} saves; using the newest: {found[0]}")
        print("  (pass a path to pick another)")
    else:
        print(f"Auto-detected save: {found[0]}")
    return found[0]


##
# @brief Program entry point.
# @return None. Writes the Markdown file and prints where it went.
def main():
    ap = argparse.ArgumentParser(
        description="FromSoftware .sl2 save -> Markdown playthrough summary "
                    "(DS PtDE/Remastered, DS2 SOTFS, DS3, Elden Ring)")
    ap.add_argument("sl2", nargs="?",
                    help="path to the .sl2 save (auto-detected if omitted)")
    ap.add_argument("-o", "--out", default="playthrough.md", help="output .md path")
    args = ap.parse_args()

    sl2 = args.sl2 or auto_find_save()
    if not os.path.isfile(sl2):
        sys.exit(f"No such file: {sl2}")
    with open(sl2, "rb") as f:
        data = f.read()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    md = convert(data, os.path.basename(sl2), base_dir)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
