##
# @file data.py
# @brief The per-game constants a rule needs, loaded from db_<game>/classes.json.
#
# Everything here is derived from the shipped table rather than hard-coded, so a
# corrected class row changes the rules with it and nothing has to be kept in sync by
# hand. The one thing that is hard-coded is which db_ directory a game key uses, because
# the GAMES entry spells that differently per game and this pass must not depend on the
# shape of a parser's config.
import json
import os

## @brief Repo root, so a caller does not have to thread a path through two writers just
#  to reach db_<game>/classes.json. The package lives beside the db_ folders.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

## @brief Game key to its table directory. Sekiro and Nightreign have no class table:
#  Sekiro has no attributes at all, and Nightreign levels a Nightfarer, not a character.
DB_DIR = {
    "ptde": "db_ds1",
    "dsr": "db_ds1",
    "ds2vanilla": "db_ds2",
    "ds2sotfs": "db_ds2",
    "ds3": "db_ds3",
    "er": "db_er",
    "sdt": None,
    "nr": None,
}

_CACHE = {}


##
# @brief The game's validation constants, or None where the game has no table.
# @details Returns a dict with the file's own keys plus three derived ones:
#  `k_values` (the set membership rule 1 tests), `floors` (the lowest a stat can start
#  at across every class) and `classes` (name -> row). K is `sum(base stats) - starting
#  level`, which is the game's own level formula rearranged, so it is computed here
#  rather than stored — a wrong stat in the table cannot then disagree with a stored K.
# @param game     Game key. @param base_dir Repo root; defaults to @ref BASE_DIR.
# @return The constants dict, or None.
def game_data(game, base_dir=None):
    base_dir = base_dir or BASE_DIR
    key = (game, base_dir)
    if key in _CACHE:
        return _CACHE[key]
    d = DB_DIR.get(game)
    path = os.path.join(base_dir, d, "classes.json") if d else None
    if not path or not os.path.exists(path):
        _CACHE[key] = None
        return None
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    classes = t.get("starting_classes") or {}
    ks = sorted({sum(r["stats"].values()) - r["level"] for r in classes.values()})
    floors = {}
    for row in classes.values():
        for stat, v in row["stats"].items():
            floors[stat] = min(floors.get(stat, v), v)
    out = dict(t)
    # A game with no class table falls back to the measured K list, which is how DS2
    # ships: 53 on all 75 of its characters here, no per-class rows claimed.
    out["k_values"] = ks or sorted(t.get("k_values", []))
    out["floors"] = floors
    out["classes"] = classes
    _CACHE[key] = out
    return out
