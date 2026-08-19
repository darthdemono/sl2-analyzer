##
# @file ds2.py
# @brief Dark Souls II, both releases. Level-vs-stats runs on a MEASURED K of 53; the
# per-stat floor does not run at all, because no class table for DS2 has been checked
# against a save here and a floor that is too high would invent findings. That is a
# deliberate gap, and it is in UNIMPLEMENTED where the reader can see it.
from ..models import INCONSISTENT, Finding
from .common import level_vs_stats, souls_above_cap, stat_above_cap, stat_below_floor


##
# @brief Souls held against soul memory, DS2's own running total.
# @details Soul memory counts every soul the character has EVER gained and never goes
# down, so it cannot be smaller than the souls currently in hand. Spending, dying and
# losing a bloodstain all move the held number down and leave soul memory where it was,
# which is why the inequality only ever fails in one direction. Zero hits across all 75
# DS2 characters here.
def souls_vs_soul_memory(ch, gd):
    souls, memory = ch.get("souls"), ch.get("soul_memory")
    if souls is None or not memory:
        return None
    if souls <= memory:
        return []
    return [
        Finding(
            "souls-vs-soul-memory",
            INCONSISTENT,
            "Souls held vs soul memory",
            f"held <= soul memory {memory:,}",
            f"held {souls:,}",
        )
    ]


RULES = [
    level_vs_stats,
    stat_above_cap,
    stat_below_floor,
    souls_above_cap,
    souls_vs_soul_memory,
]

UNIMPLEMENTED = [
    "per-stat floors (db_ds2/classes.json ships no starting-class rows: 53 is measured "
    "from the corpus, the individual class bases are not)",
    "item stack caps (no stack-size column in db_ds2)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
]
