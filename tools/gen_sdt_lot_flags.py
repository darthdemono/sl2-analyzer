#!/usr/bin/env python3
"""Regenerate db_sdt/lot_flags.json: the flag each Sekiro item lot REALLY sets.

`db_sdt/item_flags.json` files every world pickup under `50000000 + lot id`, and for
most lots that is the flag the game writes. Not for all of them. The game's own
`ItemLotParam` gives each lot a `getItemFlagId`, and a hundred rows in the table point
somewhere else — including every prosthetic part, every esoteric text, every Gourd Seed
and every world Prayer Bead in the nine areas the tool reads. Those lots set a GLOBAL
flag (`6500` for the Shuriken Wheel, `6725` for the courtyard Gourd Seed), so reading
the lot-shaped id reported them "still out there" on a save that had picked up all of
them hours earlier.

This joins the two and writes only the corrections, so `item_flags.json` itself is not
hand-edited:

    moved     {row id: the flag the lot actually sets}, where the two differ
    misfiled  [[row id, name]] for rows whose lot hands out a DIFFERENT item, so the
              row's id says nothing about the item it names

A row counts as the lot's item when one of the lot's item names starts with the row's
name — the game's own names carry suffixes the table drops (`Sabimaru Memo (Bought)`,
`Sweet Rice Ball 2`). An id with no English name is no evidence either way and leaves
the row alone.

Input is `ItemLotParam` as `gen_sdt_from_regulation.py` extracts it, one row per lot:

    python3 tools/gen_sdt_from_regulation.py --game-root ... --paramdex ... --out DIR
    python3 tools/gen_sdt_lot_flags.py --lots DIR/item_flags.tsv [--write]

Without --write it prints the delta and writes nothing.
"""

import argparse
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "db_sdt")

## The pickup family's id rule: a row id is this plus the lot id.
LOT_FLAG_BASE = 50000000
## ItemLotParam carries eight item slots per lot.
LOT_SLOTS = 8


def load_json(name):
    with open(os.path.join(DB, name), encoding="utf-8") as f:
        return json.load(f)


def item_names():
    names = {}
    for stem in ("weapons", "goods"):
        for k, v in load_json(stem + ".json").items():
            names.setdefault(int(k), []).append(v)
    return names


def load_lots(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {int(r["id"]): r for r in csv.DictReader(f, delimiter="\t")}


def lot_items(lot, names):
    out = []
    for i in range(1, LOT_SLOTS + 1):
        iid = int(lot[f"lotItemId{i:02d}"])
        if iid:
            out += names.get(iid, [])
    return out


def build(lots, rows, names):
    moved, misfiled = {}, []
    for fid, name, _where in rows:
        lot = lots.get(fid - LOT_FLAG_BASE)
        if lot is None:
            continue
        items = lot_items(lot, names)
        if items and not any(n.startswith(name) for n in items):
            misfiled.append([fid, name])
            continue
        flag = int(lot["getItemFlagId"])
        if flag > 0 and flag != fid:
            moved[str(fid)] = flag
    return {"moved": moved, "misfiled": misfiled}


## House style for db_*/: one-space indent, a short pair kept on one line.
def dump(table):
    moved = ",\n".join(f'  "{k}": {v}' for k, v in table["moved"].items())
    misfiled = ",\n".join(
        f"  {json.dumps(r, ensure_ascii=False)}" for r in table["misfiled"]
    )
    return f'{{\n "moved": {{\n{moved}\n }},\n "misfiled": [\n{misfiled}\n ]\n}}\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lots", required=True, help="ItemLotParam TSV (item_flags.tsv)")
    ap.add_argument("--write", action="store_true", help="write db_sdt/lot_flags.json")
    args = ap.parse_args()

    rows = load_json("item_flags.json").get("item_pickup", [])
    table = build(load_lots(args.lots), rows, item_names())
    print(f"{len(table['moved'])} rows moved, {len(table['misfiled'])} misfiled")
    for fid, name in table["misfiled"]:
        print(f"  misfiled {fid} {name}")
    if args.write:
        with open(os.path.join(DB, "lot_flags.json"), "w", encoding="utf-8") as f:
            f.write(dump(table))
        print("wrote db_sdt/lot_flags.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
