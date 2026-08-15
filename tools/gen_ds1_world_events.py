#!/usr/bin/env python3
"""Build `db_ds1/world_events.json` — Dark Souls 1 world flags, by what they record.

Source: `test/flag_data/files8/dark_souls_1_flags.csv`, extracted from
`HotPocketRemix/DSEventScriptTools`, which commits every vanilla PtDE `.emevd` unpacked
AND the `.emeld` files carrying FromSoft's own event names. The extraction attributes each
`Set Event Flag` instruction to its enclosing `Event ID: N` header, then looks N up in the
matching `.names.txt`.

READ THIS BEFORE TRUSTING A NUMBER HERE. Everything in this table is `derived`, and it is
shipped on the strength of its source rather than on a save this repo has verified it
against. What was checked is that it decodes (398/398 through the repo's own DS1
addressing) and that it discriminates -- 140 set on the NG+2 all-bonfires mule against 110
on a mid-game character and 85 on an all-items mule, which is the right order. What was
NOT established is that each family means what its name says:

  * `lever` reads 0 of 11 on a save with every bonfire lit and 23 bosses dead. A flag that
    must be true there and is not is TRANSIENT -- set while the event runs, cleared after.
    The same signature got DS1's "Boss Fight" category dropped from `known_flags.json`.
  * `boss_defeat` reads 33 on a mule with four bosses proven dead, so it counts FLAGS and
    not bosses: arena, phase and cutscene flags ride in the same family.

Both are printed anyway, with the section note saying so, because the source is real and a
count that moves is better than a blank. Neither number is a boss count and neither should
be read as one. Fixing this means splitting the families per row against the `.emevd` text.

Names are FromSoft's own, VERBATIM JAPANESE. They are not translated here and they are not
rendered -- the section prints per-family counts only. Guessing at a translation would be
inventing a label, and a Japanese string in an English report teaches a reader nothing.

Run from repo root: python3 tools/gen_ds1_world_events.py
"""

import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "test", "flag_data", "files8", "dark_souls_1_flags.csv")
OUT = os.path.join(BASE, "db_ds1", "world_events.json")

# What each family slug is called in the report. A family with no entry keeps its slug
# title-cased, so a source that grows a new one degrades to something readable.
TITLE = {
    "absolution": "Absolution",
    "bell": "Bells",
    "bonfire": "Bonfire events",
    "boss_defeat": "Boss-fight flags",
    "boss_event": "Boss events",
    "covenant": "Covenant events",
    "door": "Doors",
    "elevator": "Elevators",
    "enemy_spawn": "One-time enemy spawns",
    "lever": "Levers",
    "npc_death": "NPC deaths",
    "npc_hostile": "NPCs turned hostile",
    "seal": "Seals",
    "trap_switch": "Trap switches",
    "treasure_chest": "Treasure chests",
}


## @brief Byte offset and uint32 mask for an 8-digit DS1 flag, or None.
#  @details `G AAA S NNN`, MSB-first within the word. The same expression
#  `db_ds1/known_flags.json` is generated with, and it reproduces all twelve
#  independently-derived boss flags exactly.
def address(fid, groups, areas):
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


def addressing():
    path = os.path.join(BASE, "test", "flag_data", "files2", "ds1_flag_addressing.csv")
    groups, areas = {}, {}
    with open(path, encoding="utf-8-sig") as f:
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


def main():
    groups, areas = addressing()
    table, seen, undecodable = {}, set(), 0
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fid = r["flag_id"]
            if not fid.isdigit():
                continue
            addr = address(int(fid), groups, areas)
            if addr is None:
                undecodable += 1
                continue
            # The source lists a flag once per instruction that sets it, so the same flag
            # arrives several times. One flag is one thing that happened.
            key = (r["family"], addr)
            if key in seen:
                continue
            seen.add(key)
            title = TITLE.get(r["family"], r["family"].replace("_", " ").title())
            table.setdefault(title, []).append([addr[0], addr[1], r["name"]])
    if not table:
        sys.exit("no rows survived -- check the source CSV")
    for rows in table.values():
        rows.sort()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(v) for v in table.values())
    print(
        f"wrote {OUT}: {total} flags in {len(table)} families ({undecodable} undecodable)"
    )


if __name__ == "__main__":
    main()
