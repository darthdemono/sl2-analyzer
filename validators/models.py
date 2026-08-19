##
# @file models.py
# @brief What a validation rule is allowed to say.
#
# One finding is one contradiction, stated as a pair the reader can check: what the game
# would have to produce, and what the file actually holds. There is deliberately no
# score, no verdict and no "probability" — those would all be this module claiming to
# know intent, which it cannot read. See validators/__init__.py for why.
from dataclasses import dataclass, field

## @brief The game cannot produce this state at all. A stat past its hard cap, a
#  quantity past its stack cap, an upgrade past a weapon's own maximum.
IMPOSSIBLE = "impossible"
## @brief Internally contradictory: two fields the game keeps in lockstep disagree.
#  The level-versus-stat-total identity is the whole reason this tier exists.
INCONSISTENT = "inconsistent"
## @brief Odd but reachable. Every rule at this tier MUST carry a note naming the
#  legitimate cause, because the legitimate cause is common — see rule 5.
SUSPICIOUS = "suspicious"

## @brief Severity order, worst first. Used for sorting output, nothing else.
TIER_ORDER = (IMPOSSIBLE, INCONSISTENT, SUSPICIOUS)


##
# @brief One thing that does not add up.
# @details `expected` and `found` are the finding: both are short strings, both name
# concrete numbers, and a reader who disagrees can check them against the save without
# reading this code. `note` is for a rule whose false positives have a known cause —
# multiplayer item transfer, a respec, a save moved between accounts — and it is
# REQUIRED at the suspicious tier.
@dataclass
class Finding:
    rule_id: str
    tier: str
    title: str
    expected: str
    found: str
    note: str = ""

    def as_dict(self):
        d = {
            "rule_id": self.rule_id,
            "tier": self.tier,
            "title": self.title,
            "expected": self.expected,
            "found": self.found,
        }
        if self.note:
            d["note"] = self.note
        return d


##
# @brief The result of one validation pass: what fired, what ran, what does not exist.
# @details `unimplemented` is not a footnote, it is half the answer. A save that trips
# nothing has not been "cleared" — it has been checked against however many rules this
# game happens to have, and the reader is entitled to know which checks were never made.
@dataclass
class Report:
    game: str
    findings: list = field(default_factory=list)
    rules_run: int = 0
    unimplemented: list = field(default_factory=list)

    ## @brief True where the game has no rules at all (Nightreign today).
    @property
    def no_rules(self):
        return self.rules_run == 0

    def as_dict(self):
        return {
            "game": self.game,
            "rules_run": self.rules_run,
            "unimplemented": list(self.unimplemented),
            "findings": [f.as_dict() for f in self.findings],
        }
