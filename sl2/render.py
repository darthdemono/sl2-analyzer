"""Markdown rendering: one section per character, plus the shared tables.
"""
from collections import OrderedDict
from .ds1 import ds1_derived_stats
from .ds2 import DS2_FAMILY, DS2_GAMES, DS2_GREAT_SOULS, ds2_derived_stats
from .ds3 import ds3_derived_stats


## @brief Short attribute headers for the table.
STAT_ABBR = {"Vigor": "VGR", "Endurance": "END", "Vitality": "VIT",
             "Attunement": "ATN", "Strength": "STR", "Dexterity": "DEX",
             "Adaptability": "ADP", "Intelligence": "INT", "Faith": "FTH",
             "Resistance": "RES", "Luck": "LCK", "Mind": "MND", "Arcane": "ARC"}


## @brief What each attribute governs, per game. Static game-design fact — NOT read
#  from the save and never a copied stat value, so it is true for any build and can
#  never be the "wrong field" the core rule forbids. Keyed by game family because the
#  same attribute name means different things across games (DS1 Vitality is HP;
#  DS2/DS3 Vitality is equip load) — exactly the nuance the rule cares about. From the
#  games' own status screens / community wikis.
STAT_GOVERNS = {
    "ds1": OrderedDict([
        ("Vitality", "Max HP"),
        ("Attunement", "Attunement (spell) slots"),
        ("Endurance", "Stamina, equip load, physical defense"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, faster casting"),
        ("Resistance", "Poison/bleed resistance, fire defense"),
        ("Intelligence", "Magic attack, sorcery scaling"),
        ("Faith", "Miracle scaling, lightning & magic defense")]),
    "ds2sotfs": OrderedDict([
        ("Vigor", "Max HP"),
        ("Endurance", "Stamina"),
        ("Vitality", "Equip load, physical defense, petrify resistance"),
        ("Attunement", "Attunement (spell) slots, casting speed"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, casting speed"),
        ("Adaptability", "Agility (i-frames), poison/bleed/petrify resistance"),
        ("Intelligence", "Magic & dark attack, sorcery/hex scaling"),
        ("Faith", "Lightning & dark attack, miracle/hex scaling")]),
    "ds3": OrderedDict([
        ("Vigor", "Max HP"),
        ("Attunement", "FP, attunement (spell) slots"),
        ("Endurance", "Stamina"),
        ("Vitality", "Equip load, physical defense"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Physical attack, dex-weapon scaling, faster casting"),
        ("Intelligence", "Magic attack, sorcery & pyromancy scaling"),
        ("Faith", "Lightning & dark attack, miracle & pyromancy scaling"),
        ("Luck", "Item discovery, bleed/poison buildup, hollow-weapon scaling")]),
    "er": OrderedDict([
        ("Vigor", "Max HP, fire defense & immunity"),
        ("Mind", "FP (skill/spell points), focus resistance"),
        ("Endurance", "Stamina, equip load, robustness"),
        ("Strength", "Physical attack, strength-weapon scaling"),
        ("Dexterity", "Dex-weapon scaling, faster casting, less fall damage"),
        ("Intelligence", "Sorcery scaling, magic defense"),
        ("Faith", "Incantation scaling"),
        ("Arcane", "Item discovery, arcane-weapon scaling, death/holy resistance")]),
}


## @brief Map a per-slot game id to its STAT_GOVERNS family (DSR and PtDE share DS1).
def stat_governs_for(game):
    return STAT_GOVERNS.get(DS2_FAMILY.get(game, game), {})


## @brief Soft-cap / per-level breakpoint reference per attribute, per game. These are
#  the documented scaling RATES and soft-cap levels (a game-mechanics fact, true for any
#  build), NOT a per-character computed value — computing the absolute would be wrong
#  (DS2 Vigor 36 gives HP 1351 in-save vs 1420 from the flat table, because the real
#  curve carries base/class offsets the summaries drop). So the tool prints the rate
#  table and the character's own stat value, and never a derived absolute it cannot
#  verify. Sourced from the fextralife stat pages (DS1/DS2/DS3/ER), fetched per stat.
STAT_CAPS = {
    "ds1": OrderedDict([
        ("Vitality", "soft caps 30 (~1,100 HP) & 50 (~1,500 HP), rising to ~1,900 at 99"),
        ("Attunement", "1 slot at 10, then 12/14/16/19/23/28/34/41/50 — 10 slots max at 50"),
        ("Endurance", "stamina maxes at 40 (160); equip load keeps rising (~+1/lvl) to 99"),
        ("Strength", "scaling soft cap 40"),
        ("Dexterity", "scaling soft cap 40; cast speed improves to 45"),
        ("Resistance", "minor per-level gains — commonly a dump stat"),
        ("Intelligence", "scaling soft cap 40"),
        ("Faith", "scaling soft cap 40")]),
    "ds2sotfs": OrderedDict([
        ("Vigor", "soft caps 20 & 50; +30 HP/lvl to 20, +20 to 50, +5 after"),
        ("Endurance", "soft cap 20; +2 stamina/lvl to 20, +1 after"),
        ("Vitality", "soft caps 29/49/70; +1.5 load/lvl to 29, +1 to 49, +0.5 to 69, +0.25 after"),
        ("Attunement", "slots at 10/13/16/20/25/30/40/50/60/75/94; cast-speed breakpoints 30/45/60/80"),
        ("Strength", "scaling soft caps 40 & 50"),
        ("Dexterity", "scaling soft caps 40 & 50"),
        ("Adaptability", "raises Agility (with Attunement); gains taper past ~40"),
        ("Intelligence", "scaling soft caps 40 & 50"),
        ("Faith", "scaling soft caps 40 & 50")]),
    "ds3": OrderedDict([
        ("Vigor", "soft caps ~27 & 50; ~1,300 HP at 50, only ~100 more to 99"),
        ("Attunement", "FP soft cap 35 (450 max at 99); slots at 10/14/18/24/30/40/50/60/80/99"),
        ("Endurance", "stamina soft cap 40"),
        ("Vitality", "roughly linear to 99"),
        ("Strength", "scaling soft caps 40 & 60"),
        ("Dexterity", "scaling soft caps 40 & 60"),
        ("Intelligence", "scaling soft caps 40 & 60"),
        ("Faith", "scaling soft caps 40 & 60"),
        ("Luck", "+1 item discovery/pt (base 100); bleed/poison speed soft cap 50")]),
    "er": OrderedDict([
        ("Vigor", "soft caps 40 & 60"),
        ("Mind", "soft caps 50 & 60"),
        ("Endurance", "stamina soft caps 15/30/50; equip load 25/60"),
        ("Strength", "scaling soft caps 20/50/80"),
        ("Dexterity", "scaling soft caps 20/50/80"),
        ("Intelligence", "scaling soft caps 20/50/80"),
        ("Faith", "scaling soft caps 20/50/80"),
        ("Arcane", "scaling soft caps 20/50/80; also raises item discovery")]),
}


## @brief Soft-cap reference for a per-slot game id (DSR and PtDE share DS1).
def stat_caps_for(game):
    return STAT_CAPS.get(DS2_FAMILY.get(game, game), {})


## @brief Category id to printed heading (covers every id scheme / game).
CAT_TITLE = {"weapons": "Weapons", "armors": "Armor", "rings": "Rings",
             "talismans": "Talismans", "spells": "Spells", "bolts": "Ammunition",
             "upgrade": "Upgrade Materials", "consumables": "Consumables",
             "online": "Summon & Covenant Items", "goods": "Consumables & Goods",
             "ashes": "Ashes of War", "emotes": "Gestures",
             "bosssouls": "Boss Souls", "items": "Items Owned",
             # Sekiro's own six. Its storage box stands alone because an item in the
             # box is owned but not carried, and only a read that keeps them apart can
             # say which.
             "arts": "Combat Arts", "prosthetics": "Prosthetic Tools",
             "skills": "Skills & Techniques", "beads": "Prayer Beads & Gourd Seeds",
             "memories": "Memories & Remnants", "storage": "Storage (item box)"}


##
# @brief Per-game overrides for a category heading, where the shared name is wrong for
#        that game. @c "Armor" is wrong for Sekiro under any reading: the game has no
#        armour system, and the rows that survive the suppression filter are cosmetic
#        attire, so the heading says what they are.
CAT_TITLE_GAME = {"sdt": {"armors": "Attire"}}


def cat_title(game, cat):
    return CAT_TITLE_GAME.get(game, {}).get(cat, CAT_TITLE[cat])


## @brief Print order for inventory categories, mirroring the in-game item menu.
#  (`goods` is the lumped consumables bucket the non-DS2 games still use.)
CAT_ORDER = ["weapons", "arts", "prosthetics", "skills", "armors", "rings", "talismans",
             "spells", "bolts", "upgrade", "consumables", "beads", "goods", "ashes",
             "online", "bosssouls", "memories", "emotes", "items", "storage"]


##
# @brief Guess a build label from the attribute spread. A rough label, not gospel.
# @param stats The character's attribute dict.
# @return A short description, or None if there are no stats to judge.
def guess_build(stats):
    if not stats:
        return None
    g = lambda k: stats.get(k) or 0
    phys, cast = g("Strength") + g("Dexterity"), g("Intelligence") + g("Faith") + g("Attunement")
    if cast > phys:
        return "caster / hybrid (high INT/FTH/ATN)"
    if g("Strength") >= g("Dexterity") + 6:
        return "strength-focused melee"
    if g("Dexterity") >= g("Strength") + 6:
        return "dexterity-focused melee"
    return "quality / balanced melee"


## @brief What a game calls the money in your pocket. Souls unless it says otherwise.
CURRENCY = {"er": "Runes", "sdt": "Sen"}


##
# @brief Sekiro's Memory line: how many boss Memories have been spent, and what that
#        makes the kill count.
# @details Worth its own function because it is the one place in this tool where a
# CONSUMED progress token is still countable. Attack Power rises by exactly one per
# Memory consumed, so the arithmetic recovers what every other game's soul floor loses
# the moment the soul is spent. Both of its limits are printed, not buried: the count
# is a floor for bosses that drop no Memory at all, and past journey 0 it covers every
# lap rather than this one, because Attack Power carries over and the Memories do not.
# @param m The @c ch["memories"] dict from @ref sl2.sdt.sdt_parse.
def memories_line(m):
    total = m["spent"] + m["held"]
    lap = ("across every journey so far — Attack Power carries into New Game+ while "
           "the Memories do not" if m["cumulative"] else
           "this journey; a boss that drops no Memory is not counted either way")
    return (f"{total} Memory-dropping boss{'' if total == 1 else 'es'} defeated"
            f"  _({m['spent']} Memor{'y' if m['spent'] == 1 else 'ies'} already spent, "
            f"read back from Attack Power, plus {m['held']} still held — {lap})_")


##
# @brief What a Vitality figure says about Prayer Necklaces used.
# @details The Memory trick again, on Sekiro's other upgrade track: a necklace is
# consumed on use, so nothing in the inventory records that it was ever held, but
# Vitality rises by exactly one each time and a fresh character reads 1. So the
# subtraction recovers a spent token the item list cannot see. It carries into New
# Game+ the same way Attack Power does, which is why the count is never claimed to
# belong to this journey.
# @param vitality The stored Vitality. @return The parenthetical, without brackets.
def vitality_necklaces(vitality):
    used = vitality - 1
    return ("no Prayer Necklace used yet" if used == 0 else
            f"{used} Prayer Necklace{'' if used == 1 else 's'} used — four Prayer Beads "
            f"each, read back from Vitality across every journey so far")


## @brief Format a value, or "—" when it is unknown (None).
def fmt(value):
    return "—" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


## @brief Format a play-time count of seconds as H:MM:SS (hours can exceed 24).
def fmt_playtime(seconds):
    h, rem = divmod(seconds, 3600)
    mn, s = divmod(rem, 60)
    return f"{h}:{mn:02d}:{s:02d}"


##
# @brief Render one full/inventory-tier character as a Markdown section.
# @param ch      A unified character dict.
# @param slot_no The 1-based save-slot number.
# @return The Markdown for this character.
DS1_BONFIRE_NOTE = "each bonfire's own record, with how far it is kindled — a floor"


DS3_BONFIRE_NOTE = "bonfires lit, inferred from each area's flag bits — a floor"


# DS2 reads the world block's own discovered-bonfire array, so it names every one it
# found; the areas are a grouping of that list, not an inference.
DS2_BONFIRE_NOTE = "each bonfire the save records as discovered, by area — a floor"


# Sekiro's equivalent of a bonfire is a Sculptor's Idol, so it gets its own heading as
# well as its own note. It also RESETS on a new journey, which no other game's bonfire
# section has to say — DS1/DS2/DS3 all carry theirs across NG+.
SDT_BONFIRE_NOTE = ("each idol's own flag bit, by area — a floor, and one that starts "
                    "again on a new journey")


# Sekiro files a miniboss's defeat under its own ENTITY id, so unlike the Memory bosses
# these are exact rather than inferred. The names are enemy TYPES from the only published
# table that lists them, which is why four of them are "Shura Samurai" — those are four
# different enemies, not one printed four times.
# DS1's event-flag region carries far more than boss kills: the bells, the Lordvessel,
# every shortcut door and lever, the non-boss fog gates, NPC states and the covenant
# joined. Each is exact — a flag is set or it is not — but the SET is only what has been
# named, so the denominator is "tracked", not "in the game".
DS1_WORLD_NOTE = ("one-off world events, each read from its own flag — exact, but only "
                  "the flags that have been named are counted")


SDT_MINIBOSS_NOTE = ("each miniboss's own defeat flag — exact, not inferred, but it "
                     "resets on a new journey; names are enemy types, so repeats in an "
                     "area are different enemies")


# Only six areas have a derived flag-group base, so this counts what is TRACKED, not
# what the game ships. An area absent from the list is unmapped, not empty.
DS3_PICKUP_NOTE = ("one-off world items picked up, from each area's pickup flags — "
                   "covers only the areas whose flag group is mapped")


##
# @brief The Lords-of-Cinder line: how many of the four are on the throne, which ones
#        the mapped flags name, and the two counts the number came from.
# @param lords The @c ch["lords"] dict from @ref attach_progress_totals.
def lords_line(lords):
    # Mid-dot separated: "Aldrich, Devourer of Gods" has a comma of its own.
    named = f" — {' · '.join(lords['named'])}" if lords["named"] else ""
    if lords["placed"] is None:      # NG+: the thrones reset, the defeat flags do not
        return (f"{len(lords['named'])} of {lords['total']}{named}"
                "  _(NG+ — only the mapped throne flags are read, so this is a floor)_")
    return (f"{lords['placed']} of {lords['total']}{named}"
            f"  _({lords['dead']} of the four lords defeated, {lords['held']} set"
            f"{'' if lords['held'] == 1 else 's'} of cinders still held)_")


##
# @brief Render "N of M" plus the names still missing, for a progress section.
# @param missing The names with no evidence. Long lists stay one italic line so the
#        section keeps its shape.
def missing_note(label, missing):
    return f"_{label}: {' · '.join(missing)}._" if missing else None


##
# @brief Collapse repeats in a name list to @c "name ×N", keeping first-seen order.
# @details An area holds seven separate mimics and a dozen Titanite Shards, each with
# its own flag. Printing the name seven times is faithful but unreadable; the count
# says the same thing. @param names The list. @return The collapsed list.
def count_dupes(names):
    seen = OrderedDict()
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    return [n if c == 1 else f"{n} ×{c}" for n, c in seen.items()]


def md_for_character(ch, slot_no):
    L = [f"## Slot {slot_no}: {ch['name']}", ""]
    if ch["level"] is not None:
        L.append(f"- **{'Level' if ch['game'] == 'er' else 'Soul Level'}:** {ch['level']}")
    if ch["klass"]:
        L.append(f"- **Class:** {ch['klass']}")
    if ch.get("covenant"):
        L.append(f"- **Covenant:** {ch['covenant']}")
    if ch.get("gender"):
        L.append(f"- **Gender:** {ch['gender']}")
    if ch["ng_plus"] is not None:
        ng = "New Game" if ch["ng_plus"] == 0 else f"New Game +{ch['ng_plus']}"
        L.append(f"- **Playthrough:** {ng}")
    if ch["soul_memory"] is not None:
        L.append(f"- **Soul Memory:** {fmt(ch['soul_memory'])}  _(total souls earned — main progress metric)_")
    if ch.get("play_time"):
        L.append(f"- **Play Time:** {fmt_playtime(ch['play_time'])}")
    if ch["souls"] is not None:
        L.append(f"- **{CURRENCY.get(ch['game'], 'Souls')} held:** {fmt(ch['souls'])}")
    if ch.get("attack") is not None:
        L.append(f"- **Attack Power:** {ch['attack']}")
    if ch.get("vitality") is not None:
        L.append(f"- **Vitality:** {ch['vitality']}  _({vitality_necklaces(ch['vitality'])})_")
    if ch.get("skill_points") is not None:
        L.append(f"- **Skill Points Held:** {ch['skill_points']}"
                 "  _(spendable at a Sculptor's Idol — the points already spent are "
                 "not stored, so this is what is banked, not what has been earned)_")
    if ch.get("memories"):
        L.append(f"- **Memories:** {memories_line(ch['memories'])}")
    if ch["humanity"] is not None:
        L.append(f"- **Humanity:** {ch['humanity']}")
    if ch["hp"] is not None:
        L.append(f"- **Max HP:** {fmt(ch['hp'])}")
    if ch.get("posture") is not None:
        L.append(f"- **Max Posture:** {fmt(ch['posture'])}")
    if ch.get("embered") is not None:
        L.append("- **Embered:** Yes  _(Max HP above includes the +30% ember bonus)_"
                 if ch["embered"] else
                 "- **Embered:** No  _(hollow — Max HP above is the base value)_")
    if ch.get("fp") is not None:
        L.append(f"- **Max FP:** {fmt(ch['fp'])}")
    if ch.get("hollow_lvl"):
        L.append(f"- **Hollowing:** {ch['hollow_lvl']}  _(higher = more deaths without an effigy)_")
    if ch.get("deaths") is not None:
        L.append(f"- **Deaths:** {fmt(ch['deaths'])}")
    if ch["stamina"] is not None:
        L.append(f"- **Stamina:** {fmt(ch['stamina'])}")
    if ch.get("lords"):
        L.append(f"- **Cinders of a Lord Placed:** {lords_line(ch['lords'])}")
    if ch.get("endings"):
        ends = ch["endings"]
        L.append(f"- **Ending{'' if len(ends) == 1 else 's'} Reached:** "
                 + " · ".join(ends))
    build = guess_build(ch["stats"])
    if build:
        L.append(f"- **Build:** {build}")
    L.append("")

    if ch["stats"]:
        keys = list(ch["stats"].keys())
        L += ["### Attributes", "",
              "| " + " | ".join(STAT_ABBR.get(k, k[:3].upper()) for k in keys) + " |",
              "|" + "----|" * len(keys),
              "| " + " | ".join(str(ch["stats"][k]) for k in keys) + " |", ""]
        gov = stat_governs_for(ch["game"])
        cap = stat_caps_for(ch["game"])
        rows = [k for k in keys if k in gov]
        if rows:
            # Fixed game-mechanics reference, identical in every export bar the
            # current values — folded away so it does not sit between the save's own
            # numbers and its progress (and so two exports diff cleanly).
            L += ["<details>", "<summary><b>Attribute Scaling</b> — what each stat "
                  "scales and its soft caps (game-mechanics reference, not read from "
                  "this save)</summary>", ""]
            for k in rows:
                caps = f" {cap[k][:1].upper() + cap[k][1:]}." if cap.get(k) else ""
                L.append(f"- **{k}** ({ch['stats'][k]}) — {gov[k]}.{caps}")
            L += ["", "</details>", ""]
        if ch["game"] in DS2_GAMES:
            d = ds2_derived_stats(ch["stats"])
            agl = f"{d['agility']}" + (f"  _({d['iframes']} roll i-frames)_"
                                       if d["iframes"] else "")
            L += ["### Derived Stats  _(computed from attributes — base values before "
                  "rings & equipment; the in-game screen adds ring/gear bonuses on top)_",
                  "",
                  f"- **Stamina:** {d['stamina']}",
                  f"- **Equip Load (max capacity):** {d['equip_load']:.1f}",
                  f"- **Attunement Slots:** {d['slots']}",
                  f"- **Agility (AGL):** {agl}",
                  f"- **Poise (base):** {d['poise']:.1f}",
                  f"- **ATK: Str:** {d['atk_str']}",
                  f"- **ATK: Dex:** {d['atk_dex']}",
                  f"- **Magic DEF:** {d['magic_def']}",
                  f"- **Fire DEF:** {d['fire_def']}",
                  f"- **Lightning DEF:** {d['lightning_def']}",
                  f"- **Dark DEF:** {d['dark_def']}", ""]
        if ch["game"] == "ds3":
            d = ds3_derived_stats(ch["stats"], ch.get("ring_mods"))
            w = d["ring_bonus"]

            # "73.0 base, +5% Ring of Favor, +15% Havel's Ring" -- the sum is only as
            # good as its parts, so the parts are printed beside it.
            def credit(base, kind, unit):
                if not w[kind]:
                    return ""
                parts = ", ".join(f"+{v:g}{unit} {n}" for n, v in w[kind])
                return f"  _({base} base, {parts})_"

            L += ["### Derived Stats  _(computed from attributes, plus the documented "
                  "bonus of any worn ring named beside the value — the game's other "
                  "gear is not read)_", "",
                  f"- **Attunement Slots:** {d['slots']}"
                  + credit(d["slots_base"], "slots", ""),
                  f"- **Equip Load (max capacity):** {d['equip_load']:.1f}"
                  + credit(f"{d['equip_load_base']:.1f}", "load_pct", "%"),
                  f"- **Item Discovery:** {d['item_discovery']}"
                  + credit(d["item_discovery_base"], "discovery", "")]
            # HP and stamina are read fields, so a ring that boosts them is already in
            # the numbers above -- say so rather than adding it a second time.
            already = [f"+{v:g}% {'Max HP' if k == 'hp_pct' else 'Stamina'} ({n})"
                       for k in ("hp_pct", "stam_pct") for n, v in w[k]]
            if already:
                L.append(f"- **Also from rings:** {', '.join(already)}  _(Max HP and "
                         f"Stamina are read from the save, so they already include "
                         f"these)_")
            L.append("")
        if ch["game"] in ("dsr", "ptde"):
            d = ds1_derived_stats(ch["stats"])
            L += ["### Derived Stats  _(computed from attributes — base values before "
                  "rings & equipment)_", "",
                  f"- **Attunement Slots:** {d['slots']}",
                  f"- **Equip Load (max capacity):** {d['equip_load']:.1f}", ""]
    elif ch["tier"] == "inventory":
        L += ["_Attributes are not printed for this slot: its stat block did not "
              "validate (an unrecognised patch or an edited save), and a wrong "
              "number is worse than none. Inventory and progress below are read "
              "directly._", ""]

    def bullets(items):
        return [f"- {n}" + (f" ×{q}" if q and q > 1 else "") for n, q in items]

    # Boss souls / remembrances that live in their own top section (every game but
    # DS2, whose boss souls are a proper inventory category — see below).
    # Boss souls get a top section only where the inventory does NOT already have a
    # category holding them (DS2 and DS3 have `bosssouls`, Sekiro has `memories`) —
    # printing both is the same list twice.
    if ch["boss_souls"] and not (ch["inv"].get("bosssouls") or ch["inv"].get("memories")):
        header = ("### Remembrances Held  _(major bosses defeated, not yet traded)_"
                  if ch["game"] == "er"
                  else "### Boss Souls Held  _(bosses defeated, soul not yet consumed)_")
        L += [header, ""] + bullets(ch["boss_souls"]) + [""]
    if ch["key_items"]:
        L += ["### Key Items  _(progress / areas & shortcuts unlocked)_", ""]
        L += bullets(ch["key_items"]) + [""]
    # DS2 keeps a flat name list for the boss-gate logic, but renders the grouped
    # view when the area table resolved it; the flat list is the fallback.
    if ch.get("bonfires") and not ch.get("bonfire_areas"):
        L += [f"### Bonfires Discovered ({len(ch['bonfires'])})  _(areas reached — a "
              "floor on progress)_", ""]
        L += [f"- {b}" for b in ch["bonfires"]] + [""]
    if ch.get("bonfire_areas"):
        lit = sum(c for _a, c, _n, _t, _m in ch["bonfire_areas"])
        total = sum(t for _a, _c, _n, t, _m in ch["bonfire_areas"])
        n = sum(1 for _a, c, _n, _t, _m in ch["bonfire_areas"] if c)
        areas = len(ch["bonfire_areas"])
        # DS1 reads the real bonfire list (so it can say kindle level, and can list a
        # discovered-but-unlit one); DS3 only has flag bits per area. Different note.
        note = (DS1_BONFIRE_NOTE if ch.get("game") in ("dsr", "ptde")
                else DS2_BONFIRE_NOTE if ch.get("game") in DS2_GAMES
                else SDT_BONFIRE_NOTE if ch.get("game") == "sdt"
                else DS3_BONFIRE_NOTE)
        # Sekiro has no bonfires; calling its idols one would be the same kind of wrong
        # as printing a soul level for a game that has none.
        head = "Sculptor's Idols Lit" if ch.get("game") == "sdt" else "Bonfires Discovered"
        L += [f"### {head} ({lit} of {total}, in {n} of {areas} areas)"
              f"  _({note})_", ""]
        for name, c, named, tot, missing in ch["bonfire_areas"]:
            row = f"- {name}: {c}/{tot}"
            if named:
                row += f" — {', '.join(named)}"
                # Only a STARTED area lists what is left; an untouched area would just
                # print the whole game back at you.
                if missing:
                    row += f"  _(missing: {' · '.join(missing)})_"
            L.append(row)
        L.append("")
    if ch.get("covenants"):
        found, total = len(ch["covenants"]), ch.get("covenant_total")
        count = f"{found} of {total}" if total else f"{found}"
        L += [f"### Covenants Found ({count})  _(discovered — a floor; "
              "the one currently worn is the Covenant field above)_", ""]
        L += [f"- **{cov}:** {', '.join(w)}" for cov, w in ch["covenants"].items()] + [""]
        note = missing_note("Not found yet", ch.get("covenants_missing"))
        if note:
            L += [note, ""]
    if ch.get("world_flags"):
        got = sum(c for _a, c, _n, _t, _m in ch["world_flags"])
        total = sum(t for _a, _c, _n, t, _m in ch["world_flags"])
        L += [f"### World State ({got} of {total} tracked)  _({DS1_WORLD_NOTE})_", ""]
        for cat, c, names, tot, missing in ch["world_flags"]:
            row = f"- {cat}: {c}/{tot}"
            # Mid-dot, not comma: half these names contain a comma of their own
            # ("Sen's Fortress, Fog Gate 1"), so a comma-joined list is unreadable.
            if names:
                row += f" — {' · '.join(names)}"
                if missing:
                    row += f"  _(not yet: {' · '.join(missing)})_"
            L.append(row)
        L.append("")
    if ch.get("minibosses"):
        dead = sum(c for _a, c, _t, _m in ch["minibosses"])
        total = sum(t for _a, _c, t, _m in ch["minibosses"])
        L += [f"### Minibosses Defeated ({dead} of {total} tracked)  _({SDT_MINIBOSS_NOTE})_",
              ""]
        for area, c, tot, alive in ch["minibosses"]:
            row = f"- {area}: {c}/{tot}"
            # Same rule as every other progress section: an area you have started says
            # what is left in it, an untouched one would print a walkthrough back.
            if c and alive:
                row += f"  _(still alive: {' · '.join(count_dupes(alive))})_"
            L.append(row)
        L.append("")
    if ch.get("pickups"):
        got = sum(c for _a, c, _t, _m in ch["pickups"])
        total = sum(t for _a, _c, t, _m in ch["pickups"])
        L += [f"### Items Collected ({got} of {total} tracked)  _({DS3_PICKUP_NOTE})_", ""]
        for area, c, tot, missing in ch["pickups"]:
            row = f"- {area}: {c}/{tot}"
            # Same rule as bonfires — an area you have started counts what is left in
            # it; an untouched one would print a walkthrough back at you.
            if c and missing:
                row += f"  _({len(missing)} still out there)_"
            L.append(row)
        L.append("")
        # The list itself is folded away. It carries a location per item, which makes
        # it a to-do list rather than a tally — and also long enough to bury the
        # numbers above it if it were printed inline.
        todo = [(area, missing) for area, c, _t, missing in ch["pickups"] if c and missing]
        if todo:
            L += ["<details>",
                  "<summary>Where the missing items are — the ones with a known "
                  "location</summary>", ""]
            for area, missing in todo:
                L.append(f"**{area}** — {len(missing)} missing")
                L.append("")
                L += [f"- {item}" for item in count_dupes(missing)]
                L.append("")
            L += ["</details>", ""]
    if ch.get("questlines"):
        # Not all of these are NPCs — the same reward flags cover a few landmark
        # pickups and enemy drops, so the heading says rewards, not questlines.
        L += ["### Rewards Obtained  _(one-off rewards from NPCs, invaders and "
              "landmark pickups — a progress floor)_", ""]
        L += [f"- **{src}:** {', '.join(rw)}" for src, rw in ch["questlines"].items()] + [""]
    if ch.get("bosses"):
        SRC = {"flag": "confirmed", "soul": "soul held", "gate": "progression", "clear": "cleared (NG+)"}
        found, total = len(ch["bosses"]), ch.get("boss_total")
        count = f"{found} of {total} tracked" if total else f"{found}"
        L += [f"### Bosses Defeated ({count})  _(a floor — from defeat "
              "flags, held boss souls, progression, and NG+ clears; a boss whose soul "
              "was consumed and isn't gated may still be missing)_", ""]
        for boss, srcs in ch["bosses"].items():
            L.append(f"- {boss}  _({', '.join(SRC[s] for s in srcs)})_")
        L.append("")
        # The missing list splits in two where a route graph exists: what is open to
        # you now, and what is still behind something. The split is game structure,
        # not a save read — the note says so.
        avail = ch.get("bosses_available") or []
        rest = [b for b in (ch.get("bosses_missing") or []) if b not in avail]
        if avail:
            L += [f"_Available now — every prerequisite dead and the area already "
                  f"reached (from the game's fixed route, not this save): "
                  f"{' · '.join(avail)}._", ""]
        note = missing_note("No evidence yet" + (", and behind something else" if avail
                            else ""), rest)
        if note:
            L += [note, ""]

    if ch.get("equipped_weapons") or ch.get("equipped_armor") or \
            ch.get("equipped_rings") or ch.get("equipped_ammo"):
        L += ["### Equipped  _(worn gear read from the equip slots)_", ""]
        L += [f"- **{slot}:** {name}" for slot, name in ch.get("equipped_weapons", {}).items()]
        L += [f"- **{slot}:** {name}" for slot, name in ch.get("equipped_armor", {}).items()]
        if ch.get("equipped_rings"):
            # With the effect table loaded each ring gets its own line and what it
            # does; without it (or for a ring the table doesn't cover) the old
            # one-line list is still the fallback, so nothing is lost.
            eff = dict(ch.get("ring_effects") or [])
            if eff:
                L.append("- **Rings:**")
                L += [f"    - {n}" + (f" — {eff[n]}" if n in eff else "")
                      for n in ch["equipped_rings"]]
            else:
                L.append(f"- **Rings:** {', '.join(ch['equipped_rings'])}")
        if ch.get("equipped_ammo"):
            L.append(f"- **Ammo:** {', '.join(ch['equipped_ammo'])}")
        L.append("")

    L += ["### Inventory", ""]
    # DS1 and ER keep boss souls and key items inside the flat `goods` bucket, which
    # already has its own section above — list each item once and point at it.
    listed = {n for n, _q in ch["boss_souls"]} | {n for n, _q in ch["key_items"]}
    for cat in CAT_ORDER:
        items = ch["inv"].get(cat)
        if not items:
            continue
        if cat == "goods" and listed:
            items = [it for it in items if it[0] not in listed]
            if not items:
                continue
        # Boss souls split into the game's own two grades: the four "Old" great
        # souls, then the ordinary boss souls. Everything else is one heading.
        if cat == "bosssouls":
            great = [it for it in items if it[0] in DS2_GREAT_SOULS]
            normal = [it for it in items if it[0] not in DS2_GREAT_SOULS]
            for title, group in (("Great Boss Souls", great), ("Boss Souls", normal)):
                if group:
                    L += [f"#### {title}", ""] + bullets(group) + [""]
        else:
            title = cat_title(ch["game"], cat)
            if cat == "goods" and listed:
                title += "  _(boss souls and key items are listed above)_"
            L += [f"#### {title}", ""] + bullets(items) + [""]
    if ch["unknown_count"]:
        L += [f"_{ch['unknown_count']} inventory item(s) had IDs not in the name "
              "database (upgraded / infused variants) and were omitted._", ""]
    if ch.get("internal_count"):
        L += [f"_{ch['internal_count']} further entr"
              f"{'y' if ch['internal_count'] == 1 else 'ies'} carried only an engine "
              "development name — placeholder rows and debug items rather than "
              "anything the game hands you — and were left out._", ""]
    if ch.get("suppressed_count"):
        L += [f"_{ch['suppressed_count']} further entr"
              f"{'y' if ch['suppressed_count'] == 1 else 'ies'} were engine state "
              "rather than inventory — Sekiro has no armour system, so the character's "
              "own body models sit in the protector table, and the `Virtual Weapon:` "
              "rows restate a Combat Art already listed under its own name. Counted "
              "here, not printed._", ""]
    return "\n".join(L)
