"""Progress denominators: what each section's "of N" is, and which entries are
missing. Kept out of progress.py because naming the gap needs every game's own
tables, which would otherwise make the two import each other.
"""
from .progress import BOSS_SOUL_DB_DIR, DS3_CINDER_ITEM, DS3_LORDS, MANDATORY_BOSSES, load_boss_soul_map
from .ds1 import load_ds1_boss_flags
from .ds2 import DS2_COVENANT, DS2_GAMES, load_ds2_boss_souls, load_ds2_bosses
from .ds3 import DS3_COVENANT, load_ds3_boss_flags, load_ds3_boss_route, load_ds3_boss_victory, load_ds3_covenants


##
# @brief Every boss this tool can name for a game — the denominator behind
#        "Bosses Defeated (8 of 26)".
# @details Assembled from the game's own tables (defeat flags + boss-soul map), so it
# is what the tool TRACKS, not a claim about how many bosses the game ships. That
# distinction is the point: a name in here that is not in @c ch["bosses"] is a boss
# the save shows no evidence for, which is worth printing; a boss no table knows
# cannot be reported either way and must not inflate the denominator.
def boss_roster(game, base_dir):
    if game in DS2_GAMES:
        return (set(load_ds2_bosses(base_dir).values())
                | set(load_ds2_boss_souls(base_dir).values()))
    subdir = BOSS_SOUL_DB_DIR.get(game)
    names = set(load_boss_soul_map(base_dir, subdir).values()) if subdir else set()
    names |= set(MANDATORY_BOSSES.get(game, ()))
    if game == "ds3":
        names |= set(load_ds3_boss_flags(base_dir)) | set(load_ds3_boss_victory(base_dir))
    if game in ("dsr", "ptde"):
        names |= set(load_ds1_boss_flags(base_dir))
    return names


## @brief Every covenant a game has, as the denominator for "Covenants Found". These
#  are the in-game rosters (the id→name tables), so the count is the real total.
def covenant_roster(game, base_dir):
    if game in DS2_GAMES:
        return set(DS2_COVENANT.values())
    if game == "ds3":
        return set(DS3_COVENANT.values()) | set(load_ds3_covenants(base_dir))
    return set()


##
# @brief Attach the denominators the progress sections print against: how many bosses
#        and covenants the tool tracks, which of them this save shows nothing for, and
#        (DS3) how many Lords of Cinder are on the throne.
# @details The Lords count is ARITHMETIC on two reads that are already verified, not a
# new offset: a lord's cinders are in the inventory from the kill until they are
# offered, so @c placed = lords defeated − cinders still held. It matches the mapped
# throne flag on the one save that has one (the offering differential reads 1 defeated,
# 0 held, 1 placed; the before-save reads 1 defeated, 1 held, 0 placed). Skipped on
# NG+, where the thrones reset but the defeat flags do not, so the subtraction would
# over-report. @param base_dir Repo root holding the db_* folders.
def attach_progress_totals(ch, base_dir):
    game = ch.get("game")
    roster = boss_roster(game, base_dir)
    if roster and ch.get("bosses"):
        ch["boss_total"] = len(roster | set(ch["bosses"]))
        ch["bosses_missing"] = sorted(n for n in roster if n not in ch["bosses"])
    covs = covenant_roster(game, base_dir)
    if covs and ch.get("covenants"):
        ch["covenant_total"] = len(covs | set(ch["covenants"]))
        ch["covenants_missing"] = sorted(n for n in covs if n not in ch["covenants"])
    if game != "ds3":
        return
    ch_bosses = ch.get("bosses") or {}
    # Which of the missing bosses you could walk to RIGHT NOW: every hard predecessor
    # dead, and at least one bonfire lit in its gate area (so a DLC boss cannot be
    # "available" before you own/enter the DLC). Reached-area is the conservative half
    # — it under-reports the very next area rather than sending you somewhere you
    # cannot get to. Route structure only; nothing here is read from the save.
    reached = {a for a, c, _n, _t, _m in (ch.get("bonfire_areas") or []) if c}
    if reached:
        avail = [b for b, (area, after) in load_ds3_boss_route(base_dir).items()
                 if b not in ch_bosses and area in reached
                 and all(p in ch_bosses for p in after)]
        if avail:
            ch["bosses_available"] = avail
    dead = [lord for boss, lord in DS3_LORDS.items() if boss in ch_bosses]
    held = sum(q for n, q in (ch.get("key_items") or []) if n == DS3_CINDER_ITEM)
    named = ch.get("cinders") or []
    if dead or named:
        lords = {"total": len(DS3_LORDS), "named": named, "dead": len(dead), "held": held}
        # The subtraction only holds on a first journey; otherwise report just what the
        # mapped throne flags prove, and say the count is a floor.
        lords["placed"] = (max(len(dead) - held, len(named))
                           if (ch.get("ng_plus") or 0) == 0 else None)
        ch["lords"] = lords
