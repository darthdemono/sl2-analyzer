#!/usr/bin/env python3
"""Build `db_ds3/enemies.json` — the one-time enemies whose death Dark Souls III flags.

Source: `test/flag_data/files7/ds3_onetime_enemy_flags.csv`, itself extracted from the
`.emevd` committed in `thefifthmatt/SoulsRandomizers` `dist/Base/`. The rows are calls to
`common_func` templates that take a death flag and an entity id -- `20005340`, `20005341`,
`20005342`, `20000343` (the mimics), `20005416`, `20005061`, `20005760`, plus map-local
events that gate on a flag at start and set it after a death check -- those are deduped by
entity id, for the reason given at the dedupe.

WHY THIS IS TRUSTED, since a table of ids is worth nothing on its own. Run against a
79-save ladder in play-time order the count climbs 3 -> 98 with ZERO regressions, and the
per-area breakdown lands where the player actually was: at 12:17:13 it reads Cathedral 9,
Road of Sacrifices 7, High Wall 3, Undead Settlement 3, and nothing at all in Irithyll,
Archdragon Peak, the Grand Archives or either DLC. A wrong base reads noise, and noise
does not do that. `scratch/ds3_enemy_flags.py` is the check; re-run it if this table moves.

The flags do NOT reset on a new journey -- the NG+2 ending save still reads 98, which is
`63xx` boss-victory behaviour rather than per-map `13xxxx8xx` behaviour.

Five more rows are dropped: their groups (`8`, `9`, `13105`) have no base in the CE
table, and an unmapped group is absent rather than guessed, exactly like the three
world-pickup groups. `X8` of the mimic template is NOT read -- the packet calls it a drop
flag, but all six Irithyll Dungeon copies turn on in one snapshot while their death flags
turn on hours apart, which is what an area-enable flag looks like.

Run from repo root: python3 tools/gen_ds3_enemies.py
"""

import csv
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "test", "flag_data", "files7", "ds3_onetime_enemy_flags.csv")
BASES = os.path.join(BASE, "scratch", "ds3flags", "ds3_flag_group_bases.csv")
OUT = os.path.join(BASE, "db_ds3", "enemies.json")

# The save sits this far past the Cheat Engine table's memory offset, verified across all
# sixteen map groups when the bonfires were derived.
SAVE_DELTA = 111


## @brief Flag id -> (distance into the flag region, bit), or None for an unmapped group.
#  @details The byte counts DOWN inside each uint32 word. Same expression as every other
#  DS3 table here, and it reproduces all 77 shipped bonfires exactly.
def address(fid, ks):
    k = ks.get(fid // 1000)
    if k is None:
        return None
    n = fid % 1000
    return k * 0x500 + (n >> 5) * 4 + 3 - ((n & 31) >> 3) + SAVE_DELTA, 7 - (n & 7)


## @brief "Crystal Lizard [entity 3200259]" -> "Crystal Lizard".
#  @details The entity id is how the extractor kept rows apart; it is not a name, and
#  47 lines reading "Crystal Lizard [entity ...]" say less than 47 reading the type and a
#  count. Duplicates ACROSS rows are real and are collapsed at render time by
#  `count_dupes`, the same way seven separate mimics and four Shura Samurai already are —
#  but a duplicate INSIDE one row is one flag covering two enemies, so it collapses here.
#  Rows the source could not name keep their entity id, because "Unnamed enemy" three
#  times would merge three different enemies into one line.
def clean(name):
    name = re.sub(r"\s*\[entity [\d/]+\]", "", name).strip()
    parts, seen = [], set()
    for part in re.split(r"\s*(?:\|\||\+)\s*", name):
        part = part.strip()
        part = re.sub(r"^entity (\d+)$", r"Unnamed enemy (\1)", part)
        if part and part not in seen:
            seen.add(part)
            parts.append(part)
    return " + ".join(parts)


## @brief "Lothric Castle (m30_01_00_00)" -> "Lothric Castle".
#  @details The map id is what the EMEVD file was called. A reader wants the area, and the
#  spelling has to match nothing else here -- this is its own section, not a join.
def area_of(text):
    return re.sub(r"\s*\(m\d\d_\d\d_\d\d_\d\d\)", "", text).strip()


def main():
    with open(BASES) as f:
        ks = {
            int(r["flag_group (id//1000)"]): int(r["k (base/0x500)"])
            for r in csv.DictReader(f)
        }
    table, dropped, local, seen_entities = {}, [], 0, set()
    with open(SRC) as f:
        for r in csv.DictReader(f):
            fid = int(r["flag_id"])
            # MAP-LOCAL rows are kept, but DEDUPED BY ENTITY ID, and the Nameless King is
            # why: three separate map-local flags (13200850/855/856) all carry his one
            # entity id, so listing each would report him killed three times. One entity
            # is one enemy, so the first flag wins and the rest are dropped. The
            # `common_func` rows are template invocations with one flag per entity and do
            # not have the problem. These rows are still the softer half of the table --
            # a flag set after a death check can also be a phase or music flag, and the
            # source's own filter (gated at event start AND set after the death check) is
            # what stands between them and a false kill.
            entity = re.search(r"\[entity ([\d/]+)\]", r["enemy_name"])
            if "Map-local event" in r["notes"]:
                key = entity.group(1) if entity else r["enemy_name"]
                if key in seen_entities:
                    local += 1
                    continue
                seen_entities.add(key)
            addr = address(fid, ks)
            if addr is None:
                dropped.append(fid)
                continue
            table.setdefault(area_of(r["area_or_map"]), []).append(
                [addr[0], addr[1], clean(r["enemy_name"])]
            )
    if not table:
        sys.exit("no rows survived -- check the source CSV")
    for rows in table.values():
        rows.sort(key=lambda t: (t[2], t[0], t[1]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(v) for v in table.values())
    print(f"wrote {OUT}: {total} enemies in {len(table)} areas")
    print(
        f"dropped {len(dropped)} in groups with no base: {sorted({d // 1000 for d in dropped})}"
    )
    print(f"dropped {local} duplicate map-local rows (same entity, another flag)")


if __name__ == "__main__":
    main()
