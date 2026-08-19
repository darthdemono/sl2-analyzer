##
# @file rules/__init__.py
# @brief Which rules run for which game, and what each game has no rule for.
#
# Registration is the whole point of this file: adding a rule is one function in a rules
# module and one line in that game's RULES list, and nothing else in the package changes.
# UNIMPLEMENTED is not decoration — a save that trips nothing has only been checked
# against the rules that exist, and the report prints this list so "clean" cannot be
# mistaken for "complete".
from . import ds1, ds2, ds3, er, nightreign, sekiro

## @brief Game key to its rules module. Both DS1 releases share one module, as do both
#  DS2 releases: the arithmetic is the release-independent part.
MODULES = {
    "ptde": ds1,
    "dsr": ds1,
    "ds2vanilla": ds2,
    "ds2sotfs": ds2,
    "ds3": ds3,
    "er": er,
    "sdt": sekiro,
    "nr": nightreign,
}
