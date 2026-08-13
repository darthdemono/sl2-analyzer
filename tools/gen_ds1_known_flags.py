#!/usr/bin/env python3
"""Build `db_ds1/known_flags.json` — Dark Souls 1 world state, by event flag.

WHAT THIS UNLOCKS
    The repo has read DS1's event-flag region since the boss-flag work
    (`DS1_FLAG_BASE`, found by search because DS1's published group bases are MEMORY
    offsets). It has only ever read twelve boss flags out of it. There are fifty-two
    more named flags sitting in `test/flag_data/files2/ds1_known_event_flags.csv` — the
    Bells of Awakening, the Lordvessel, the shortcut doors and levers, the non-boss fog
    gates, NPC states, covenants joined — and every one is addressable with machinery
    that already exists. This turns them into a readable section instead of a file
    nobody opened.

THE ADDRESSING, AND WHY IT IS TRUSTWORTHY HERE
    An 8-digit DS1 flag is `G AAA S NNN`: a group digit, a three-digit area, a section
    digit and the flag number. From `ds1_flag_addressing.csv`:

        offset = group_base[G] + area_index[AAA]*0x500 + S*128 + (NNN - NNN%32)/8
        mask   = 0x80000000 >> (NNN % 32)

    That is not taken on faith. Run over the twelve boss ids this repo already ships as
    hand-checked `(offset, mask)` pairs in `db_ds1/boss_flags.json`, it reproduces all
    twelve exactly. A formula that regenerates an independently-derived table is a
    formula worth pointing at new ids.

WHAT IS DELIBERATELY DROPPED
    A flag whose group or area is not in the addressing table is skipped rather than
    guessed — the same rule the DS3 pickup groups follow. Anything not 8 digits is an
    enum index rather than an event flag (the boss CSV is full of them) and is skipped
    too. The counts printed at the end say how many of each, so a shrinking table is
    visible rather than silent.

Run from the repo root:

    python3 tools/gen_ds1_known_flags.py
"""

import argparse
import collections
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDRESSING = os.path.join(
    BASE, "test", "flag_data", "files2", "ds1_flag_addressing.csv"
)
KNOWN = os.path.join(BASE, "test", "flag_data", "files2", "ds1_known_event_flags.csv")
OUT = os.path.join(BASE, "db_ds1", "known_flags.json")

## @brief The order categories are printed in — roughly the order they matter to a
#  reader, rather than alphabetical. Anything not listed sorts to the end by name.
CATEGORY_ORDER = [
    "Bells of Awakening",
    "Lordvessel",
    "Non-Boss Fog Gates",
    "Doors",
    "Levers",
    "Elevators",
    "Join Covenants",
    "NPC",
    "Other",
]


##
# @brief Categories dropped on evidence, not taste.
# @details "Boss Fight" is eight rows of "Boss Arena Entered" and "Cutscene Skipped",
# and every one reads CLEAR on the NG+2 all-bonfires mule that has 23 bosses dead. A
# flag that must be true there and is not is transient — set while you are in the arena,
# not after you win — so printing "Boss Fight 0 of 8" on a finished run would tell a
# reader those bosses were never fought. The kills are already reported properly from
# `db_ds1/boss_flags.json` and the soul floor.
EXCLUDE_CATEGORIES = {"Boss Fight"}


## @brief Load the group-base and area-index tables out of the addressing CSV.
def addressing():
    groups, areas = {}, {}
    with open(ADDRESSING, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            table = (row.get("table") or "").strip()
            key, value = (
                (row.get("key") or "").strip(),
                (row.get("value") or "").strip(),
            )
            if table.startswith("group"):
                groups[int(key)] = int(value, 16)
            elif table.startswith("area"):
                areas[key] = int(value)
    return groups, areas


##
# @brief Byte offset of a flag's uint32 and the bit mask inside it, or None.
# @details MSB-first within the word, which is the same rule DS3 and Sekiro use — DS1
# just expresses it as a whole-word mask rather than a byte and a bit.
# @param fid The 8-digit event flag id.
def address(fid, groups, areas):
    # Short ids are common-group flags written without their leading zeros — `851` is
    # `00000851`, area 000, section 0. They are NOT enum indices; padding is the
    # documented reading of the same G-AAA-S-NNN shape.
    text = str(fid).zfill(8)
    if len(text) != 8:
        return None
    group, area, section, number = int(text[0]), text[1:4], int(text[4]), int(text[5:8])
    if group not in groups or area not in areas:
        return None
    off = (
        groups[group]
        + areas[area] * 0x500
        + section * 128
        + (number - number % 32) // 8
    )
    return off, 0x80000000 >> (number % 32)


##
# @brief Leading text that only repeats the category it is printed under.
# @details The source writes "Covenant Joined, Chaos Servant" and files it under
# "Join Covenants". Printed as a bullet beneath that heading the lead is pure noise, so
# it comes off. Area leads ("Sen's Fortress, Fog Gate 1") are NOT stripped — those say
# where, which is the useful half.
PREFIX_STRIP = {
    "Bells of Awakening": "Bell of Awakening,",
    "Join Covenants": "Covenant Joined,",
    "Lordvessel": "Lordvessel,",
    "NPC": "NPC,",
}


##
# @brief Tidy a display name: drop the trailing id and the category echo.
# @details The CSV writes "Bell of Awakening, Undead Parish 11010700". The id is already
# the key, so repeating it in the printed name is noise.
def clean(name, fid, category):
    name = name.strip()
    if name.endswith(str(fid)):
        name = name[: -len(str(fid))].strip()
    lead = PREFIX_STRIP.get(category)
    if lead and name.startswith(lead):
        name = name[len(lead) :].strip()
    return name or "(unnamed)"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("-o", "--out", default=OUT)
    args = ap.parse_args()

    groups, areas = addressing()
    if not groups or not areas:
        sys.exit(f"no addressing tables in {ADDRESSING}")

    table = collections.defaultdict(list)
    skipped_index = skipped_area = excluded = 0
    with open(KNOWN, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw = (row.get("flag_id") or "").strip()
            if not raw.isdigit():
                continue
            fid = int(raw)
            if len(raw) > 8:
                skipped_index += 1
                continue
            at = address(fid, groups, areas)
            if at is None:
                skipped_area += 1
                continue
            cat = (row.get("category") or "Other").strip() or "Other"
            if cat in EXCLUDE_CATEGORIES:
                excluded += 1
                continue
            table[cat].append([at[0], at[1], clean(row.get("name") or "", fid, cat)])

    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    out = collections.OrderedDict()
    for cat in sorted(table, key=lambda c: (order.get(c, len(order)), c)):
        out[cat] = sorted(table[cat], key=lambda r: (r[0], -r[1]))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(v) for v in out.values())
    print(f"wrote {args.out}: {total} flags in {len(out)} categories")
    for cat, rows in out.items():
        print(f"   {len(rows):3}  {cat}")
    if excluded:
        print(
            f"   dropped {excluded} in {', '.join(sorted(EXCLUDE_CATEGORIES))} "
            f"(transient — see EXCLUDE_CATEGORIES)"
        )
    if skipped_index:
        print(f"   skipped {skipped_index} enum indices (not event flags)")
    if skipped_area:
        print(f"   skipped {skipped_area} with an unmapped group/area")


if __name__ == "__main__":
    main()
