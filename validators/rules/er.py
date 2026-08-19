## @file er.py
## @brief Elden Ring: the shared rules. Rune level shares one K (79) across all ten
## classes, and the stat block is only read at all where it already agrees with the
## roster level, so a slot that reaches these rules has passed one check already.
from .common import level_vs_stats, souls_above_cap, stat_above_cap, stat_below_floor

RULES = [level_vs_stats, stat_above_cap, stat_below_floor, souls_above_cap]

UNIMPLEMENTED = [
    "item stack caps and quantities (ER quantities are not read at all)",
    "weapon upgrade caps, ash-of-war legality (no reinforce data)",
    "anything flag-based (ER's flag region is unsolved, so no boss, grace or pickup "
    "state exists to check against)",
]
