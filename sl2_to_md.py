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
# @see https://github.com/darthdemono/sl2-analyzer
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
                or n in ("Core of an Iron Golem", "Guardian Soul",
                         "Soul (Nito)", "Soul (Bed of Chaos)")):
            out.append((n, q))
    return out


## @brief Per-game folder holding a boss-soul → boss-name table (boss_souls.json).
#  DS2 runs its own richer multi-source inference; these cover the games whose only
#  proof-of-kill floor is the boss souls / remembrances the character still holds.
BOSS_SOUL_DB_DIR = {"dsr": "db_ds1", "ptde": "db_ds1", "ds3": "db_ds3", "er": "db_er"}

## @brief Load a game's boss-soul → boss-name table. Cached per (base_dir, subdir).
_BOSS_SOUL_CACHE = {}
def load_boss_soul_map(base_dir, subdir):
    key = (base_dir, subdir)
    if key not in _BOSS_SOUL_CACHE:
        path = os.path.join(base_dir, subdir, "boss_souls.json")
        try:
            with open(path, encoding="utf-8") as f:
                _BOSS_SOUL_CACHE[key] = json.load(f)
        except (OSError, ValueError):
            _BOSS_SOUL_CACHE[key] = {}
    return _BOSS_SOUL_CACHE[key]


## @brief Endgame-only progression prereqs: a proven-dead boss (key) implies its
#  mandatory predecessors (values) are dead too, tagged `gate`. Each key lists ALL
#  its predecessors (already flattened), so one closure pass suffices. DELIBERATELY
#  ENDGAME-ONLY, mirroring DS2's `DS2_BOSS_PREREQ` rule: only strictly-linear,
#  cannot-skip mandatory chains qualify — a mid-game gate would risk a false kill
#  (the core rule). Sourced from each game's fixed endgame route.
#
#  DS3: the four Lords of Cinder plus Iudex Gundyr are all mandatory to fight Soul
#  of Cinder, and Vordt/Dancer gate the only path forward (High Wall → … → Lothric
#  Castle). Aldrich sits past Pontiff Sulyvahn in Irithyll.
#  ER: Morgott (Leyndell) → Fire Giant (Forge) → Maliketh (Farum Azula) → Godfrey/
#  Hoarah Loux (Ashen Leyndell) is the fixed mandatory endgame chain; each requires
#  every earlier one. Morgott's own prereqs are player-choice great runes, so it
#  gates nothing specific.
BOSS_PREREQ = {
    "ds3": {
        "Soul of Cinder": ["Iudex Gundyr", "Vordt of the Boreal Valley",
                           "Dancer of the Boreal Valley", "Abyss Watchers",
                           "Aldrich, Devourer of Gods", "Yhorm the Giant",
                           "Lothric, Younger Prince"],
        "Lothric, Younger Prince": ["Dancer of the Boreal Valley",
                                    "Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Aldrich, Devourer of Gods": ["Pontiff Sulyvahn",
                                      "Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Dancer of the Boreal Valley": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Pontiff Sulyvahn": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Vordt of the Boreal Valley": ["Iudex Gundyr"],
    },
    "er": {
        "Godfrey, First Elden Lord (Hoarah Loux)": ["Maliketh, the Black Blade",
                                                    "Fire Giant",
                                                    "Morgott, the Omen King"],
        "Maliketh, the Black Blade": ["Fire Giant", "Morgott, the Omen King"],
        "Fire Giant": ["Morgott, the Omen King"],
    },
}

## @brief Bosses that CANNOT be skipped to finish the game, so **reaching NG+ proves
#  every one of them dead at least once** (tag `clear`). DS1 (dsr/ptde) is linear from
#  Anor Londo on: both bells (Gargoyles, Quelaag), Sen's/Anor Londo (Iron Golem, O&S),
#  the four Lord Souls (Nito, Bed of Chaos, Four Kings — needs Sif's ring — and Seath)
#  and Gwyn are all mandatory. Deliberately endgame-safe, the same core-rule caution as
#  the gate maps — no mid-game boss whose route can be skipped is listed. (DS2 handles
#  this itself in ds2_infer_bosses, seeding only its final boss Nashandra, because DS2's
#  mid-game is skippable — Shrine of Winter opens on Soul Memory alone.)
MANDATORY_BOSSES = {
    "dsr": ["Bell Gargoyles", "Chaos Witch Quelaag", "Iron Golem",
            "Dragon Slayer Ornstein", "Executioner Smough", "Great Grey Wolf Sif",
            "The Four Kings", "Seath the Scaleless", "Gravelord Nito", "Bed of Chaos",
            "Gwyn, Lord of Cinder"],
}
MANDATORY_BOSSES["ptde"] = MANDATORY_BOSSES["dsr"]
## DS3's unskippable path to Soul of Cinder — the four Lords of Cinder plus the
## bosses that gate them (Iudex/Vordt/Dancer/Pontiff/Dragonslayer Armour). Reaching
## NG+ proves all of these dead even if their souls were spent. Optional bosses
## (Greatwood, Crystal Sage, Wolnir, Nameless King…) are deliberately excluded.
MANDATORY_BOSSES["ds3"] = [
    "Iudex Gundyr", "Vordt of the Boreal Valley", "Dancer of the Boreal Valley",
    "Abyss Watchers", "Pontiff Sulyvahn", "Aldrich, Devourer of Gods",
    "Yhorm the Giant", "Dragonslayer Armour", "Lothric, Younger Prince",
    "Soul of Cinder"]


## @brief Attach a `bosses` defeat floor to a non-DS2 character from the boss souls
#  / remembrances it still holds, plus endgame progression. A held boss soul is a
#  boss killed — you cannot own the soul otherwise — so each maps to its boss with
#  `soul` evidence, and its mandatory endgame predecessors get `gate` (see
#  BOSS_PREREQ), the same certain-when-true signals DS2 uses. If the character is in
#  NG+ (ng_plus > 0) every MANDATORY_BOSSES entry is proven dead too (`clear`). A boss
#  whose soul was consumed, not gated and not mandatory, is invisible here (the render
#  note says so). DS2 sets its own richer `bosses` via augment and is skipped.
def attach_defeated_bosses(ch, base_dir):
    game = ch.get("game")
    subdir = BOSS_SOUL_DB_DIR.get(game)
    if not subdir or ch.get("bosses"):
        return
    soul_db = load_boss_soul_map(base_dir, subdir)
    bosses = {}
    for name, _q in ch.get("boss_souls") or []:
        boss = soul_db.get(name)
        if boss:
            bosses.setdefault(boss, set()).add("soul")
    if (ch.get("ng_plus") or 0) > 0:
        for boss in MANDATORY_BOSSES.get(game, ()):
            bosses.setdefault(boss, set()).add("clear")
    prereq = BOSS_PREREQ.get(game, {})
    for boss in list(bosses):
        for pre in prereq.get(boss, ()):
            bosses.setdefault(pre, set()).add("gate")
    if bosses:
        # Sort each evidence set for a stable render order (matches ds2_infer_bosses,
        # which already sorts); boss keys keep insertion order.
        ch["bosses"] = {b: sorted(bosses[b]) for b in bosses}


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


## @brief DS3 attunement-slot breakpoints (fextralife Attunement table): the nth
#  entry is the ATN needed for the nth spell slot. Slots = count of these <= ATN.
DS3_SLOT_BREAKS = (10, 14, 18, 24, 30, 40, 50, 60, 80, 99)

##
# @brief DS3 base derived stats that are closed-form functions of attributes only.
# @details Only the three the character screen shows that don't need gear: attunement
# slots (breakpoint count), base Equip Load (@c 40 + Vitality) and base Item Discovery
# (@c 100 + Luck, hard cap 199). HP/FP/stamina are read from the save, not recomputed;
# poise is gear-only in DS3, and defences/resistances/attack power are gear- and
# level-scaled, so none of those are derived here. Formulas from the fextralife
# Equipment Load / Attunement / Item Discovery pages. @param stats The attribute dict.
def ds3_derived_stats(stats):
    atn = stats.get("Attunement", 0) or 0
    vit = stats.get("Vitality", 0) or 0
    lck = stats.get("Luck", 0) or 0
    return {"slots": sum(1 for b in DS3_SLOT_BREAKS if atn >= b),
            "equip_load": 40.0 + vit,
            "item_discovery": min(199, 100 + lck)}


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
            visited.append(bf_db.get(bid, f"(bonfire {bid:#06x})"))
    return visited


## @brief DS2-only augment: attach world-block progression (bonfires, bosses) to a
#  parsed character. The world block for status entry @c i is entry
#  @c i+DS2_WORLD_ENTRY_DELTA; a missing/undecryptable block leaves both fields None
#  (sections omitted). Decrypts the world block once for both reads.
def ds2_augment(ch, data, entries, i, base_dir):
    # Play time lives in the header title record (one per slot), not the character
    # block. Title index for block entry i is i - slots.start, and DS2 starts at 1.
    if entries:
        hdr = decrypt_ds2(data[entries[0].offset:entries[0].offset + entries[0].size])
        if hdr is not None:
            base = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - 1)
            ch["play_time"] = u32(hdr, base + DS2_TITLE_PLAYTIME_OFF)
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
#  Storage order is NOT the level-up display order: eight contiguous uint32
#  (Vigor, Attunement, Endurance, Strength, Dexterity, Intelligence, Faith, Luck),
#  then Vitality alone after a two-field gap. Listed here in display order pointing
#  at the true distances. Calibrated against a real lopsided build (Joy, STR 18 /
#  VIT 14 / LCK 11 read out as VIT 18 / STR 9 / LCK 14 under the old naive mapping,
#  which the order-independent level-sum identity could not catch).
DS3_STAT_D = OrderedDict([
    ("Vigor", 0), ("Attunement", 4), ("Endurance", 8), ("Vitality", 40),
    ("Strength", 12), ("Dexterity", 16), ("Intelligence", 20), ("Faith", 24),
    ("Luck", 28)])
## @brief DS3 max HP, FP, stamina, soul level and souls, same anchor-relative scheme.
#  HP/FP/stamina each store a current+max triple; these offsets point at the MAX
#  copy (a lopsided real save read HP 728 max / 681 current at -40 / -36 — we take
#  the max). FP at -28 verified 72 at ATN 6 and 450 at a high-attunement char.
DS3_HP_D, DS3_FP_D, DS3_STAM_D, DS3_LEVEL_D, DS3_SOULS_D = -40, -28, -12, 44, 48
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
        "fp": u32(buf, v + DS3_FP_D) if v is not None else None,
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


## @brief Play time (seconds, uint32) inside slot @p i's DS3 roster descriptor.
#  The status block does not carry it — it lives in the header menu block, at the
#  same per-slot descriptor as the name, @c +38 past the descriptor start. Pinned
#  by a ~17-minute differential (a real Joy save, 7573 s -> 8603 s, matching an
#  on-screen 2:23:24). Per-character (one descriptor per slot).
DS3_ROSTER_PLAYTIME_OFF = 38
def ds3_playtime(menu_data, i):
    p = ROSTER_PARAMS["ds3"]
    return u32(menu_data, p["desc"] + p["stride"] * i + DS3_ROSTER_PLAYTIME_OFF)


# ─────────────────────────────────────────────────────────────────────────────
#  DS3 event flags — bonfires discovered + bosses defeated (read from the save)
# ─────────────────────────────────────────────────────────────────────────────
# DS3 serialises event flags in a large region inside each character slot, located
# by walking the variable-length blocks that precede it (the GaItem array, then
# inventory / storage / gesture / NG+ headers). Offsets/constants come from the
# alfizari DS3 save editor (main_ds3.py parse_save) and were verified against a real
# save: Joy reads Iudex Gundyr defeated + Cemetery-of-Ash / High-Wall bonfires and
# NOTHING else — zero false positives across 25 bosses and 12 areas on two backups.
# This retires the old "DS3 flags aren't in the save" blocker.
#
# Our decrypted slot drops the 4-byte length prefix alfizari's buffer keeps, so every
# absolute offset is theirs minus 4: the GaItem walk starts at 0x6C (their 0x70); the
# rest is block-relative and self-corrects.
DS3_GAITEM_START = 0x6C
DS3_GAITEM_SLOTS = 6144
DS3_GAITEM_BIG = 60                                 # weapon/armour record; all else 8
DS3_GAITEM_TYPES_BIG = (0x80000000, 0x90000000)     # weapon, armour top nibbles

## @brief DS3 bonfire areas: distance from the event-flag base → the area's "all
#  bonfires lit" bitmask. Each set bit is one bonfire, so we AND the save byte with
#  the mask and count bits — only real bonfire bits count (never overcounts; can
#  undercount if a bit is unmapped, a floor). Distances/masks from the alfizari
#  editor's offset table + bonfire.json; its two non-bonfire "unlock" entries are
#  dropped. Verified: Joy = Cemetery 3 + High Wall 2 = her 5 bonfires.
DS3_BONFIRE_AREAS = OrderedDict([
    ("Cemetery of Ash", (23154, 0xF8)),
    ("High Wall of Lothric", (3953, 0xEC40)),
    ("Undead Settlement", (6514, 0xF8)),
    ("Road of Sacrifices", (11633, 0xFF80)),
    ("Cathedral of the Deep", (15474, 0xF0)),
    ("Catacombs of Carthus", (20594, 0xFA)),
    ("Irithyll of the Boreal Valley", (19313, 0xFF80)),
    ("Irithyll Dungeon", (21874, 0xE0)),
    ("Lothric Castle", (5234, 0xE0)),
    ("Grand Archives", (14194, 0xC0)),
    ("Archdragon Peak", (9074, 0xF0)),
    ("Kiln of the First Flame", (24434, 0xE0)),
    ("Painted World of Ariandel (DLC)", (25714, 0xFF)),
    ("The Dreg Heap (DLC)", (29554, 0xF0)),
    ("The Ringed City (DLC)", (30834, 0xFC)),
    ("Filianore's Rest (DLC)", (32114, 0xC0)),
])

## @brief DS3 boss-defeat flags: distance from the event-flag base → the byte value
#  that is present once the boss is dead. Read the byte and compare exactly: the
#  dead value is the complete-bit state, so a partial/unrelated state has fewer bits
#  and won't match — the read can MISS a kill but won't invent one (core rule). Boss
#  names are the canonical forms used by db_ds3/boss_souls.json so a held-soul kill
#  and a flag kill dedup. Values/distances from the alfizari editor's Bosses.json;
#  positively verified on Iudex Gundyr (the one boss dead in the calibration save),
#  negatively verified on the other 24 (all correctly Alive). Still a floor.
DS3_BOSS_FLAGS = OrderedDict([
    ("Iudex Gundyr", (23254, 0xE0)),
    ("Vordt of the Boreal Valley", (4054, 0xC0)),
    ("Curse-Rotted Greatwood", (6614, 0xC0)),
    ("Crystal Sage", (11736, 0x28)),
    ("Abyss Watchers", (11734, 0xC0)),
    ("Deacons of the Deep", (15574, 0xC0)),
    ("High Lord Wolnir", (20694, 0xC0)),
    ("Pontiff Sulyvahn", (19416, 0x20)),
    ("Aldrich, Devourer of Gods", (19414, 0x80)),
    ("Old Demon King", (20691, 0x02)),
    ("Oceiros, the Consumed King", (4051, 0x42)),
    ("Dancer of the Boreal Valley", (4059, 0x20)),
    ("Dragonslayer Armour", (5334, 0x80)),
    ("Yhorm the Giant", (21974, 0xC0)),
    ("Nameless King", (9176, 0x21)),
    ("Lothric, Younger Prince", (14291, 0x03)),
    ("Champion Gundyr", (23251, 0x03)),
    ("Soul of Cinder", (24534, 0xC0)),
    ("Champion's Gravetender", (25815, 0x0C)),
    ("Sister Friede", (25814, 0xC0)),
    ("Halflight, Spear of the Church", (30934, 0xC0)),
    ("Darkeater Midir", (30936, 0x30)),
    ("Slave Knight Gael", (32214, 0xC0)),
    ("Demon Prince", (29654, 0x80)),
])


##
# @brief Locate the DS3 event-flag region base in a decrypted slot, or None.
# @details Walks the same block chain the alfizari editor uses. Every read is
# bounds-checked (u32 returns None past the buffer), so a short or edited save turns
# the feature off rather than reading garbage. @return The base offset, or None.
def ds3_event_flag_base(buf):
    off = DS3_GAITEM_START
    for _ in range(DS3_GAITEM_SLOTS):
        handle = u32(buf, off)
        if handle is None:
            return None
        big = handle and (handle & 0xF0000000) in DS3_GAITEM_TYPES_BIG
        off += DS3_GAITEM_BIG if big else 8
    above_counter = off + 0x13F + 0x1DD + 0x8808 + 0x11C
    above_size = u32(buf, above_counter)
    if above_size is None:
        return None
    gesture_end = above_counter + 4 + above_size * 8 + 0x18C + 0x4 + 0x8800 + 0xC + 0xA4
    table2_size = u32(buf, gesture_end)
    if table2_size is None:
        return None
    base = gesture_end + 4 + table2_size * 4 + 0x92 + 0xBCC - 0x12
    return base if 0 <= base < len(buf) else None


##
# @brief Read DS3 bonfires + boss-defeat flags off the event-flag region and attach
#        them to @p ch: @c bonfire_areas as [(area, count)], and merge @c flag boss
#        evidence into @c ch["bosses"] (deduping with any soul/gate evidence already
#        there). No-op if the region can't be located. @param buf Decrypted slot.
def ds3_attach_flags(ch, buf):
    base = ds3_event_flag_base(buf)
    if base is None:
        return
    areas = []
    for name, (dist, mask) in DS3_BONFIRE_AREAS.items():
        val = u16(buf, base + dist) if mask > 0xFF else u8(buf, base + dist)
        lit = bin(val & mask).count("1") if val is not None else 0
        if lit:
            areas.append((name, lit))
    if areas:
        ch["bonfire_areas"] = areas
    bosses = {b: set(s) for b, s in (ch.get("bosses") or {}).items()}
    for name, (dist, val) in DS3_BOSS_FLAGS.items():
        got = u16(buf, base + dist) if val > 0xFF else u8(buf, base + dist)
        if got == val:
            bosses.setdefault(name, set()).add("flag")
    if bosses:
        ch["bosses"] = {b: sorted(bosses[b]) for b in bosses}


## @brief DS3 New Game+ cycle (journey count), a uint16 just before the event-flag
#  region, or None. new_game_plus sits at @c base + 0x12 - 0xBCC (base is that region
#  less 0x12 — see @ref ds3_event_flag_base). Guarded to a sane range: a cheated mule
#  read 0xFFFF here, so an out-of-range value is omitted rather than printed wrong.
#  Verified: Joy = 0 (New Game), a real NG+1 char = 1. @return The cycle, or None.
DS3_NG_MAX = 99
def ds3_journey(buf):
    base = ds3_event_flag_base(buf)
    if base is None:
        return None
    ng = u16(buf, base + 0x12 - 0xBCC)
    return ng if ng is not None and 0 <= ng <= DS3_NG_MAX else None


# ═════════════════════════════════════════════════════════════════════════════
#  Markdown rendering
# ═════════════════════════════════════════════════════════════════════════════

## @brief Short attribute headers for the table.
STAT_ABBR = {"Vigor": "VGR", "Endurance": "END", "Vitality": "VIT",
             "Attunement": "ATN", "Strength": "STR", "Dexterity": "DEX",
             "Adaptability": "ADP", "Intelligence": "INT", "Faith": "FTH",
             "Resistance": "RES", "Luck": "LCK", "Mind": "MND", "Arcane": "ARC"}
## @brief What each attribute governs, per game. Static game-design fact — NOT read
#  from the save and never a copied stat value, so it is true for any build and can
#  never be the "wrong field" the core rule forbids. Keyed by game family because the
#  same attribute name means different things across games (DS1 Vitality is HP;
#  DS2/DS3 Vitality is equip load) — exactly the nuance the rule cares about. From the
#  games' own status screens / community wikis.
STAT_GOVERNS = {
    "ds1": OrderedDict([
        ("Vitality", "Max HP"),
        ("Attunement", "Attunement (spell) slots"),
        ("Endurance", "Stamina, equip load, physical defense"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, faster casting"),
        ("Resistance", "Poison/bleed resistance, fire defense"),
        ("Intelligence", "Magic attack, sorcery scaling"),
        ("Faith", "Miracle scaling, lightning & magic defense")]),
    "ds2sotfs": OrderedDict([
        ("Vigor", "Max HP"),
        ("Endurance", "Stamina"),
        ("Vitality", "Equip load, physical defense, petrify resistance"),
        ("Attunement", "Attunement (spell) slots, casting speed"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, casting speed"),
        ("Adaptability", "Agility (i-frames), poison/bleed/petrify resistance"),
        ("Intelligence", "Magic & dark attack, sorcery/hex scaling"),
        ("Faith", "Lightning & dark attack, miracle/hex scaling")]),
    "ds3": OrderedDict([
        ("Vigor", "Max HP"),
        ("Attunement", "FP, attunement (spell) slots"),
        ("Endurance", "Stamina"),
        ("Vitality", "Equip load, physical defense"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, faster casting"),
        ("Intelligence", "Magic attack, sorcery & pyromancy scaling"),
        ("Faith", "Lightning & dark attack, miracle & pyromancy scaling"),
        ("Luck", "Item discovery, bleed/poison buildup, hollow-weapon scaling")]),
    "er": OrderedDict([
        ("Vigor", "Max HP, fire defense & immunity"),
        ("Mind", "FP (skill/spell points), focus resistance"),
        ("Endurance", "Stamina, equip load, robustness"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Dex-weapon scaling, faster casting, less fall damage"),
        ("Intelligence", "Sorcery scaling, magic defense"),
        ("Faith", "Incantation scaling"),
        ("Arcane", "Item discovery, arcane-weapon scaling, death/holy resistance")]),
}
## @brief Map a per-slot game id to its STAT_GOVERNS family (DSR and PtDE share DS1).
def stat_governs_for(game):
    return STAT_GOVERNS.get("ds1" if game in ("dsr", "ptde") else game, {})
## @brief Soft-cap / per-level breakpoint reference per attribute, per game. These are
#  the documented scaling RATES and soft-cap levels (a game-mechanics fact, true for any
#  build), NOT a per-character computed value — computing the absolute would be wrong
#  (DS2 Vigor 36 gives HP 1351 in-save vs 1420 from the flat table, because the real
#  curve carries base/class offsets the summaries drop). So the tool prints the rate
#  table and the character's own stat value, and never a derived absolute it cannot
#  verify. Sourced from the fextralife stat pages (DS1/DS2/DS3/ER), fetched per stat.
STAT_CAPS = {
    "ds1": OrderedDict([
        ("Vitality", "soft caps 30 (~1,100 HP) & 50 (~1,500 HP), rising to ~1,900 at 99"),
        ("Attunement", "1 slot at 10, then 12/14/16/19/23/28/34/41/50 — 10 slots max at 50"),
        ("Endurance", "stamina maxes at 40 (160); equip load keeps rising (~+1/lvl) to 99"),
        ("Strength", "scaling soft cap 40"),
        ("Dexterity", "scaling soft cap 40; cast speed improves to 45"),
        ("Resistance", "minor per-level gains — commonly a dump stat"),
        ("Intelligence", "scaling soft cap 40"),
        ("Faith", "scaling soft cap 40")]),
    "ds2sotfs": OrderedDict([
        ("Vigor", "soft caps 20 & 50; +30 HP/lvl to 20, +20 to 50, +5 after"),
        ("Endurance", "soft cap 20; +2 stamina/lvl to 20, +1 after"),
        ("Vitality", "soft caps 29/49/70; +1.5 load/lvl to 29, +1 to 49, +0.5 to 69, +0.25 after"),
        ("Attunement", "slots at 10/13/16/20/25/30/40/50/60/75/94; cast-speed breakpoints 30/45/60/80"),
        ("Strength", "scaling soft caps 40 & 50"),
        ("Dexterity", "scaling soft caps 40 & 50"),
        ("Adaptability", "raises Agility (with Attunement); gains taper past ~40"),
        ("Intelligence", "scaling soft caps 40 & 50"),
        ("Faith", "scaling soft caps 40 & 50")]),
    "ds3": OrderedDict([
        ("Vigor", "soft caps ~27 & 50; ~1,300 HP at 50, only ~100 more to 99"),
        ("Attunement", "FP soft cap 35 (450 max at 99); slots at 10/14/18/24/30/40/50/60/80/99"),
        ("Endurance", "stamina soft cap 40"),
        ("Vitality", "roughly linear to 99"),
        ("Strength", "scaling soft caps 40 & 60"),
        ("Dexterity", "scaling soft caps 40 & 60"),
        ("Intelligence", "scaling soft caps 40 & 60"),
        ("Faith", "scaling soft caps 40 & 60"),
        ("Luck", "+1 item discovery/pt (base 100); bleed/poison speed soft cap 50")]),
    "er": OrderedDict([
        ("Vigor", "soft caps 40 & 60"),
        ("Mind", "soft caps 50 & 60"),
        ("Endurance", "stamina soft caps 15/30/50; equip load 25/60"),
        ("Strength", "scaling soft caps 20/50/80"),
        ("Dexterity", "scaling soft caps 20/50/80"),
        ("Intelligence", "scaling soft caps 20/50/80"),
        ("Faith", "scaling soft caps 20/50/80"),
        ("Arcane", "scaling soft caps 20/50/80; also raises item discovery")]),
}
## @brief Soft-cap reference for a per-slot game id (DSR and PtDE share DS1).
def stat_caps_for(game):
    return STAT_CAPS.get("ds1" if game in ("dsr", "ptde") else game, {})
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


## @brief Format a play-time count of seconds as H:MM:SS (hours can exceed 24).
def fmt_playtime(seconds):
    h, rem = divmod(seconds, 3600)
    mn, s = divmod(rem, 60)
    return f"{h}:{mn:02d}:{s:02d}"


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
    if ch.get("gender"):
        L.append(f"- **Gender:** {ch['gender']}")
    if ch["ng_plus"] is not None:
        ng = "New Game" if ch["ng_plus"] == 0 else f"New Game +{ch['ng_plus']}"
        L.append(f"- **Playthrough:** {ng}")
    if ch["soul_memory"] is not None:
        L.append(f"- **Soul Memory:** {fmt(ch['soul_memory'])}  _(total souls earned — main progress metric)_")
    if ch.get("play_time"):
        L.append(f"- **Play Time:** {fmt_playtime(ch['play_time'])}")
    if ch["souls"] is not None:
        L.append(f"- **{'Runes' if ch['game'] == 'er' else 'Souls'} held:** {fmt(ch['souls'])}")
    if ch["humanity"] is not None:
        L.append(f"- **Humanity:** {ch['humanity']}")
    if ch["hp"] is not None:
        L.append(f"- **Max HP:** {fmt(ch['hp'])}")
    if ch.get("fp") is not None:
        L.append(f"- **Max FP:** {fmt(ch['fp'])}")
    if ch.get("hollow_lvl"):
        L.append(f"- **Hollowing:** {ch['hollow_lvl']}  _(higher = more deaths without an effigy)_")
    if ch.get("deaths") is not None:
        L.append(f"- **Deaths:** {fmt(ch['deaths'])}")
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
        gov = stat_governs_for(ch["game"])
        cap = stat_caps_for(ch["game"])
        rows = [k for k in keys if k in gov]
        if rows:
            L += ["### Attribute Scaling  _(what each stat scales, its soft caps, and "
                  "your current value — game-mechanics reference, not a value read from "
                  "this save)_", ""]
            for k in rows:
                caps = f" {cap[k][:1].upper() + cap[k][1:]}." if cap.get(k) else ""
                L.append(f"- **{k}** ({ch['stats'][k]}) — {gov[k]}.{caps}")
            L.append("")
        if ch["game"] == "ds2sotfs":
            d = ds2_derived_stats(ch["stats"])
            agl = f"{d['agility']}" + (f"  _({d['iframes']} roll i-frames)_"
                                       if d["iframes"] else "")
            L += ["### Derived Stats  _(computed from attributes — base values before "
                  "rings & equipment; the in-game screen adds ring/gear bonuses on top)_",
                  "",
                  f"- **Stamina:** {d['stamina']}",
                  f"- **Equip Load:** {d['equip_load']:.1f}",
                  f"- **Attunement Slots:** {d['slots']}",
                  f"- **Agility (AGL):** {agl}",
                  f"- **Poise (base):** {d['poise']:.1f}",
                  f"- **ATK: Str:** {d['atk_str']}",
                  f"- **ATK: Dex:** {d['atk_dex']}",
                  f"- **Magic DEF:** {d['magic_def']}",
                  f"- **Fire DEF:** {d['fire_def']}",
                  f"- **Lightning DEF:** {d['lightning_def']}",
                  f"- **Dark DEF:** {d['dark_def']}", ""]
        if ch["game"] == "ds3":
            d = ds3_derived_stats(ch["stats"])
            L += ["### Derived Stats  _(computed from attributes — base values before "
                  "rings, covenant & equipment)_", "",
                  f"- **Attunement Slots:** {d['slots']}",
                  f"- **Equip Load:** {d['equip_load']:.1f}",
                  f"- **Item Discovery:** {d['item_discovery']}", ""]
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
    if ch.get("bonfire_areas"):
        total = sum(c for _, c in ch["bonfire_areas"])
        n = len(ch["bonfire_areas"])
        L += [f"### Bonfires Discovered ({total} across {n} area{'s' if n != 1 else ''})"
              "  _(bonfires lit, inferred from each area's flag bits — a floor)_", ""]
        L += [f"- {name} ({c})" for name, c in ch["bonfire_areas"]] + [""]
    if ch.get("bosses"):
        SRC = {"flag": "confirmed", "soul": "soul held", "gate": "progression", "clear": "cleared (NG+)"}
        L += [f"### Bosses Defeated ({len(ch['bosses'])})  _(a floor — from defeat "
              "flags, held boss souls, progression, and NG+ clears; a boss whose soul "
              "was consumed and isn't gated may still be missing)_", ""]
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
REPO_URL = "https://github.com/darthdemono/sl2-analyzer"

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
                attach_defeated_bosses(ch, base_dir)
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
                if menu is not None:
                    ch["play_time"] = ds3_playtime(menu, i)
                ch["ng_plus"] = ds3_journey(slot)
                attach_defeated_bosses(ch, base_dir)
                ds3_attach_flags(ch, slot)
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
            attach_defeated_bosses(ch, base_dir)
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
