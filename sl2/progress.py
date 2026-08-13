"""Progress inference shared by every game: boss souls held, key items, the
NG+ mandatory-clear floor, and the denominators each progress section prints.
"""

import json
import os
from collections import OrderedDict

## @brief Ordinary soul consumables that are NOT boss souls. A boss soul in your
#         pack means the boss is dead; a "Soul of a Lost Undead" just means you
#         killed something ordinary.
GENERIC_SOULS = {
    "Fading Soul",
    "Soul of a Lost Undead",
    "Large Soul of a Lost Undead",
    "Soul of a Nameless Soldier",
    "Large Soul of a Nameless Soldier",
    "Soul of a Proud Knight",
    "Large Soul of a Proud Knight",
    "Soul of a Brave Warrior",
    "Large Soul of a Brave Warrior",
    "Soul of a Hero",
    "Soul of a Great Hero",
    "Soul of a Old Hero",
    "Wandering Soul",
    "Old Soul",
    # Dark Souls III generic farm souls — not bosses.
    "Soul of a Deserted Corpse",
    "Large Soul of a Deserted Corpse",
    "Soul of an Unknown Traveler",
    "Large Soul of an Unknown Traveler",
    "Soul of a Weary Warrior",
    "Large Soul of a Weary Warrior",
    "Soul of a Crestfallen Knight",
    "Large Soul of a Crestfallen Knight",
    "Soul of a Venerable Old Hand",
    "Soul of a Champion",
    "Soul of a Great Champion",
    "Soul of a Seasoned Warrior",
    "Large Soul of a Seasoned Warrior",
    "Soul of an Intrepid Hero",
    "Large Soul of an Intrepid Hero",
}


## @brief DS1 progression goods that gate the world but do not read as "keys".
#  Crest of Artorias opens the sealed Darkroot door, so it gates as hard as a key.
DS1_PROGRESSION = {
    "Lordvessel",
    "Peculiar Doll",
    "Broken Pendant",
    "Rite of Kindling",
    "Crest of Artorias",
}


## @brief Pull the likely boss / lord souls out of a goods list.
def find_boss_souls(goods):
    out = []
    for n, q in goods:
        if n in GENERIC_SOULS:
            continue
        if (
            "Soul of " in n
            or "Lord Soul" in n
            or n in ("Core of an Iron Golem", "Guardian Soul")
        ):
            out.append((n, q))
    return out


## @brief Per-game folder holding a boss-soul → boss-name table (boss_souls.json).
#  DS2 runs its own richer multi-source inference; these cover the games whose only
#  proof-of-kill floor is the boss souls / remembrances the character still holds.
#  Sekiro's table maps its Memory items, which are the same kind of token — and the
#  only one in the series whose spending leaves a trace (see sdt_memories_spent).
BOSS_SOUL_DB_DIR = {
    "dsr": "db_ds1",
    "ptde": "db_ds1",
    "ds3": "db_ds3",
    "er": "db_er",
    "sdt": "db_sdt",
}


## @brief Load a game's boss-soul → boss-name table. Cached per (base_dir, subdir).
_BOSS_SOUL_CACHE = {}


def load_boss_soul_map(base_dir, subdir):
    key = (base_dir, subdir)
    if key not in _BOSS_SOUL_CACHE:
        path = os.path.join(base_dir, subdir, "boss_souls.json")
        try:
            with open(path, encoding="utf-8") as f:
                _BOSS_SOUL_CACHE[key] = json.load(f)
        except (OSError, ValueError):
            _BOSS_SOUL_CACHE[key] = {}
    return _BOSS_SOUL_CACHE[key]


## @brief Load a game's route graph (boss_route.json): boss name →
#  @c [gate area, [bosses that must die first]]. GAME STRUCTURE, not a save read —
#  it exists to answer "what can I fight now", which no flag can. The area name is a
#  key of that game's own bonfire table, so "the area was reached" is decided by that
#  area's lit bonfires; the predecessor list is only the HARD gates (the arena or key
#  you cannot get past otherwise), never a suggested order.
#  Cached per (base_dir, subdir). Returns {} if the game has no table.
_BOSS_ROUTE_CACHE = {}


def load_boss_route(base_dir, subdir):
    key = (base_dir, subdir)
    if key not in _BOSS_ROUTE_CACHE:
        path = os.path.join(base_dir, subdir, "boss_route.json")
        try:
            with open(path, encoding="utf-8") as f:
                _BOSS_ROUTE_CACHE[key] = json.load(f)
        except (OSError, ValueError):
            _BOSS_ROUTE_CACHE[key] = {}
    return _BOSS_ROUTE_CACHE[key]


## @brief Endgame-only progression prereqs: a proven-dead boss (key) implies its
#  mandatory predecessors (values) are dead too, tagged `gate`. Each key lists ALL
#  its predecessors (already flattened), so one closure pass suffices. DELIBERATELY
#  ENDGAME-ONLY, mirroring DS2's `DS2_BOSS_PREREQ` rule: only strictly-linear,
#  cannot-skip mandatory chains qualify — a mid-game gate would risk a false kill
#  (the core rule). Sourced from each game's fixed endgame route.
#
#  DS3: the four Lords of Cinder plus Iudex Gundyr are all mandatory to fight Soul
#  of Cinder, and Vordt/Dancer gate the only path forward (High Wall → … → Lothric
#  Castle). Aldrich sits past Pontiff Sulyvahn in Irithyll.
#  ER: Morgott (Leyndell) → Fire Giant (Forge) → Maliketh (Farum Azula) → Godfrey/
#  Hoarah Loux (Ashen Leyndell) is the fixed mandatory endgame chain; each requires
#  every earlier one. Morgott's own prereqs are player-choice great runes, so it
#  gates nothing specific.
BOSS_PREREQ = {
    "ds3": {
        "Soul of Cinder": [
            "Iudex Gundyr",
            "Vordt of the Boreal Valley",
            "Dancer of the Boreal Valley",
            "Abyss Watchers",
            "Aldrich, Devourer of Gods",
            "Yhorm the Giant",
            "Lothric, Younger Prince",
        ],
        "Lothric, Younger Prince": [
            "Dancer of the Boreal Valley",
            "Vordt of the Boreal Valley",
            "Iudex Gundyr",
        ],
        "Aldrich, Devourer of Gods": [
            "Pontiff Sulyvahn",
            "Vordt of the Boreal Valley",
            "Iudex Gundyr",
        ],
        "Dancer of the Boreal Valley": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Pontiff Sulyvahn": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
        "Vordt of the Boreal Valley": ["Iudex Gundyr"],
    },
    "er": {
        "Godfrey, First Elden Lord (Hoarah Loux)": [
            "Maliketh, the Black Blade",
            "Fire Giant",
            "Morgott, the Omen King",
        ],
        "Maliketh, the Black Blade": ["Fire Giant", "Morgott, the Omen King"],
        "Fire Giant": ["Morgott, the Omen King"],
    },
}


## @brief Bosses that CANNOT be skipped to finish the game, so **reaching NG+ proves
#  every one of them dead at least once** (tag `clear`). DS1 (dsr/ptde) is linear from
#  Anor Londo on: both bells (Gargoyles, Quelaag), Sen's/Anor Londo (Iron Golem, O&S),
#  the four Lord Souls (Nito, Bed of Chaos, Four Kings — needs Sif's ring — and Seath)
#  and Gwyn are all mandatory. Deliberately endgame-safe, the same core-rule caution as
#  the gate maps — no mid-game boss whose route can be skipped is listed. (DS2 handles
#  this itself in ds2_infer_bosses, seeding only its final boss Nashandra, because DS2's
#  mid-game is skippable — Shrine of Winter opens on Soul Memory alone.)
MANDATORY_BOSSES = {
    "dsr": [
        "Bell Gargoyles",
        "Chaos Witch Quelaag",
        "Iron Golem",
        "Dragon Slayer Ornstein",
        "Executioner Smough",
        "Great Grey Wolf Sif",
        "The Four Kings",
        "Seath the Scaleless",
        "Gravelord Nito",
        "Bed of Chaos",
        "Gwyn, Lord of Cinder",
    ],
}


MANDATORY_BOSSES["ptde"] = MANDATORY_BOSSES["dsr"]


## DS3's unskippable path to Soul of Cinder — the four Lords of Cinder plus the
## bosses that gate them (Iudex/Vordt/Dancer/Pontiff/Dragonslayer Armour). Reaching
## NG+ proves all of these dead even if their souls were spent. Optional bosses
## (Greatwood, Crystal Sage, Wolnir, Nameless King…) are deliberately excluded.
MANDATORY_BOSSES["ds3"] = [
    "Iudex Gundyr",
    "Vordt of the Boreal Valley",
    "Dancer of the Boreal Valley",
    "Abyss Watchers",
    "Pontiff Sulyvahn",
    "Aldrich, Devourer of Gods",
    "Yhorm the Giant",
    "Dragonslayer Armour",
    "Lothric, Younger Prince",
    "Soul of Cinder",
]


## @brief Attach a `bosses` defeat floor to a non-DS2 character from the boss souls
#  / remembrances it still holds, plus endgame progression. A held boss soul is a
#  boss killed — you cannot own the soul otherwise — so each maps to its boss with
#  `soul` evidence, and its mandatory endgame predecessors get `gate` (see
#  BOSS_PREREQ), the same certain-when-true signals DS2 uses. If the character is in
#  NG+ (ng_plus > 0) every MANDATORY_BOSSES entry is proven dead too (`clear`). A boss
#  whose soul was consumed, not gated and not mandatory, is invisible here (the render
#  note says so). DS2 sets its own richer `bosses` via augment and is skipped.
def attach_defeated_bosses(ch, base_dir):
    game = ch.get("game")
    subdir = BOSS_SOUL_DB_DIR.get(game)
    if not subdir or ch.get("bosses"):
        return
    soul_db = load_boss_soul_map(base_dir, subdir)
    bosses = {}
    for name, _q in ch.get("boss_souls") or []:
        boss = soul_db.get(name)
        if boss:
            bosses.setdefault(boss, set()).add("soul")
    if (ch.get("ng_plus") or 0) > 0:
        for boss in MANDATORY_BOSSES.get(game, ()):
            bosses.setdefault(boss, set()).add("clear")
    prereq = BOSS_PREREQ.get(game, {})
    for boss in list(bosses):
        for pre in prereq.get(boss, ()):
            bosses.setdefault(pre, set()).add("gate")
    if bosses:
        # Sort each evidence set for a stable render order (matches ds2_infer_bosses,
        # which already sorts); boss keys keep insertion order.
        ch["bosses"] = {b: sorted(bosses[b]) for b in bosses}


## @brief The four Lords of Cinder, boss name → the name on the Firelink throne.
#  A closed set: all four must be placed before the Kiln opens, so "N of 4" is a real
#  denominator rather than an open-ended list.
DS3_LORDS = OrderedDict(
    [
        ("Abyss Watchers", "Abyss Watchers"),
        ("Yhorm the Giant", "Yhorm the Giant"),
        ("Aldrich, Devourer of Gods", "Aldrich"),
        ("Lothric, Younger Prince", "Twin Princes"),
    ]
)


## @brief The one item id (any lord's) that sits in the inventory between killing a
#  Lord of Cinder and offering the ashes at the throne.
DS3_CINDER_ITEM = "Cinders of a Lord"


## @brief Pull key / progression items out of a goods list (DS1 keeps keys here).
def find_key_goods(goods):
    return [(n, q) for n, q in goods if "Key" in n or n in DS1_PROGRESSION]
