"""Item-name databases. Three id schemes across the four games — see the db_*/
folders and CLAUDE.md for why DS2 is id-keyed and the others are not.
"""
import json
import os


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


##
# @brief Load an id-scan database: per-category JSON of @c {name: id}, flattened
#        to @c {id: (name, category)}.
# @param db_dir Folder of category JSON files.
# @param files  Filename-stem to category mapping.
# @param refine Optional @c (id, cat) -> cat hook, used to split DS3's one goods
#               file into the finer categories the render prints.
# @return The flat lookup, or {} if the folder is absent.
def load_scan_db(db_dir, files, refine=None):
    if not os.path.isdir(db_dir):
        return {}
    db = {}
    for stem, cat in files.items():
        path = os.path.join(db_dir, stem + ".json")
        if os.path.exists(path):
            for name, iid in json.load(open(path, encoding="utf-8")).items():
                iid = int(iid)
                db.setdefault(iid, (name, refine(iid, cat) if refine else cat))
    return db
