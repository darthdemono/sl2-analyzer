#!/usr/bin/env python3
"""Build `db_sdt/minibosses.json` from a sourced Sekiro flag dump.

WHY THIS IS A GENERATOR AND NOT A HAND-WRITTEN TABLE
    The rows come from `thefifthmatt/SoulsRandomizers` `dists/Base/enemy.txt`, which is
    the only published table that names Sekiro's minibosses at all. Hand-copying 32 rows
    is how a transcription error ships, and the entity ids ARE the flag ids (see below),
    so a wrong digit invents a kill rather than merely mislabelling one.

WHAT THE FLAG ACTUALLY IS
    Sekiro files a miniboss's defeat under its own ENTITY ID, used directly as an event
    flag. That is not the Dark Souls III convention — DS3 uses a separate `13xxxx8xx`
    per-map block — so it had to be measured here rather than assumed. It was, four ways,
    and all four are recorded in CLAUDE.md:

      * a fresh save reads 0 of 32, and a journey-9 save at maximum Attack Power also
        reads 0, which is the New Game+ reset the other two flag families already show;
      * the local run's ladder is strictly monotone (0, 0, 1, 1, 4, 4, 5 …) and never
        loses one;
      * that run reads its five reachable minibosses and reads the Blazing Bull CLEAR
        while already standing in the Bull's own map, which is what rules out the bit
        being "area entered" rather than "enemy killed";
      * across 51 slot-reads from three unrelated save packs the count rises with the
        boss count and the idol count, both of which are independently verified.

NAMES ARE ENEMY TYPES, NOT THE GAME'S OWN MINIBOSS NAMES
    `enemy.txt` gives a model and a plain-English type — "Chained Ogre", "Shura Samurai",
    "Seven Ashina Spears" — not "Juzou the Drunkard" or "General Naomori Kawarada". Four
    rows are "Shura Samurai" and three are "Shichimen Warrior", so duplicates inside one
    area are REAL and are kept rather than deduped: they are different enemies at
    different entity ids. The render collapses a missing list with `count_dupes`, the
    same way DS3's seven separate mimics are handled. The shipped English names live in
    the FMG tables behind the archive unpack; when those land, only this file changes.

Run from the repo root:

    python3 tools/gen_sdt_minibosses.py test/sekiro_flag_data.json
"""

import argparse
import json
import sys

## @brief Map id → the area name the report prints. Deliberately the same vocabulary as
#  `db_sdt/idols.json` uses, so the two Sekiro progress sections agree on what an area is
#  called — except Ashina Reservoir, which idols.json folds into Ashina Castle and which
#  is kept separate here because it is its own map and its minibosses are endgame-only.
SDT_MAP_AREA = {
    "m11_00_00_00": "Ashina Outskirts",
    "m10_00_00_00": "Hirata Estate",
    "m11_01_00_00": "Ashina Castle",
    "m11_02_00_00": "Ashina Reservoir",
    "m13_00_00_00": "Abandoned Dungeon",
    "m20_00_00_00": "Senpou Temple, Mt. Kongo",
    "m17_00_00_00": "Sunken Valley",
    "m15_00_00_00": "Ashina Depths",
    "m25_00_00_00": "Fountainhead Palace",
}


## @brief Rows MEASURED here, that the source does not have.
#  @details The source is a placement dump and it is not complete. Each entry below was
#  pinned the way the Blazing Bull was: a save either side of one named kill, with the
#  owner saying what died, and exactly one entity-shaped flag in that map turning on
#  across the window and staying on.
#
#  `1120450` — **Lone Shadow Longswordsman**, Ashina Reservoir. Killed in the
#  17:35:58 → 17:52:36 window on the local ladder. It is the only block-0 (entity-shaped)
#  flag in map `(11,2)` to flip there, it reads 0 in all twenty earlier saves, and it is
#  still set in the newest. **The source's own Lone Shadow row for that map is `1120300`,
#  and that flag has never been set in any save here** — so either it is a second
#  placement nobody has killed, or the row is simply wrong. Both are kept: the measured
#  one because it is proven, the sourced one because dropping a placement on suspicion is
#  the mistake in the other direction.
MEASURED = [
    {
        "entity_id": 1120450,
        "map": "m11_02_00_00",
        "type": "Lone Shadow Longswordsman",
    },
]


##
# @brief Turn the sourced rows into {area: [[entity id, name]]}, in map order.
# @details Areas follow @ref SDT_MAP_AREA's own insertion order, which is roughly the
# route through the game — the same reason `idols.json` is ordered the way it is. Within
# an area, rows keep ascending entity id, which is close enough to the order you meet
# them and is at least stable between regenerations.
# @param rows The `minibosses.rows` list from the sourced dump.
# @return An OrderedDict-shaped plain dict ready to serialise.
def build(rows):
    out = {area: [] for area in SDT_MAP_AREA.values()}
    for row in sorted(list(rows) + MEASURED, key=lambda r: r["entity_id"]):
        area = SDT_MAP_AREA.get(row["map"])
        if area is None:
            sys.exit(
                f"unknown map {row['map']!r} — add it to SDT_MAP_AREA before "
                f"regenerating, or entity {row['entity_id']} is silently dropped"
            )
        out[area].append([row["entity_id"], row["type"]])
    # An area with no miniboss would render as a permanent 0/0 row, which says nothing.
    return {area: rows for area, rows in out.items() if rows}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("source", help="the sourced flag dump (test/sekiro_flag_data.json)")
    ap.add_argument("-o", "--out", default="db_sdt/minibosses.json")
    args = ap.parse_args()

    with open(args.source, encoding="utf-8") as f:
        data = json.load(f)
    block = data.get("minibosses") or {}
    rows = block.get("rows") or []
    if not rows:
        sys.exit("no minibosses.rows in the source dump")
    # The source ships `defeat_event_flag: null` on every row because no published table
    # carries one. That is correct and must stay correct: the flag is the ENTITY ID, and
    # a non-null value here would mean somebody found a real flag table and this
    # generator needs rewriting rather than rerunning.
    named = [r for r in rows if r.get("defeat_event_flag") is not None]
    if named:
        sys.exit(
            f"{len(named)} row(s) carry a defeat_event_flag. The source has gained "
            f"real flag ids — use them instead of the entity id, and update the "
            f"reasoning in this docstring and in CLAUDE.md before regenerating."
        )

    table = build(rows)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(v) for v in table.values())
    print(f"wrote {args.out}: {total} minibosses in {len(table)} areas")
    print(f"source: {block.get('source', 'unrecorded')}")


if __name__ == "__main__":
    main()
