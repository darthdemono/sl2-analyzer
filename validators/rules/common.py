##
# @file common.py
# @brief The rules that are the same arithmetic in every Souls game.
#
# Each rule is a pure function of `(character, game_data)` and returns findings or None.
# None and [] mean the same thing to the runner; None is what a rule returns when it had
# nothing to work with (no stats on a Sekiro character, no table for the game) and [] is
# what it returns when it checked and found nothing, which is the distinction the caller
# does NOT need but a reader of the rule does.
#
# THE ONE RULE OF THIS FILE: a check only ships if it can name the contradiction. "This
# looks like a cheater" is not a finding. "Vigor 255, cap 99" is.
from ..models import IMPOSSIBLE, INCONSISTENT, Finding


##
# @brief Level against stat total — the identity every Souls game keeps in lockstep.
# @details `level = starting level + (sum of stats - sum of starting stats)`, so for each
# starting class the quantity `sum(stats) - level` is a constant K. A save is consistent
# when its K is one the game can produce.
#
# TESTED AS SET MEMBERSHIP EVEN WHERE THE SET HAS ONE ELEMENT, and where it does the
# message says so rather than listing a set of one. Measured over the local corpus:
# DS3 K=89 on all 89 characters, ER K=79 on all 182, DS2 K=53 on all 75, and DS1 has a
# genuine set — Warrior and Deprived both give 82, Sorcerer 79, Knight and Thief 81.
#
# WHY THE STARTING CLASS DOES NOT NARROW THE FIRING CONDITION, only the message. DS1 and
# DS2 store the class, so in principle the check could demand that class's own K. It does
# not, because a wrong row in a wiki-sourced class table would then invent a finding on a
# legitimate save, and this pass is worth nothing if it does that. Set membership is the
# claim the data actually supports.
def level_vs_stats(ch, gd):
    stats, level = ch.get("stats") or {}, ch.get("level")
    ks = (gd or {}).get("k_values") or []
    if not stats or level is None or not ks:
        return None
    total = sum(stats.values())
    if total - level in ks:
        return []
    row = (gd.get("classes") or {}).get(ch.get("klass"))
    if row:
        k = sum(row["stats"].values()) - row["level"]
        expected = f"level {total - k} for a stat total of {total} (a {ch['klass']})"
    elif len(ks) == 1:
        expected = f"level {total - ks[0]} for a stat total of {total}"
    else:
        levels = ", ".join(str(total - k) for k in ks)
        expected = f"level {levels} for a stat total of {total}, one per starting class"
    return [
        Finding(
            "level-vs-stats",
            INCONSISTENT,
            "Level vs stat total",
            expected,
            f"level {level}",
        )
    ]


## @brief Any attribute past the game's hard cap. One finding per stat, because the
#  reader wants to know WHICH, and a save with two edited stats is not one finding.
def stat_above_cap(ch, gd):
    stats, cap = ch.get("stats") or {}, (gd or {}).get("stat_cap")
    if not stats or cap is None:
        return None
    return [
        Finding(
            "stat-above-cap",
            IMPOSSIBLE,
            "Stat above cap",
            f"<= {cap}",
            f"{stat.lower()} {v}",
        )
        for stat, v in sorted(stats.items())
        if v > cap
    ]


##
# @brief Any attribute below the lowest value it can start at.
# @details Stats go DOWN legitimately — a Soul Vessel, Rosaria, Rennala — which is why
# the floor is the starting value and not "never decreases". A respec cannot take a stat
# below the class's own base, so the class's base is the floor where the save stores the
# class, and the minimum across all classes where it does not.
#
# The floor is deliberately the LOWEST plausible one when the class is unknown: too low
# only costs sensitivity, while too high invents findings on legitimate saves. DS2 ships
# no class rows at all for exactly that reason, so this rule returns None there.
def stat_below_floor(ch, gd):
    stats, floors = ch.get("stats") or {}, (gd or {}).get("floors") or {}
    if not stats or not floors:
        return None
    row = (gd.get("classes") or {}).get(ch.get("klass"))
    base = row["stats"] if row else floors
    where = f"a {ch['klass']}'s starting" if row else "the lowest starting"
    out = []
    for stat, v in sorted(stats.items()):
        floor = base.get(stat)
        if floor is not None and v < floor:
            out.append(
                Finding(
                    "stat-below-floor",
                    IMPOSSIBLE,
                    "Stat below its starting value",
                    f">= {floor} ({where} {stat.lower()})",
                    f"{stat.lower()} {v}",
                    "A respec lowers stats but never below the class base, so this is a "
                    "floor no legitimate character can be under.",
                )
            )
    return out


## @brief Souls, runes or soul memory past the currency cap.
def souls_above_cap(ch, gd):
    cap = (gd or {}).get("souls_cap")
    if cap is None:
        return None
    out = []
    for field, label in (("souls", "held"), ("soul_memory", "soul memory")):
        v = ch.get(field)
        if v is not None and v > cap:
            out.append(
                Finding(
                    "souls-above-cap",
                    IMPOSSIBLE,
                    "Currency above cap",
                    f"<= {cap:,}",
                    f"{label} {v:,}",
                )
            )
    return out
