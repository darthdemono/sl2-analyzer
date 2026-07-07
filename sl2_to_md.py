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
# Seven save variants share one archive format but diverge in the details, and
# not all of them are fully mapped in public tooling. Each game is handled at the
# highest tier it can be trusted at, and the output states the tier plainly:
#
# | Game            | Tier      | What comes out                                  |
# |-----------------|-----------|-------------------------------------------------|
# | DS2: SOTFS      | full      | identity, stats, souls, inventory, progress     |
# | Dark Souls R.   | full      | identity, stats, souls, inventory, progress     |
# | Dark Souls PtDE | inventory | full inventory + progress + character list      |
# | DS2: vanilla    | blocked   | needs its AES key, which isn't public — see note |
# | Dark Souls III  | roster    | character list (name per slot) from the header  |
# | Elden Ring      | roster    | character list (name per slot) from the header  |
#
# A tier is a promise: everything printed at any tier is read from the save, not
# inferred and not guessed. PtDE stats and the DS3/ER stat blocks are not printed
# because their offsets are not calibrated in this build, and a wrong number is
# worse than a missing one.
#
# ### A note on "MISRA C"
# MISRA C is a coding standard for C, and this is Python, so it does not apply
# literally. What carries over is the intent: validate everything at the boundary,
# never read past the end of a buffer, give every constant a name, keep functions
# single-purpose, and fail loudly instead of limping on with garbage. Every
# integer read here goes through a bounds-checked helper that returns @c None
# rather than raising or reading out of range, and the archive structure is
# validated before any offset is trusted.
#
# @note Encryption keys and offsets come from the community: DS2 tables from
#       alfizari/Dark-Souls-2-Save-Editor-PS4-PC; DSR decryption from
#       jtesta/souls_givifier; DSR/DS1 tables and anchor offsets from
#       alfizari/Dark-Souls-Remastered-Save-Editor; DS3/ER keys and header layout
#       from jtesta/souls_givifier; DS2 key from mi5hmash/SL2Bonfire.
#
# @author Jubair Hasan (Joy / DarthDemono)
#
import argparse
import hashlib
import json
import os
import struct
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


##
# @brief Scan a bounded window for the first plausible UTF-16LE name.
# @details Used where the exact name offset is not calibrated (PtDE): step
# through the window, and the moment a run of valid name characters at least
# @c min_len long appears, take it. Bounded so a bad slot cannot spin.
# @param buf     The bytes to search.
# @param limit   How far into the buffer to look.
# @param min_len Shortest run that counts as a name.
# @return The first valid name found, or None.
def scan_first_name(buf, limit=1024, min_len=2):
    i, cap = 0, min(limit, len(buf) - 1)
    while i < cap:
        if 32 <= buf[i] < 0x7F and buf[i + 1] == 0:
            j, s = i, bytearray()
            while j < len(buf) - 1 and 32 <= buf[j] < 0x7F and buf[j + 1] == 0:
                s.append(buf[j])
                j += 2
            if len(s) >= min_len:
                cand = s.decode("ascii", "ignore")
                if is_valid_name(cand):
                    return cand
            i = j
        else:
            i += 1
    return None


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
        # Both DS2 variants share the signature. SOTFS is the one whose key works.
        blob = data[entries[1].offset:entries[1].offset + entries[1].size]
        pt = _aes_cbc(DS2_KEY, blob[16:32], blob[32:])
        dlen = u32(pt, 0)
        return "ds2sotfs" if (dlen is not None and 0 < dlen <= len(pt) - 4) else "ds2vanilla"
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
DS2_DB_FILES = {"items": "goods", "rings": "rings", "weapons": "weapons",
                "armors": "armors", "key": "keys", "bolts": "bolts",
                "spells": "spells", "upgrade": "upgrade"}
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
        db = {}
        for stem, cat in files.items():
            path = os.path.join(db_dir, stem + ".json")
            if os.path.exists(path):
                for name, hx in json.load(open(path, encoding="utf-8")).items():
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
## @brief DS2 attribute offsets (uint16 each), in display order; Level last.
DS2_STAT_OFF = OrderedDict([
    ("Vigor", 32), ("Endurance", 34), ("Vitality", 36), ("Attunement", 38),
    ("Strength", 40), ("Dexterity", 42), ("Adaptability", 44),
    ("Intelligence", 46), ("Faith", 48), ("Level", 0x38)])
## @brief DS2 inventory regions (start, end); 16-byte slots throughout.
DS2_INV_RANGE, DS2_KEY_RANGE = (0x1E2C, 0x10E1C), (0x10E30, 0x11DF0)
## @brief DS2 categories whose slot +8 field is a real count (float durability
#         elsewhere).
DS2_STACKABLE = {"goods", "bolts", "spells", "upgrade", "keys"}


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
            iid, qty = u32(buf, o), u32(buf, o + 8)
            o += 16
            if not iid:
                continue
            info = item_db.get(iid)
            if info is None:
                unknown += 1
                continue
            name, cat = info
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
        "tier": "full", "game": "ds2sotfs", "name": ds2_name(buf), "klass": None,
        "level": stats.pop("Level"), "stats": stats,
        "souls": u32(buf, DS2_SOULS_OFF), "soul_memory": u32(buf, DS2_SOULMEM_OFF),
        "humanity": None, "stamina": None, "hp": u32(buf, DS2_HP_OFF),
        "ng_plus": max(0, (u16(buf, DS2_NG_OFF) or 1) - 1),
        "boss_souls": find_boss_souls(inv.get("goods", [])),
        "key_items": inv.pop("keys", []), "inv": inv, "unknown_count": unknown,
    }


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
        name = item_db.get(cat, {}).get(iid) if cat else None
        if name is None:
            unknown += 1
            continue
        buckets[cat].append((name, qty))
    return buckets, unknown


## @brief Parse one DSR slot into the unified dict (full tier), or None if empty.
def dsr_parse(buf, item_db):
    m = dsr_find_anchor(buf)
    if m is None:
        return None
    stats = OrderedDict((k, u8(buf, m + d)) for k, d in DSR_STAT_D.items())
    buckets, unknown = ds1_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    name = read_utf16(buf, m + DSR_NAME_D, 13)
    return {
        "tier": "full", "game": "dsr",
        "name": name if is_valid_name(name) else read_utf16(buf, DSR_NAME_D + m, 13),
        "klass": DS1_CLASS.get(u8(buf, m + DSR_CLASS_D)),
        "level": u16(buf, m + DSR_LEVEL_D), "stats": stats,
        "souls": u32(buf, m + DSR_SOULS_D), "soul_memory": None,
        "humanity": u8(buf, m + DSR_HUM_D), "stamina": u32(buf, m + DSR_STAM_D),
        "hp": u32(buf, m + DSR_HP_D), "ng_plus": u8(buf, m + DSR_NG_D) or 0,
        "boss_souls": find_boss_souls(inv.get("goods", [])),
        "key_items": find_key_goods(inv.get("goods", [])),
        "inv": inv, "unknown_count": unknown,
    }


##
# @brief Parse one PtDE slot (inventory tier).
# @details PtDE is unencrypted DS1, and its inventory sits at the same anchor as
# DSR, so the full item list comes out cleanly. The stat block, though, is at
# distances this build has not calibrated for PtDE, so no stats are emitted — a
# missing number beats a wrong one. A slot counts as present if it has an
# inventory anchor.
def ptde_parse(buf, item_db):
    if buf.find(DS1_INV_ANCHOR, DS1_INV_START) == -1:
        return None
    buckets, unknown = ds1_inventory(buf, item_db)
    inv = {c: merge_qty(v) for c, v in buckets.items()}
    name = scan_first_name(buf, limit=600)  # PtDE name offset isn't calibrated
    return {
        "tier": "inventory", "game": "ptde",
        "name": name or "(unnamed slot)",
        "klass": None, "level": None, "stats": OrderedDict(),
        "souls": None, "soul_memory": None, "humanity": None, "stamina": None,
        "hp": None, "ng_plus": None,
        "boss_souls": find_boss_souls(inv.get("goods", [])),
        "key_items": find_key_goods(inv.get("goods", [])),
        "inv": inv, "unknown_count": unknown,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  Dark Souls III / Elden Ring — roster tier (character names from the header)
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
             "Resistance": "RES"}
## @brief Category id to printed heading (covers both id schemes).
CAT_TITLE = {"weapons": "Weapons", "armors": "Armor", "rings": "Rings",
             "spells": "Spells", "goods": "Consumables & Goods",
             "bolts": "Ammunition", "upgrade": "Upgrade Materials"}
## @brief Print order for inventory categories.
CAT_ORDER = ["weapons", "armors", "rings", "spells", "bolts", "upgrade", "goods"]


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
# @param ch         A unified character dict.
# @param slot_label A short label naming the slot.
# @return The Markdown for this character.
def md_for_character(ch, slot_label):
    L = [f"## {ch['name']}  ·  {slot_label}", ""]
    if ch["level"] is not None:
        L.append(f"- **Soul Level:** {ch['level']}")
    if ch["klass"]:
        L.append(f"- **Class:** {ch['klass']}")
    if ch["ng_plus"] is not None:
        ng = "New Game" if ch["ng_plus"] == 0 else f"New Game +{ch['ng_plus']}"
        L.append(f"- **Playthrough:** {ng}")
    if ch["soul_memory"] is not None:
        L.append(f"- **Soul Memory:** {fmt(ch['soul_memory'])}  _(total souls earned — main progress metric)_")
    if ch["souls"] is not None:
        L.append(f"- **Souls held:** {fmt(ch['souls'])}")
    if ch["humanity"] is not None:
        L.append(f"- **Humanity:** {ch['humanity']}")
    if ch["hp"] is not None:
        L.append(f"- **Max HP:** {fmt(ch['hp'])}")
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
        L += ["_Attributes and level are not printed for this game: its stat "
              "offsets are not calibrated in this build, and a wrong number is "
              "worse than none. Inventory and progress below are read directly._", ""]

    if ch["boss_souls"]:
        L += ["### Boss Souls Held  _(bosses defeated, soul not yet consumed)_", ""]
        L += [f"- {n}" + (f" ×{q}" if q and q > 1 else "") for n, q in ch["boss_souls"]]
        L.append("")
    if ch["key_items"]:
        L += ["### Key Items  _(progress / areas & shortcuts unlocked)_", ""]
        L += [f"- {n}" + (f" ×{q}" if q and q > 1 else "") for n, q in ch["key_items"]]
        L.append("")

    L += ["### Inventory", ""]
    for cat in CAT_ORDER:
        items = ch["inv"].get(cat)
        if not items:
            continue
        L += [f"**{CAT_TITLE[cat]}** ({len(items)})", ""]
        L += [f"- {n}" + (f" ×{q}" if q and q > 1 else "") for n, q in items]
        L.append("")
    if ch["unknown_count"]:
        L += [f"_{ch['unknown_count']} inventory item(s) had IDs not in the name "
              "database (upgraded / infused variants) and were omitted._", ""]
    return "\n".join(L)


# ═════════════════════════════════════════════════════════════════════════════
#  Driver
# ═════════════════════════════════════════════════════════════════════════════

## @brief Per-game title, db config, decrypt function, parse function, and slots.
GAMES = {
    "ds2sotfs": {"title": "Dark Souls II: Scholar of the First Sin", "tier": "full",
                 "db": ("db_ds2", True, DS2_DB_FILES), "decrypt": decrypt_ds2,
                 "parse": ds2_parse, "slots": range(1, 11)},
    "dsr": {"title": "Dark Souls Remastered", "tier": "full",
            "db": ("db_ds1", False, DS1_DB_FILES),
            "decrypt": lambda b: decrypt_iv_prefixed(b, DSR_KEY),
            "parse": dsr_parse, "slots": range(0, 10)},
    "ptde": {"title": "Dark Souls: Prepare to Die Edition", "tier": "inventory",
             "db": ("db_ds1", False, DS1_DB_FILES), "decrypt": decrypt_none,
             "parse": ptde_parse, "slots": range(0, 10)},
    "ds2vanilla": {"title": "Dark Souls II (vanilla)", "tier": "blocked"},
    "ds3": {"title": "Dark Souls III", "tier": "roster",
            "decrypt": lambda b: decrypt_iv_prefixed(b, DS3_KEY)},
    "er": {"title": "Elden Ring", "tier": "roster", "decrypt": decrypt_none},
}
## @brief The header note that states the honest limits, printed on every file.
DISCLAIMER = (
    "> Automated dump of the save. Everything printed is read directly from the "
    "save — no field is guessed. \"Bosses defeated\" and \"locations unlocked\" "
    "are **inferred** from boss souls and key items still held; the raw event-flag "
    "table (bonfires lit, bosses killed after their soul was spent) is not publicly "
    "mapped and is not decoded here.")


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

    head = [f"# {cfg['title']} — Playthrough Save Summary", "",
            f"_Source: `{filename}` · generated {datetime.now():%Y-%m-%d %H:%M} · sl2_to_md_",
            "", f"- **Game:** {cfg['title']}", f"- **Support tier:** {cfg['tier']}", ""]

    # Vanilla DS2: known game, but its AES key is not public, so nothing to read.
    if cfg["tier"] == "blocked":
        head += [DISCLAIMER, "", "---", "",
                 "## Not supported yet",
                 "",
                 "This is a **vanilla Dark Souls II** save (`DARKSII0000.sl2`). It is "
                 "encrypted with a key that is not published in any tool I could find, "
                 "so the slots cannot be decrypted. Re-save it in *Scholar of the First "
                 "Sin*, or drop the vanilla key into the script, and it will read fully. "
                 "Detection, structure, and everything else already work — only the key "
                 "is missing."]
        return "\n".join(head)

    # DS3 / ER: roster tier — character names from the header, and an honest note.
    if cfg["tier"] == "roster":
        menu = cfg["decrypt"](data[entries[ROSTER_PARAMS[game]["menu"]].offset:
                                   entries[ROSTER_PARAMS[game]["menu"]].offset
                                   + entries[ROSTER_PARAMS[game]["menu"]].size])
        roster = parse_roster(menu or b"", game) if menu is not None else []
        names = [n for _, n in roster]
        # Output guard: the load-screen table only shifts between patches, so if it
        # decodes to junk or the same name in every slot, the offsets don't fit this
        # save's version. Say that instead of printing fabricated names.
        reliable = bool(roster) and all(is_valid_name(n) for n in names) and \
            (len(roster) == 1 or len(set(names)) > 1)
        head += [DISCLAIMER, "", "---", ""]
        if reliable:
            head += [f"## Characters ({len(roster)})", ""]
            head += [f"- **Slot {i}:** {name}" for i, name in roster]
            head += ["",
                     "_This game is at **roster tier**: names are read from the save's "
                     "load-screen table, which is reliable. Stats and inventory are not "
                     "printed because their offsets are not mapped in this build for "
                     "this game. Drop the item-id tables and I can lift it to full._"]
        else:
            head += ["## Detected, but not readable in this build", "",
                     f"This is a **{cfg['title']}** save and it decrypts fine, but the "
                     "character-table offsets from public tooling do not line up with "
                     "this save's game version — they shifted across patches, and "
                     "trusting them here would print fabricated names. So nothing is "
                     "printed rather than something wrong. Recalibrating the offsets "
                     "against this exact version, plus the item-id tables, lifts it to "
                     "full."]
        return "\n".join(head)

    # Full / inventory tier: decrypt each slot and parse it.
    db_dir = os.path.join(base_dir, cfg["db"][0])
    item_db = load_item_db(db_dir, cfg["db"][1], cfg["db"][2])
    if not item_db:
        sys.exit(f"No item database found in {db_dir}")

    characters = []
    for i in cfg["slots"]:
        if i >= len(entries):
            continue
        blob = data[entries[i].offset:entries[i].offset + entries[i].size]
        game_data = cfg["decrypt"](blob)
        if game_data is None:
            continue
        ch = cfg["parse"](game_data, item_db)
        if ch is not None:
            characters.append((i, ch))

    head += [f"- **Characters found:** {len(characters)}", "", DISCLAIMER, "", "---", ""]
    body = []
    if not characters:
        body.append("_No populated character slots found._")
    for i, ch in characters:
        body.append(md_for_character(ch, f"slot entry {i}"))
        body += ["---", ""]
    return "\n".join(head + body)


##
# @brief Program entry point.
# @return None. Writes the Markdown file and prints where it went.
def main():
    ap = argparse.ArgumentParser(
        description="FromSoftware .sl2 save -> Markdown playthrough summary "
                    "(DS PtDE/Remastered, DS2 vanilla/SOTFS, DS3, Elden Ring)")
    ap.add_argument("sl2", help="path to the .sl2 save")
    ap.add_argument("-o", "--out", default="playthrough.md", help="output .md path")
    args = ap.parse_args()

    if not os.path.isfile(args.sl2):
        sys.exit(f"No such file: {args.sl2}")
    with open(args.sl2, "rb") as f:
        data = f.read()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    md = convert(data, os.path.basename(args.sl2), base_dir)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
