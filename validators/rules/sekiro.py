##
# @file sekiro.py
# @brief Sekiro has no attributes, no level and no class, so every rule in common.py has
# nothing to read. Attack Power and Vitality are counters the game raises one at a time
# and no published source gives their hard maximum, so bounding them would be inventing
# a cap rather than checking one.
RULES = []

UNIMPLEMENTED = [
    "everything the other games check: Sekiro stores no attributes, no level and no "
    "starting class, so the level identity has nothing to test",
    "Attack Power / Vitality bounds (no verified maximum for either counter)",
    "item stack caps (no stack-size column in db_sdt)",
]
