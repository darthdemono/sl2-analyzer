#!/usr/bin/env python3
"""Regenerate every id->name table in db_*/ from soulsmods/Paramdex.

Pinned source: soulsmods/Paramdex @ ff7245e524329bc3eab00036723d2bd53384cedf
(2026-03-06) -- the commit that carries Elden Ring through Shadow of the Erdtree.

This is the single source of truth for item-name data in this project. It is
idempotent and non-destructive: an existing hand-disambiguated name always wins
on an id collision, so running it can add rows and can never silently rewrite a
name a human decided on.

    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/soulsmods/Paramdex.git /tmp/Paramdex
    cd /tmp/Paramdex && git sparse-checkout set DS1 DS1R DS3 ER
    python3 tools/gen_from_paramdex.py --paramdex /tmp/Paramdex

    --dry-run   report the delta, write nothing
    --only ds1  restrict to one game key (ds1, ds3, er, sdt)

DS2 is deliberately absent: its ids are little-endian save bytes, not param ids,
and its tables are already complete from the SOTFS Hex Code Compendium. Paramdex
DS2S cannot be mapped onto them and must not be imported.
"""
import argparse
import json
import os
import re
import sys

# --- id-space geometry -------------------------------------------------------
# A save stores an inventory id as category_prefix | param_id. The prefix is what
# separates two items that share a param id in different tables.
W, P, A, G, GEM = 0x00000000, 0x10000000, 0x20000000, 0x40000000, 0x80000000

# Rows that are engine scaffolding, not items a save can hold. Anything matching
# is dropped before merge. Kept deliberately tight: a bad filter here silently
# deletes real items, which is worse than carrying a few dev rows.
JUNK = re.compile(
    r"^\s*$"
    r"|\[Unused\]|%null%|^Dummy|^dummy"
    r"|^test |^Test |test gem|TestData|ID Monitoring|ID monitoring"
    r"|^Type \d+$|^Unarmed$"
    r"|^\{|^-$|^NoName|^\(dummy",
)
# Sekiro's Paramdex rows carry the Japanese dev name after a double dash. Those
# are dev tables, not localised names, and must never reach a report.
DEVNAME = re.compile(r" -- ")


## Hand corrections applied last, after the merge. Small by design: if this map
#  grows past a dozen entries the upstream table is the thing to fix.
NAME_FIXUPS = {
    "Havel's ring +3": "Havel's Ring+3",   # lowercase/space drift on one variant
}


def read_names(paramdex, game, stem):
    """Paramdex Names/*.txt -> {int id: name}. Files are '<id> <name>' per line."""
    path = os.path.join(paramdex, game, "Names", stem + ".txt")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ident, _, name = line.partition(" ")
            if not ident.lstrip("-").isdigit():
                continue
            name = name.strip()
            if not name or JUNK.search(name) or DEVNAME.search(name):
                continue
            out[int(ident)] = name
    return out


# --- table plan --------------------------------------------------------------
# (game_key, db_dir, shape, [(out_stem, paramdex_dir, param_stem, prefix, filter)])
# A stem listed in STRICT treats Paramdex as the closed set: shipped ids Paramdex
# has never heard of are evicted. Only for tables where cut/foreign rows are known
# to have crept in — db_ds3/rings.json carried DS1 and DS2 rings.
#
# shape "name_str"  -> {"Name": "12345"}   DS1
# shape "name_int"  -> {"Name": 12345}     DS3
# shape "hex_name"  -> {"0000ABCD": "Name"} ER
# shape "dec_name"  -> {"12345": "Name"}   Sekiro


# --- per-table id gates ------------------------------------------------------
# Each gate exists because two param tables share one inventory prefix, or
# because a range is deliberately not reported. Never widen one without saying
# which collision it was guarding.

def ds1_spells(i, _n):
    """DS1 stores sorceries/miracles/pyromancies as ordinary goods, 3000-8999.
    9000-9014 is the gesture block, which is a good and stays one — filing a
    gesture under a "Spells" heading would be a worse lie than no heading."""
    return 3000 <= i < 9000


def ds1_goods(i, _n):
    return not ds1_spells(i, _n)


## @brief DS3 flask ids, in level pairs (full, drained). ds3_resolve_estus computes
#  the level from the id, so a table row would only ever disagree with it about the
#  spelling — and would shadow it, since a direct hit wins.
DS3_ESTUS = ((150, 171), (190, 211))


def ds3_goods(i, _n):
    """Goods and spells both sit behind 0x40000000 in a DS3 save, so anything at
    or above the Magic id floor belongs to db_ds3/spells.json, not here. 9000-
    9099 is the gesture block: gestures are not reported (they scatter off-grid
    flag hits and cost real items to acquire)."""
    if any(lo <= i <= hi for lo, hi in DS3_ESTUS):
        return False
    return i < 1200000 and not (9000 <= i < 9100)


def ds3_weapons(i, _n):
    """DS3's inventory is found by scanning every byte of the slot for a known id,
    so a junk row is not free: a dev id matching off the 16-byte record grid splits
    a run and takes real items with it (a mule lost four items to exactly this).
    Ammunition sits at 400000-409999 and real armaments at 1000000-29999999;
    everything Paramdex lists outside those is (Debug)/Test-/Ghost scaffolding, or
    the sub-10000 thrown-item rows whose small ids match constantly."""
    return 400000 <= i <= 409999 or 1000000 <= i <= 29999999


def ds3_armors(i, _n):
    """Real DS3 protector ids start at 19000000. Everything below 10^7 in
    Paramdex is the cut DS1-legacy block (Armor of Favor, Stone Armor) that no
    DS3 save can hold."""
    return i >= 10000000


def ds3_rings(i, _n):
    """EquipParamAccessory 10000-19999 is the covenant-badge block, which is
    rendered from db_ds3/covenants.json. Real rings start at 20000."""
    return i >= 20000


STRICT = {"db_ds3/rings"}

## Tables whose gate also applies to what is ALREADY shipped. Everywhere else a gate
#  filters Paramdex only, because a shipped id is one a real save was seen to hold —
#  db_ds3/weapons carries Torch (90000) and Fists (110000), which the weapon gate
#  rejects and which the equipped-weapon read depends on. Pruning is for the DS1
#  goods/spells split (rows must MOVE, not duplicate) and the ring eviction.
PRUNE_EXISTING = {"db_ds1/Consumables", "db_ds1/Spells", "db_ds3/rings"}

PLAN = [
    ("ds1", "db_ds1", "name_str", [
        # DS1R and DS1 PtDE share an id space; DS1R is the superset. The audit
        # believed spells were unshipped — they are present, but folded into
        # Consumables under a "Sorcery:/Pyromancy:/Miracle:" prefix. Splitting
        # them out is what gives DS1 a spells heading like DS2/DS3 have.
        # Order matters: Consumables runs first and evicts the spell ids, which
        # Spells then adopts *with the names already on them* ("Sorcery: Soul
        # Arrow"), rather than taking Paramdex's bare "Soul Arrow".
        ("Consumables",   "DS1R", "EquipParamGoods",     0, ds1_goods),
        ("Spells",        "DS1R", "EquipParamGoods",     0, ds1_spells),
        ("MeleeWeapons",  "DS1R", "EquipParamWeapon",    0, None),
        ("Armor",         "DS1R", "EquipParamProtector", 0, None),
        ("Rings",         "DS1R", "EquipParamAccessory", 0, None),
    ]),
    ("ds3", "db_ds3", "name_int", [
        ("goods",   "DS3", "EquipParamGoods",     G, ds3_goods),
        ("rings",   "DS3", "EquipParamAccessory", A, ds3_rings),
        ("weapons", "DS3", "EquipParamWeapon",    W, ds3_weapons),
        ("armors",  "DS3", "EquipParamProtector", P, ds3_armors),
        ("spells",  "DS3", "Magic",               G, None),
    ]),
    ("er", "db_er", "hex_name", [
        ("weapons",   "ER", "EquipParamWeapon",    W,   None),
        ("armors",    "ER", "EquipParamProtector", P,   None),
        ("goods",     "ER", "EquipParamGoods",     G,   None),
        ("talismans", "ER", "EquipParamAccessory", A,   None),
        ("ashes",     "ER", "EquipParamGem",       GEM, None),
    ]),
    # Sekiro is deliberately not in this plan, and is handled by
    # tools/gen_sdt_from_regulation.py instead. The reason is the same one that
    # generator exists for: Paramdex SDT/Names carries machine-translated dev rows
    # only ("Molotov cocktail -- 火炎瓶"), and Sekiro's shipped English names live in
    # the game's own msg/engus FMGs, not in Paramdex at all. db_sdt/ was built from a
    # cleaned pass and is complete for what a report prints; Sekiro's remaining gaps
    # are save-layout, not names. Do not add SDT here — two generators writing the
    # same tables from different sources is how the two disagree.
]


def load_existing(path, shape):
    """Read a shipped table into {int id: name}, whatever shape it is on disk."""
    if not os.path.exists(path):
        return {}, None
    raw = json.load(open(path, encoding="utf-8"))
    if shape in ("name_str", "name_int"):
        # A name-keyed value may be a LIST: one name, several ids (see dump).
        out = {}
        for name, value in raw.items():
            for i in (value if isinstance(value, list) else [value]):
                out[int(i)] = name
        return out, raw
    if shape == "hex_name":
        return {int(k, 16): v for k, v in raw.items()}, raw
    return {int(k): v for k, v in raw.items()}, raw


def dump(table, shape):
    """{int id: name} -> the on-disk shape, id-sorted for a stable diff.

    The name-keyed shapes must hold a name that owns SEVERAL ids — the games ship
    one, repeatedly (a "Cinders of a Lord" per lord, a DS1 base row beside its
    alternate-path twin). Writing one key per name drops all but the last, which is
    how three real DS3 goods and two DS1 weapons went missing on the first import.
    So a name with several ids gets a list, and the loaders read either form.
    """
    items = sorted(table.items())
    if shape in ("name_str", "name_int"):
        cast = str if shape == "name_str" else int
        byname = {}
        for i, n in items:
            byname.setdefault(n, []).append(cast(i))
        return {n: (v[0] if len(v) == 1 else v) for n, v in byname.items()}
    if shape == "hex_name":
        return {"%08X" % i: n for i, n in items}
    return {str(i): n for i, n in items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paramdex", required=True)
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Names a split moves out of one table and into another, keyed by id.
    carried = {}
    total_added = 0
    for key, dbdir, shape, tables in PLAN:
        if args.only and args.only != key:
            continue
        for stem, pgame, pstem, prefix, filt in tables:
            src = read_names(args.paramdex, pgame, pstem)
            if not src:
                print("  !! no Paramdex rows for %s/%s" % (pgame, pstem), file=sys.stderr)
                continue
            if filt:
                src = {i: n for i, n in src.items() if filt(i, n)}
            src = {prefix | i: n for i, n in src.items()}

            key_name = dbdir + "/" + stem
            path = os.path.join(args.repo, dbdir, stem + ".json")
            have, _raw = load_existing(path, shape)
            if filt and key_name in PRUNE_EXISTING:
                # Prune existing rows the gate rejects. This is what makes the
                # DS1 Consumables/Spells split move rows rather than duplicate
                # them, and what evicts the cut non-DS3 rings.
                keep, drop = {}, {}
                for i, n in have.items():
                    (keep if filt(i & ~prefix, n) else drop)[i] = n
                have = keep
                carried.update(drop)

            if key_name in STRICT:
                evicted = {i: n for i, n in have.items() if i not in src}
                if evicted:
                    print("   evicted (not in Paramdex): %s"
                          % ", ".join(sorted(evicted.values())))
                have = {i: n for i, n in have.items() if i in src}

            merged = dict(src)
            merged.update({i: n for i, n in carried.items() if i in src})
            merged.update(have)            # hand-disambiguated name wins
            merged = {i: NAME_FIXUPS.get(n, n) for i, n in merged.items()}
            added = len(merged) - len(have)
            total_added += added
            print("%-24s %5d -> %5d  (+%d)" % (dbdir + "/" + stem, len(have), len(merged), added))
            if not args.dry_run:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(dump(merged, shape), fh, ensure_ascii=False, indent=1)
                    fh.write("\n")
    print("\ntotal rows added: %d%s" % (total_added, "  (dry run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
