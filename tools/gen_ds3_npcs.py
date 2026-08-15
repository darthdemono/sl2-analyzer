#!/usr/bin/env python3
"""Build `db_ds3/npcs.json` — Dark Souls III NPC deaths, hostility and quest states.

Sources, both in `test/flag_data/files8/dark_souls_3_flags.csv`: Smithbox's committed
`Documentation/DS3/Info - QWC Flags.txt`, which is FromSoft's own English descriptions,
and rows extracted from the decompiled `.emevd` (`20006002` awaits a `CharacterDead` then
sets a flag; `20006000` sets `HostileNPC` then a flag).

THE BASE IS THE INTERESTING PART, and it is derived rather than taken from anywhere. Three
DS3 common-group bases had been pinned one differential at a time; they are not
independent. A group holds `n < 1000`, so it occupies 128 bytes, and groups 0..9 are packed
128 apart inside the `k = 0` category:

    base(g) = 111 + 128 * g          # g < 10

`6 -> 879` and `9 -> 1263` fall straight out of that, which is two of the three already
known. It predicts `1 -> 239`, and group 1 is where most of these flags live. Checked three
ways: at 239 all 161 group-1 flags are MONOTONE across a 79-save ladder with 43 ever set,
the only rival candidate is non-monotone eleven times, and -- the one that settles it --
flag `1218` "character 3000700 killed" first reads set in exactly the 33:31:38 snapshot,
which is where Ringfinger Leonhard's own Red Eye Orb pickup flag turns on. 3000700 is
Leonhard. The whole family dates correctly besides: `4500701` (Ariandel) at 45:06,
`5100810` (Ringed City) at 56:59, `5000705` (Dreg Heap) at 62:49.

TWO WARNINGS THAT MUST SURVIVE INTO THE REPORT.

  * The QWC descriptions are NOT reliable per row. The same ladder that confirmed the base
    shows `1158` -- which the source calls "after killing Leonhard" -- never setting on a
    run where Leonhard demonstrably died. The EMEVD-derived row is right and the English
    label is on the wrong one. Where a flag has both, the English is kept because it is
    what a reader can use, and the entity id is appended so a wrong label is checkable.
  * `character 3000700 killed` is an entity id, not a name. Rows with no English label
    print that, because the alternative is inventing a name.

Only flags in groups 0..9 are emitted. The `70000` and `73xxx`-`74xxx` shop and handover
groups are two orders of magnitude past the single-digit grid, so this shortcut cannot
reach them and each needs its own anchor -- a differential either side of handing something
to the Shrine Handmaid.

Run from repo root: python3 tools/gen_ds3_npcs.py
"""

import csv
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "test", "flag_data", "files8", "dark_souls_3_flags.csv")
OUT = os.path.join(BASE, "db_ds3", "npcs.json")

# Groups 0..9 live in the k=0 category, packed 128 bytes apart, the first at the same 111
# every other DS3 group is offset by.
GROUP_STRIDE = 128
GROUP_ZERO = 111

TITLE = {
    "npc_death": "NPCs killed",
    "npc_turned_hostile": "NPCs turned hostile",
    "npc_quest": "Questline states",
    "npc_handover": "Items handed over",
    "area_entered": "Areas entered",
    "world_state": "World state",
    "dlc_ownership": "DLC owned",
}


## @brief Flag id -> (distance into the flag region, bit), or None outside groups 0..9.
def address(fid):
    group, n = fid // 1000, fid % 1000
    if group > 9:
        return None
    return (
        GROUP_ZERO + group * GROUP_STRIDE + (n >> 5) * 4 + 3 - ((n & 31) >> 3),
        7 - (n & 7),
    )


## @brief The best label for a flag, given every row that carries it.
#  @details An English description beats an entity id, because it is the half a reader can
#  act on. The entity ids are appended when there is a description AND ids, so a label the
#  ladder later proves wrong -- and one already is -- can be checked against the entity
#  that actually died rather than quietly believed.
def label_for(names):
    described = [n for n in names if not re.match(r"^character \d+ ", n)]
    entities = sorted(
        {m.group(1) for n in names for m in [re.match(r"^character (\d+) ", n)] if m}
    )
    if described:
        text = " / ".join(sorted(set(described)))
        return f"{text} (entity {', '.join(entities)})" if entities else text
    return " / ".join(sorted(set(names)))


def main():
    rows = {}
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["flag_id"].isdigit():
                continue
            addr = address(int(r["flag_id"]))
            if addr is None:
                continue
            # "after defeating <boss>" rows are boss-death flags wearing an NPC family
            # name. This repo already reports bosses from two flag families and a soul
            # floor; a third, noisier list would say nothing new and would disagree with
            # the other two the moment one of them gains a boss.
            if r["name"].startswith("after defeating "):
                continue
            rows.setdefault((r["family"], addr), []).append(r["name"])
    if not rows:
        sys.exit("no rows survived -- check the source CSV")
    table = {}
    for (family, addr), names in rows.items():
        title = TITLE.get(family, family.replace("_", " ").capitalize())
        table.setdefault(title, []).append([addr[0], addr[1], label_for(names)])
    for rs in table.values():
        rs.sort()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(v) for v in table.values())
    print(f"wrote {OUT}: {total} flags in {len(table)} families")


if __name__ == "__main__":
    main()
