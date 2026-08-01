#!/usr/bin/env python3
##
# @file sl2_to_md.py
# @brief FromSoftware `.sl2` save to Markdown or JSON, for the whole Souls line:
#        Dark Souls (PtDE and Remastered), Dark Souls II (vanilla and SOTFS),
#        Dark Souls III, and Elden Ring.
#
# @details
# A Souls save is a locked box. This reads it and hands you back a description of the
# playthrough: one plain Markdown file to paste into an LLM that cannot read a `.sl2`
# but reads Markdown fine, or a JSON document against a published schema if something
# else is going to consume it. Per character it pulls whatever the game reliably
# exposes: name, class, level, attributes, souls, the full inventory with real item
# names, and a progress section built from event flags, boss souls and key items.
#
# It reads the save. It never writes to it. Point it at your live save if you want;
# the worst case is a bad output file, not a bricked character.
#
# **This file is the entry point, not the program.** The code lives in the `sl2`
# package, one module per layer and one per game — see `sl2/__init__.py` for the map.
# Everything the package exports is re-exported here, so `import sl2_to_md` still
# reaches the whole API and the existing harnesses keep working.
#
# ### Not every game is equal, and the output says so instead of guessing
# Six save variants share one archive format but diverge in the details, and not all
# of them are fully mapped in public tooling. Each game is handled at the highest tier
# it can be trusted at, and the output states the tier plainly. A tier is a promise:
# everything printed at any tier is read from the save, not inferred and not guessed.
# Stat offsets are calibrated for every supported game; DS3 and ER locate their stat
# block by content (the level == sum-of-attributes identity) and drop stats for a slot
# rather than print a wrong one if it fails to validate. Elden Ring is full identity
# and stats but a partial item list, which the output states where the list is.
#
# ### Reading defensively
# Every integer read goes through a bounds-checked helper that returns @c None rather
# than raising or reading past the end of a buffer, and the archive structure is
# validated before any offset is trusted. A malformed or truncated save degrades to
# "unknown" fields; it does not crash and it does not print garbage.
#
# @note Encryption keys and offsets come from the community: DS2 tables from
#       alfizari/Dark-Souls-2-Save-Editor-PS4-PC; DSR decryption from
#       jtesta/souls_givifier; DSR/DS1 tables and anchor offsets from
#       alfizari/Dark-Souls-Remastered-Save-Editor; DS3/ER keys and header layout
#       from jtesta/souls_givifier; DS2 key from mi5hmash/SL2Bonfire.
#
# @author Jubair Hasan (Joy) / DarthDemono
# @see https://github.com/darthdemono/sl2-analyzer
#
# Re-exported for anything that imports this module by name (the parity harnesses and
# the scratch tools do). The star imports are deliberate: this file's whole job is to
# be the flat surface the package used to have.
from sl2.reader import *          # noqa: F401,F403
from sl2.keys import *            # noqa: F401,F403
from sl2.bnd4 import *            # noqa: F401,F403
from sl2.crypto import *          # noqa: F401,F403
from sl2.detect import *          # noqa: F401,F403
from sl2.itemdb import *          # noqa: F401,F403
from sl2.progress import *        # noqa: F401,F403
from sl2.roster import *          # noqa: F401,F403
from sl2.ds1 import *             # noqa: F401,F403
from sl2.ds2 import *             # noqa: F401,F403
from sl2.ds3 import *             # noqa: F401,F403
from sl2.er import *              # noqa: F401,F403
from sl2.totals import *          # noqa: F401,F403
from sl2.render import *          # noqa: F401,F403
from sl2.convert import *         # noqa: F401,F403
from sl2.jsonout import *         # noqa: F401,F403
from sl2.cli import main

if __name__ == "__main__":
    main()
