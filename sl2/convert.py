"""The driver: the GAMES control table, the file-level footer fields, and the
one pass that turns a .sl2 into Markdown.
"""
import os
import sys
from datetime import datetime
from .reader import u32
from .keys import DS2_VANILLA_KEY, DS3_KEY, DSR_KEY
from .bnd4 import parse_bnd4
from .crypto import decrypt_ds2, decrypt_iv_prefixed, decrypt_none
from .detect import detect_game
from .itemdb import DS1_DB_FILES, DS2_DB_FILES, load_item_db, load_scan_db
from .progress import attach_defeated_bosses
from .roster import parse_roster
from .ds1 import ds1_augment, dsr_parse, ptde_parse
from .ds2 import ds2_active_slots, ds2_augment, ds2_parse
from .ds3 import DS3_DB_FILES, ds3_attach_flags, ds3_attach_ring_effects, ds3_event_flag_base, ds3_item_cat, ds3_journey, ds3_parse, ds3_playtime
from .er import er_parse, er_roster, load_er_db
from .sdt import SDT_SLOT_COUNT, load_sdt_db, sdt_attach_flags, sdt_parse
from .totals import attach_progress_totals
from .render import md_for_character


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
    "ds2vanilla": {"title": "Dark Souls II", "tier": "full",
                   "db": ("db_ds2", True, DS2_DB_FILES),
                   "decrypt": lambda b: decrypt_ds2(b, DS2_VANILLA_KEY),
                   "parse": lambda b, d: ds2_parse(b, d, "ds2vanilla"),
                   "slots": range(1, 11),
                   # The header and world blocks are encrypted with the same key as
                   # the slot, so both hooks must be given the vanilla one — reading
                   # them with the Scholar key yields noise, not an empty result.
                   "active": lambda d, e, s: ds2_active_slots(
                       d, e, s, lambda b: decrypt_ds2(b, DS2_VANILLA_KEY)),
                   "augment": lambda ch, d, e, i, b: ds2_augment(
                       ch, d, e, i, b, lambda x: decrypt_ds2(x, DS2_VANILLA_KEY)),
                   "how": "the original (pre-Scholar) release locks its save with a "
                          "different AES-128 key from Scholar's, but stores everything "
                          "in the same places once unlocked — so the same reader "
                          "handles both. Name, level, the nine attributes, souls and "
                          "the inventory sit at fixed known positions, and every item "
                          "ID is looked up in the community SOTFS name table. Note "
                          "the Scholar-only items and bonfires simply never appear in "
                          "an original-edition save"},
    "dsr": {"title": "Dark Souls Remastered", "tier": "full",
            "db": ("db_ds1", False, DS1_DB_FILES),
            "decrypt": lambda b: decrypt_iv_prefixed(b, DSR_KEY),
            "parse": dsr_parse, "slots": range(0, 10),
            "augment": lambda ch, d, e, i, b: ds1_augment(
                ch, d, e, i, b, lambda x: decrypt_iv_prefixed(x, DSR_KEY)),
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
             "augment": lambda ch, d, e, i, b: ds1_augment(ch, d, e, i, b, decrypt_none),
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
    "sdt": {"title": "Sekiro: Shadows Die Twice", "tier": "full", "db": "db_sdt",
            "decrypt": decrypt_none, "slots": range(0, SDT_SLOT_COUNT),
            # `coverage` says what the tier does NOT cover, so a reader who sees
            # "full" does not fairly infer that everything the other games report is
            # here. Moving the tier would redefine what the word means for every game.
            "coverage": "minibosses and world item pickups are not read — Sekiro "
                        "publishes no id table for either, so there is nothing to look "
                        "up even though the flag region itself is read",
            "how": "the save is not encrypted and, unlike every other game here, its "
                   "fields do not move between patches — so play time, journey (New "
                   "Game+) count, Attack Power and Sen are read straight from fixed "
                   "positions. The item lists are read the same way: each entry stores "
                   "a type code beside its item ID, so a piece of armour can never be "
                   "named as a weapon, and a prosthetic tool's upgrade tier is its own "
                   "ID (there is no '+N' to work out). Sekiro has no character name and "
                   "no attributes to level, so neither appears; Attack Power doubles as "
                   "a count of the Memories already spent, which is how bosses whose "
                   "token is long gone are still counted"},
}


## @brief One-line header note for a generated file: the repo, and how this game
#         is read. Replaces the old boilerplate; states the source, not caveats.
def disclaimer_for(cfg):
    return (f"> Automated dump of the save. Code Repo: {REPO_URL} . "
            f"How it works for {cfg['title']}: {cfg['how']}.")


##
# @brief Games that stamp a save-format version as a @c uint32 at slot @c +0.
# @details ClayAmore's ER-Save-Lib names this field ("File version", the word right
# after the 16-byte checksum) and branches on it, so it is documented rather than
# inferred. DSR reads 71, DS3 98, ER 220 or 251. It is NOT the game patch — two ER saves
# here read 220 and 251 with the same regulation version — so it is printed as a bare
# number beside the patch, not translated into one. DS2 is deliberately absent: it reads
# a constant @c 0x6F there on vanilla, Scholar and all 41 mules alike, so that word is
# structure, not a version. PtDE's first word is its slot size. Neither is guessed at.
SAVE_VERSION_GAMES = {"dsr", "ds3", "er"}


## @brief Above this a slot-0 word is not a version counter but data.
SAVE_VERSION_MAX = 4095


##
# @brief The save-format version this file was written with, or None.
# @details Read from the first slot that carries one — an unused slot is all zeros, so
# the walk continues past it rather than reporting 0.
# @param data The full file bytes. @param entries BND4 entries.
# @param cfg  The GAMES entry. @param game The game key.
def save_format_version(data, entries, cfg, game):
    if game not in SAVE_VERSION_GAMES:
        return None
    for e in entries:
        if e.index not in cfg["slots"]:
            continue
        buf = cfg["decrypt"](data[e.offset:e.offset + e.size])
        v = u32(buf, 0) if buf else None
        if v is not None and 0 < v <= SAVE_VERSION_MAX:
            return v
    return None


##
# @brief Where each game stores the Steam account that owns the save: (menu entry,
#        offset of the @c uint64 inside it).
# @details Found by scanning every entry of every fixture for a well-formed SteamID64
# and checking the hit against the account the save's own folder is named for. DS3 and
# ER keep it at the very front of the menu block, Sekiro a little further in.
# @note DS1 and DS2 are ABSENT because they genuinely do not store it — an exact byte
# search for both the SteamID64 and the bare account id, over PtDE, DSR, vanilla DS2 and
# Scholar saves whose owning account is known from the folder name, finds nothing. Those
# two games pick the save folder from whichever account is logged in and never write it
# down, which is also why their saves move between accounts and these ones do not.
STEAM_ID_GAMES = {"ds3": (10, 0x04), "er": (10, 0x04), "sdt": (10, 0x24)}


##
# @brief High dword of every individual-account SteamID64 (universe 1, type 1,
#        instance 1). The low dword is the account id proper.
# @details Reading the field as two halves rather than one @c uint64 is deliberate and
# has to be matched in the JS port: a SteamID64 is larger than JavaScript's exact
# integer range, so forming the 64-bit value in a double loses the last digits. Both
# ports read two @c uint32 and assemble the printable forms from those. Requiring this
# exact constant in the high half is also the validity gate: it is what separates the
# real field from an arbitrary word, so an unrecognised layout omits the field instead
# of printing a nonsense account.
STEAM_ID64_HIGH = 0x01100001


## @brief Games whose save folder is named with the SteamID64 in HEX rather than
#  decimal. Verified against the folders on disk: DS3 sits in `011000013fc93365`,
#  Sekiro in the decimal `76561199030416229`. DS2 names its folder the same hex way but
#  is NOT listed, because it stores no account to derive one from. ER is not listed
#  either: no ER folder was on hand, so its convention is unchecked and unclaimed.
STEAM_FOLDER_HEX = {"ds3"}


## @brief Games whose save folder is named with the decimal SteamID64.
STEAM_FOLDER_DEC = {"sdt"}


##
# @brief The Steam account that owns this save, or None.
# @details Returns @c (account_id, steam_id64_text) — the account id as a plain int and
# the full SteamID64 rendered as text, because the number is too large to survive a
# JavaScript double and the two front ends have to agree byte for byte.
# @param data The full file bytes. @param entries BND4 entries. @param game The game key.
def steam_owner(data, entries, game):
    where = STEAM_ID_GAMES.get(game)
    if where is None:
        return None
    entry, off = where
    if len(entries) <= entry:
        return None
    e = entries[entry]
    buf = GAMES[game]["decrypt"](data[e.offset:e.offset + e.size])
    if buf is None:
        return None
    low, high = u32(buf, off), u32(buf, off + 4)
    if low is None or high != STEAM_ID64_HIGH or low == 0:
        return None
    return low, str((high << 32) | low)


##
# @brief The folder name the game will look for this save under, or None where the
#        convention has not been verified for that game.
# @details The account is baked into the save, and the game only reads a save back out
# of the folder named for that account — so a save moved to another account's folder,
# or a save whose account id changed underneath it, will not load. That is the whole
# reason this is worth printing.
# @param game The game key. @param owner The @ref steam_owner pair.
def steam_folder(game, owner):
    if owner is None:
        return None
    account, _ = owner
    if game in STEAM_FOLDER_HEX:
        return f"{STEAM_ID64_HIGH:08x}{account:08x}"
    if game in STEAM_FOLDER_DEC:
        return str((STEAM_ID64_HIGH << 32) | account)
    return None


## @brief Elden Ring ships its regulation (the game's own param data) inside the save,
#  in BND4 entry 11 behind a " GER" magic — and that block is versioned.
ER_REG_ENTRY = 11


ER_REG_MAGIC = b" GER"


ER_REG_VER_OFF = 8      # magic[4] + unk u32, per ER-Save-Lib's UserData11


##
# @brief Elden Ring's game patch, decoded from its regulation version, or None.
# @details The regulation version is a @c uint32 laid out as @c M-mm-p-bbbb: major,
# minor, patch, build. Both ER saves here read @c 11601000 → 1.16.0. The layout is not
# a guess — ER-Save-Lib carries a regulation-version→size table of 24 real ids, and
# every one of them decodes this way to a version Bandai actually shipped (10210038 →
# 1.02.1, 10330078 → 1.03.3, 10911000 → 1.09.1, 11611000 → 1.16.1). The build digits are
# dropped: they identify the regulation revision, not the patch players are told about.
# @note ER only. DS3's entry 11 carries the same " GER" magic but no version word (its
# @c +8 is a size), and DS1/DS2 have no regulation block at all — so nothing to read.
# @param data The full file bytes. @param entries BND4 entries.
def er_game_patch(data, entries):
    if len(entries) <= ER_REG_ENTRY:
        return None
    e = entries[ER_REG_ENTRY]
    buf = decrypt_none(data[e.offset:e.offset + e.size])
    if buf[:4] != ER_REG_MAGIC:
        return None
    v = u32(buf, ER_REG_VER_OFF)
    if v is None or not 10000000 <= v <= 19999999:
        return None
    return f"{v // 10 ** 7}.{v // 10 ** 5 % 100:02d}.{v // 10 ** 4 % 10}"


## @brief Display labels for metadata keys whose acronym `capitalize()` would mangle
#  ("dlc" -> "Dlc", "os" -> "Os"). Any key not listed falls back to capitalising, so a
#  caller inventing their own key still gets a sane label.
META_LABEL = {"dlc": "DLC", "os": "OS", "cpu": "CPU", "gpu": "GPU", "ram": "RAM",
              "mangohud": "MangoHud", "gamemode": "GameMode", "dxvk": "DXVK",
              "fps": "FPS", "hdr": "HDR", "url": "URL", "id": "ID"}


##
# @brief The closing "about this file" block: game, tier, slot count and the
#        how-it-works note.
# @details These are facts about the TOOL, not about the character, and they are
# identical in every export — so they sit at the end, out of the way of the save's own
# numbers, and folded into a @c <details> block so two exports diff cleanly. The save
# version is the one line here that IS about the file, and it sits here because it is a
# property of the file rather than of any one character — as is the game patch.
# @param cfg The GAMES entry. @param n Characters rendered.
# @param version The save-format version, or None where the game has no known field.
# @param patch The game patch (ER only, from its regulation version), or None.
# @param owner The Steam account pair from @ref steam_owner, or None.
# @param folder The folder name from @ref steam_folder, or None.
# @param meta Caller-supplied environment (store, launcher, OS, …), or None. It is
#        printed under its own heading and labelled as SUPPLIED, because none of it
#        is read from the save — the save cannot know which launcher started it.
def footer_for(cfg, n, version=None, patch=None, owner=None, folder=None, meta=None):
    ver = [f"- **Save format version:** {version}"] if version is not None else []
    if patch is not None:
        ver.append(f"- **Game patch:** {patch}  _(from the save's own regulation)_")
    if owner is not None:
        account, sid = owner
        ver.append(f"- **Steam account:** {account}  _(SteamID64 {sid} — the account "
                   f"this save was written by)_")
    if folder is not None:
        ver.append(f"- **Save folder:** `{folder}`  _(the game loads this save only "
                   f"from a folder of this name)_")
    env = []
    if meta:
        env = ["", "**Setup**  _(supplied by the caller — not read from the save, "
               "which cannot know any of it)_", ""]
        for key, value in meta.items():
            label = META_LABEL.get(key) or key.replace("_", " ").capitalize()
            shown = " · ".join(str(v) for v in value) if isinstance(value, list) else value
            env.append(f"- **{label}:** {shown}")
    return ["<details>", "<summary>About this file — how it was produced, "
            "and how far to trust it</summary>", "",
            f"- **Game:** {cfg['title']}",
            f"- **Support tier:** {cfg['tier']}"
            + (f"  _({cfg['coverage']})_" if cfg.get("coverage") else ""),
            f"- **Character slots read:** {n}", *ver, *env, "",
            disclaimer_for(cfg), "", "</details>", ""]


##
# @brief One parsed save: the game it is, its file-level fields, and its characters.
# @details A plain record rather than a dict so the two writers cannot disagree about
#  a key name. @c characters is a list of @c (entry index, character dict) pairs, the
#  entry index being what the slot number is derived from.
class SaveData:
    __slots__ = ("game", "cfg", "version", "patch", "owner", "folder", "characters")

    def __init__(self, game, cfg, version, patch, characters, owner=None, folder=None):
        self.game = game            # game id, e.g. "ds3"
        self.cfg = cfg              # its GAMES entry
        self.version = version      # save-format version, or None
        self.patch = patch          # ER regulation version, or None
        self.owner = owner          # (account id, SteamID64 text), or None
        self.folder = folder        # the folder name that account implies, or None
        self.characters = characters


##
# @brief Read one save file into plain data: which game it is, and every populated
#        character slot already augmented with its progress.
# @details This is the whole reading pass, with no rendering in it — the Markdown
#        writer and the JSON writer both start here, so neither can drift from the
#        other. The three branches are the three shapes the games come in: Elden Ring
#        (roster-gated, GaItem items), DS3 (id-scan items, content-scan stats, event
#        flags), and everything else (decrypt the slot, hand it to the game's parse
#        hook, then its optional augment hook).
# @param data     The full file bytes.
# @param base_dir Folder holding the @c db_* item-table directories.
# @return A @ref SaveData.
def parse_save(data, base_dir):
    entries = parse_bnd4(data)
    game = detect_game(data, entries)
    cfg = GAMES[game]
    version = save_format_version(data, entries, cfg, game)
    patch = er_game_patch(data, entries) if game == "er" else None
    owner = steam_owner(data, entries, game)
    folder = steam_folder(game, owner)
    characters = []

    # Elden Ring: identity + stats (content-scan) + owned items (GaItem walk).
    if game == "er":
        iddb = load_er_db(os.path.join(base_dir, cfg["db"]))
        if not iddb:
            sys.exit(f"No item database found in {os.path.join(base_dir, cfg['db'])}")
        menu_entry = entries[cfg["menu"]]
        roster = er_roster(data[menu_entry.offset:menu_entry.offset + menu_entry.size])
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
                attach_progress_totals(ch, base_dir)
                characters.append((i, ch))
        return SaveData(game, cfg, version, patch, characters, owner, folder)

    # Sekiro: fixed offsets throughout, and the slot's own content decides whether it
    # holds a character — the game publishes no occupancy array.
    if game == "sdt":
        db_dir = os.path.join(base_dir, cfg["db"])
        iddb = load_sdt_db(db_dir)
        if not any(iddb["names"].values()):
            sys.exit(f"No item database found in {db_dir}")
        for i in cfg["slots"]:
            if i >= len(entries):
                continue
            slot = cfg["decrypt"](data[entries[i].offset:entries[i].offset + entries[i].size])
            if slot is None:
                continue
            ch = sdt_parse(slot, iddb)
            if ch is not None:
                attach_defeated_bosses(ch, base_dir)
                sdt_attach_flags(ch, slot, base_dir)
                attach_progress_totals(ch, base_dir)
                characters.append((i, ch))
        return SaveData(game, cfg, version, patch, characters, owner, folder)

    # DS3: names from the header, inventory by id-scan, stats by content-scan.
    if game == "ds3":
        db_dir = os.path.join(base_dir, cfg["db"][0])
        iddb = load_scan_db(db_dir, cfg["db"][1], ds3_item_cat)
        if not iddb:
            sys.exit(f"No item database found in {db_dir}")
        menu_entry = entries[cfg["menu"]]
        menu = cfg["decrypt"](data[menu_entry.offset:menu_entry.offset + menu_entry.size])
        names = dict(parse_roster(menu or b"", game)) if menu is not None else {}
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
                flag_base = ds3_event_flag_base(slot)  # walk the block chain once
                ch["ng_plus"] = ds3_journey(slot, flag_base)
                attach_defeated_bosses(ch, base_dir)
                ds3_attach_ring_effects(ch, base_dir)
                ds3_attach_flags(ch, slot, flag_base, base_dir)
                attach_progress_totals(ch, base_dir)
                characters.append((i, ch))
        return SaveData(game, cfg, version, patch, characters, owner, folder)

    # Full / inventory tier: decrypt each slot and parse it.
    db_dir = os.path.join(base_dir, cfg["db"][0])
    item_db = load_item_db(db_dir, cfg["db"][1], cfg["db"][2])
    if not item_db:
        sys.exit(f"No item database found in {db_dir}")

    # Some games keep a deleted character's block intact and only drop it from the
    # menu; an "active" hook returns the still-listed entries so ghosts are skipped.
    active = cfg["active"](data, entries, cfg["slots"]) if "active" in cfg else None

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
            attach_progress_totals(ch, base_dir)
            characters.append((i, ch))
    return SaveData(game, cfg, version, patch, characters, owner, folder)


## @brief Elden Ring's item-coverage caveat. ER is the one game whose item list is
#  deliberately partial, so the document says so where the list is.
ER_NOTE = ("_Elden Ring identity, attributes, and runes are read directly; the "
           "**item list is partial**. Owned items come from the GaItem array, "
           "which holds weapons, armour and Ashes of War — each named against "
           "its own type table (so no cross-type mis-naming) and reinforced/"
           "affinity weapons resolve to the base weapon (the upgrade level "
           "itself is not read). Talismans, spells and consumable goods live in "
           "a separate held-inventory that shifts between patches and is not "
           "parsed, so they are not listed. What is listed is really owned._")


## @brief Sekiro's own caveat. The item lists are complete, the two stat maxima are
#  pinned, and the event-flag region is located — so both the idols and the boss kills
#  come out of their own flags. What is left needs id tables the game does not publish.
SDT_NOTE = ("_Sekiro has no character name and no attributes: both are absent from the "
            "game, not missing here. The item lists (carried, key items and the storage "
            "box) are read whole and named by type, so nothing in them is guessed. Max HP "
            "and max Posture come from the second of each field's two copies, because the "
            "offsets the published editor labels as maxima are the CURRENT values — a "
            "save pair either side of taking damage settled that. **Spirit Emblems** is "
            "not read as a number of its own: the documented field holds 15 across saves "
            "taken before and after the character gained a prosthetic, so it is the carry "
            "cap rather than the count — and emblems you actually hold are an ordinary "
            "inventory item, listed with everything else. The **Sculptor's Idols** and the "
            "boss-defeat **flags** are both read: the event-flag region is at a fixed "
            "place in the save, worked out from save pairs that lit one idol and killed "
            "one boss, so a kill tagged _(confirmed)_ is proven rather than counted off a "
            "Memory. Both RESET on a new journey — Attack Power carries and the flags do "
            "not, so an NG+ save reports fewer than the character has earned._")


##
# @brief Build the Markdown document for one save file.
# @param data     The full file bytes.
# @param filename The source filename, for the header line.
# @param base_dir Folder holding the @c db_* item-table directories.
# @return The complete Markdown string.
def convert(data, filename, base_dir, meta=None):
    return render_markdown(parse_save(data, base_dir), filename, meta)


##
# @brief Render an already-parsed save as the Markdown document.
# @param save     A @ref SaveData from @ref parse_save.
# @param filename The source filename, for the header line.
# @param meta Caller-supplied environment for the footer, or None.
# @return The complete Markdown string.
def render_markdown(save, filename, meta=None):
    cfg = save.cfg
    # Only the save's own identity up top; what the TOOL is and how far to trust it
    # is the same in every export, so it goes in the closing block (footer_for).
    head = [f"# {cfg['title']} — Playthrough Save Summary", "",
            f"_Source: `{filename}` · generated {datetime.now():%Y-%m-%d %H:%M} · sl2_to_md_",
            "", "---", ""]
    body = ["_No populated character slots found._"] if not save.characters else []
    for i, ch in save.characters:
        body.append(md_for_character(ch, i - cfg["slots"].start + 1))
        body += ["---", ""]
    if save.game == "er":
        body += [ER_NOTE, ""]
    if save.game == "sdt":
        body += [SDT_NOTE, ""]
    return "\n".join(head + body
                     + footer_for(cfg, len(save.characters), save.version, save.patch,
                                  save.owner, save.folder, meta))


