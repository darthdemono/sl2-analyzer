##
# @file validators/__init__.py
# @brief A second pass over an ALREADY-PARSED character that reports what could not have
#        come out of an unmodified game.
#
# WHAT THIS IS NOT. It is not a cheat detector, it does not score a save, and it never
# says "modded". It reports contradictions: a stat above the game's cap, a level that
# does not match its own stat total, a currency past its ceiling. Every finding names
# what the game would have to produce and what the file actually holds, and the reader
# decides what that means. Intent is not in the file, so it is not in the output.
#
# WHY IT IS A SEPARATE PASS. The parsers never see it. They read a save into a plain
# dict and stop; this reads that dict. Nothing here can change what is reported about a
# save, and a rule that is wrong costs a wrong finding, never a wrong stat.
#
# OFF BY DEFAULT, both front ends. `--validate` on the CLI, a toggle in the web app.
#
# THE ACCEPTANCE CRITERION, which is the reason to trust any of it: every one of the 264
# saves on this machine — 89 DS3 characters, 75 DS2, 40 Sekiro, 182 Elden Ring, three
# DS1 — produces zero `impossible` and zero `inconsistent` findings. A rule that fires
# on a save known to be legitimate is a wrong rule, not a caught save.
from .data import game_data
from .models import IMPOSSIBLE, INCONSISTENT, SUSPICIOUS, TIER_ORDER, Finding, Report
from .rules import MODULES

__all__ = [
    "run_validation",
    "Finding",
    "Report",
    "IMPOSSIBLE",
    "INCONSISTENT",
    "SUSPICIOUS",
    "TIER_ORDER",
    "game_data",
]


##
# @brief Run every rule registered for a game against one parsed character.
# @details Findings come back worst tier first and, within a tier, in the order the
# rules ran, so the output is stable enough to diff between two saves.
#
# A rule returning None means "no data to check" and a rule returning [] means "checked,
# nothing wrong"; both count as run, because the reader is being told how many checks the
# save survived, not how many had material to work with.
# @param ch       A parsed character dict.
# @param game     The game key ("ds3", "dsr", ...).
# @param base_dir Repo root, for db_<game>/classes.json. Defaults to the repo the
#                 package sits in, so neither writer has to thread a path through.
# @return A @ref Report.
def run_validation(ch, game, base_dir=None):
    module = MODULES.get(game)
    if module is None:
        return Report(game, [], 0, ["no rules module for this game key"])
    gd = game_data(game, base_dir)
    findings = []
    for rule in module.RULES:
        out = rule(ch, gd)
        if out:
            findings.extend(out)
    findings.sort(key=lambda f: TIER_ORDER.index(f.tier))
    return Report(game, findings, len(module.RULES), list(module.UNIMPLEMENTED))
