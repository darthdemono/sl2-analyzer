## @file ds3.py
## @brief Dark Souls III: the four shared rules, on a K set of one.
from .common import level_vs_stats, souls_above_cap, stat_above_cap, stat_below_floor

RULES = [level_vs_stats, stat_above_cap, stat_below_floor, souls_above_cap]

## @brief Checks this game has no data for. Each entry names what is missing, not what
#  would be nice: the reader is being told which questions were never asked.
UNIMPLEMENTED = [
    "item stack caps (no stack-size column in db_ds3)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
    "unrecognised item ids (the tables are known to be incomplete, so an unknown id is "
    "a gap in db_ds3 as often as it is an edit)",
]
