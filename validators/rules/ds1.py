## @file ds1.py
## @brief Dark Souls (PtDE and Remastered). The one game here whose K really is a SET:
## Sorcerer 79, Knight and Thief 81, Warrior/Bandit/Hunter/Cleric/Deprived 82,
## Wanderer and Pyromancer 83.
from .common import level_vs_stats, souls_above_cap, stat_above_cap, stat_below_floor

RULES = [level_vs_stats, stat_above_cap, stat_below_floor, souls_above_cap]

UNIMPLEMENTED = [
    "humanity and the soft/hard humanity caps (no verified bound for the counter)",
    "item stack caps (no stack-size column in db_ds1)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
]
