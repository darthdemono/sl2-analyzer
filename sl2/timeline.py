"""Turn a pile of saves into runs, and each run into a tree of snapshots.

A folder of backups is not a list. Backups sorted by time LOOK linear, but reloading
an earlier save and playing on forks the run — the four Dark Souls III endings are
exactly that, one pre-ending save finished four different ways. This module works out
which snapshot descends from which, using the one thing every game in the series
guarantees: event flags never clear. If a save has a bonfire lit, every save after it
on the same line has that bonfire lit too, so a snapshot's parent is the latest
earlier one whose progress it still entirely contains — a sibling branch holds a flag
this one lacks, fails that test, and both land on the shared ancestor.

Nothing here renders. It reads parsed characters and returns data; sl2.chart draws it
and sl2.combine writes the document, so the inference can be tested without a document
and the document can change without touching the inference.
"""
import os
import re
from collections import OrderedDict

##
# @brief The Estus Flask's reinforcement level, or None if this character holds none.
# @details Not a stored field. DS3 keeps the flask's level IN its goods id (two ids per
# level), so the parser resolves it to a name and the level rides in that name. Undead
# Bone Shards are the only thing that moves it, which is why it earns a timeline row.
# A @c +0 flask has no suffix, hence the optional group.
ESTUS_RE = re.compile(r"^Estus Flask(?: \+(\d+))?$")


def estus_level(ch):
    for name, _qty in (ch.get("inv") or {}).get("consumables", []):
        mt = ESTUS_RE.match(name)
        if mt:
            return int(mt.group(1) or 0)
    return None


##
# @brief Flatten one parsed character into the fields a timeline needs.
# @details Bonfires are kept as (area, name) pairs so two areas sharing a bonfire name
# cannot collide in a first-seen set, and so every part of the document prints them the
# same way. Games that do not have a field simply do not get it — a DS1 character has
# no pickups and an Elden Ring one has no bonfires, and both are fine here.
# @param ch      A parsed character dict.
# @param path    The file it came from.
# @param slot_no Its 1-based slot number.
# @param game    The game id, @param title that game's display name.
# @return A snapshot dict.
def snapshot(ch, path, slot_no, game, title):
    areas = ch.get("bonfire_areas") or []
    bonfires = [(a, n) for a, _c, names, _t, _m in areas for n in names]
    if not bonfires and ch.get("bonfires"):
        bonfires = [(None, n) for n in ch["bonfires"]]
    st = os.stat(path)
    return {
        "path": path,
        "file": os.path.basename(path),
        "mtime": int(st.st_mtime),
        "size": st.st_size,
        "game": game,
        "title": title,
        "slot": slot_no,
        "name": ch.get("name") or "?",
        "tier": ch.get("tier"),
        "play_time": ch.get("play_time") or 0,
        "level": ch.get("level") or 0,
        "souls": ch.get("souls") or 0,
        "soul_memory": ch.get("soul_memory"),
        "deaths": ch.get("deaths"),
        "hollow_lvl": ch.get("hollow_lvl"),
        "embered": ch.get("embered"),
        "covenant": ch.get("covenant"),
        "ng_plus": ch.get("ng_plus"),
        "estus": estus_level(ch),
        "bonfires": bonfires,
        "bosses": {b: list(ev) for b, ev in (ch.get("bosses") or {}).items()},
        "covenants": {c: list(v) for c, v in (ch.get("covenants") or {}).items()},
        "questlines": {q: list(v) for q, v in (ch.get("questlines") or {}).items()},
        "pickups": {a: c for a, c, _t, _m in (ch.get("pickups") or [])},
        "pickup_total": sum(t for _a, _c, t, _m in (ch.get("pickups") or [])),
        "endings": list(ch.get("endings") or []),
        "cinders": list(ch.get("cinders") or []),
        "boss_total": ch.get("boss_total"),
    }


##
# @brief Group snapshots into RUNS — one per character, across every file that holds it.
# @details The key is (game, character name, slot), not the file: a run is spread over
# dozens of backups, and one backup can hold several characters. The slot is in the key
# because an all-characters mule really does hold ten slots called the same thing, and
# merging those into one run would invent a history none of them had. A character that
# was moved to a different slot splits instead, which is the rarer mistake.
#
# Ordering inside a run is by PLAY TIME, the game's own clock, falling back to the file
# date where a game does not store it (Elden Ring). That matters: file dates reorder
# when saves are copied around, play time does not.
# @return OrderedDict {(game, name): [snapshot, ...]}, runs ordered by first appearance.
def group_runs(snaps):
    runs = OrderedDict()
    for s in snaps:
        runs.setdefault((s["game"], s["name"], s["slot"]), []).append(s)
    for key in runs:
        runs[key].sort(key=lambda s: (s["play_time"], s["mtime"], s["file"], s["slot"]))
    return OrderedDict(sorted(runs.items(), key=lambda kv: min(s["mtime"] for s in kv[1])))


## @brief Boss kills that came from a FLAG, which is the only boss evidence that
#  cannot go backwards. A boss known by its held soul disappears the moment the soul is
#  consumed, and one inferred through a progression gate goes with it, so counting
#  those as progress would fork the tree at every boss-soul spend.
def flag_bosses(s):
    return {b for b, ev in s["bosses"].items() if "flag" in ev or "clear" in ev}


##
# @brief The monotone progress a snapshot holds — the things that only ever grow.
# @details This is the whole basis for reconstructing lineage, so it contains only
# one-way signals. Souls are spent, a covenant is switched, embered is consumed and
# hollowing goes down with an effigy: any one of those would fork the tree on every
# death. Level, Estus and the flag-backed sets only ever climb.
def progress(s):
    return {
        "bonfires": {tuple(b) for b in s["bonfires"]},
        "bosses": flag_bosses(s),
        "endings": set(s["endings"]),
        "cinders": set(s["cinders"]),
        "covenants": set(s["covenants"]),
        "pickups": s["pickups"],
        "level": s["level"],
        "estus": s["estus"] if s["estus"] is not None else -1,
        "ng_plus": s["ng_plus"] if s["ng_plus"] is not None else -1,
    }


## @brief Progress that a New Game+ lap wipes — the per-map flags. Bonfires go out,
#  world pickups reset, the thrones empty, and the per-map boss flags clear (the
#  cumulative victory flags do not, but a merged boss set cannot tell the two apart, so
#  the whole set is treated as resettable rather than risk a false fork).
RESETTABLE = ("bonfires", "bosses", "cinders", "covenants")


##
# @brief Could @p b be a continuation of @p a — is everything a had still in b?
# @details New Game+ is the one place a real continuation LOSES progress, so a journey
# bump waives the flags a lap resets. Endings are NOT waived: they accumulate across
# journeys, which is exactly what makes them the thing that separates two saves finished
# different ways from the same parent. Level and Estus never reset either.
def descends(a, b):
    pa, pb = progress(a), progress(b)
    if pa["ng_plus"] > pb["ng_plus"]:
        return False
    if not pa["endings"] <= pb["endings"]:
        return False
    if pa["level"] > pb["level"] or pa["estus"] > pb["estus"]:
        return False
    if pb["ng_plus"] > pa["ng_plus"]:
        return True
    for k in RESETTABLE:
        if not pa[k] <= pb[k]:
            return False
    return all(n <= pb["pickups"].get(area, 0) for area, n in pa["pickups"].items())


##
# @brief Work out each snapshot's parent, turning a run into a forest.
# @details A snapshot's parent is the LATEST earlier one it still contains, so a
# sibling branch is skipped over and both forks land on the shared ancestor.
#
# When NOTHING earlier qualifies, the snapshot becomes a root of its own rather than
# being hung off whatever happened to precede it. That case is real and it is not an
# error: two characters with the same name in the same slot look like one run here, and
# a save that lost progress cannot be a continuation of anything before it. Drawing it
# as a second tree says "these are not the same line", which is what the data says; an
# edge would claim a descent that the flags refute.
# @param rows Snapshots of one run, in order.
# @return (parent index or None per row, indices of roots after the first).
def build_tree(rows):
    parents, restarts = [], set()
    for i, r in enumerate(rows):
        best = None
        for j in range(i - 1, -1, -1):
            if descends(rows[j], r):
                best = j
                break
        if best is None and i > 0:
            restarts.add(i)
        parents.append(best)
    return parents, restarts


##
# @brief Carry every boss kill forward down each line of descent.
# @details A single save is a floor and it can only fall: the held-soul evidence that
# proves a kill DISAPPEARS the moment the soul is spent, so a later save reports fewer
# bosses than an earlier one on the same run. That is honest for one file — the save
# genuinely no longer proves it — but a document that has both files in front of it and
# still says "no evidence" is throwing away what it was given. A kill is permanent, so
# a boss proven at any ancestor is proven here.
#
# ANCESTORS, not "every earlier snapshot": a sibling branch is a different line, and a
# boss killed there was never killed on this one. This is exactly the case the DS3
# endings make real.
# @param rows Snapshots of one run, @param parents from @ref build_tree.
# @return [{boss: (sorted evidence, index of the snapshot it was proven in)}, ...].
def carry_bosses(rows, parents):
    out = []
    for i, r in enumerate(rows):
        got = dict(out[parents[i]]) if parents[i] is not None else {}
        for boss, ev in r["bosses"].items():
            # The current save's own evidence always wins: it is the one still standing.
            got[boss] = (sorted(ev), i)
        out.append(got)
    return out


##
# @brief The bosses a snapshot can only prove through an ancestor, newest first.
# @return [(boss, evidence, index of the snapshot that proved it)].
def carried_only(row, carried):
    return sorted(((b, ev, at) for b, (ev, at) in carried.items() if b not in row["bosses"]),
                  key=lambda t: (t[2], t[0]))


##
# @brief Children of each node, in order. @return {parent index: [child index, ...]}.
def children(parents):
    kids = {}
    for i, p in enumerate(parents):
        if p is not None:
            kids.setdefault(p, []).append(i)
    return kids


##
# @brief How many snapshots in this run have more than one child — the fork count.
def fork_count(parents):
    return sum(1 for v in children(parents).values() if len(v) > 1)


##
# @brief What this snapshot achieved that its parent had not — the node's headline.
# @details Ordered by how much it means, and capped, because a node has to stay
# readable: an ending outranks a boss, a boss outranks a bonfire, and "+3 bonfires"
# outranks a level-up. A snapshot that achieved nothing returns [], which is the honest
# answer for the many backups taken minutes apart.
# @param cur The snapshot, @param prev its parent (or None for the first).
# @param cap Most lines to return.
# @return A list of short strings.
def achievements(cur, prev, cap=3):
    was = progress(prev) if prev else {"bonfires": set(), "bosses": set(), "endings": set(),
                                       "cinders": set(), "covenants": set(), "pickups": {},
                                       "level": 0, "estus": -1, "ng_plus": -1}
    out = []
    for end in sorted(set(cur["endings"]) - was["endings"]):
        out.append(f"ENDING: {end}")
    if prev and (cur["ng_plus"] or 0) > (prev["ng_plus"] or 0):
        out.append(f"NEW JOURNEY: NG+{cur['ng_plus']}")
    # Bosses are compared on the WHOLE set here, not the flag-only one containment
    # uses: a kill proven by a held soul is still news worth putting in the box, and
    # the two sides of the subtraction have to be the same kind of set or every node
    # claims the entire roster.
    had = set(prev["bosses"]) if prev else set()
    new_bosses = sorted(set(cur["bosses"]) - had)
    if new_bosses:
        out.append("BOSS: " + " · ".join(new_bosses[:2])
                   + (f" +{len(new_bosses) - 2} more" if len(new_bosses) > 2 else ""))
    new_cinders = sorted(set(cur["cinders"]) - was["cinders"])
    if new_cinders:
        out.append("CINDERS: " + " · ".join(new_cinders))
    new_covs = sorted(set(cur["covenants"]) - was["covenants"])
    if new_covs:
        out.append("COVENANT: " + " · ".join(new_covs[:2]))
    new_fires = sorted(progress(cur)["bonfires"] - was["bonfires"])
    if new_fires:
        named = " · ".join(n for _a, n in new_fires[:2])
        out.append(f"+{len(new_fires)} bonfire{'' if len(new_fires) == 1 else 's'}: {named}"
                   if len(new_fires) <= 2 else f"+{len(new_fires)} bonfires")
    if cur["estus"] is not None and cur["estus"] > was["estus"] >= 0:
        out.append(f"Estus +{was['estus']} → +{cur['estus']}")
    gained = sum(max(0, n - was["pickups"].get(a, 0)) for a, n in cur["pickups"].items())
    if gained:
        out.append(f"+{gained} world item{'' if gained == 1 else 's'}")
    if cur["level"] > was["level"]:
        out.append(f"lv{was['level']} → lv{cur['level']}" if prev else f"lv{cur['level']}")
    return out[:cap]


##
# @brief Number every file in the whole document, earliest to latest by FILE DATE.
# @details The reference list is what lets a node say "^12" instead of carrying a
# 40-character filename, and it is ordered by the file's modified time rather than play
# time because it spans games — the point of the ordering is "what did you play, in
# what order", which only the file date can answer.
#
# Keyed by full PATH, never by name: every game writes to a fixed filename, so a folder
# of backups is full of files all called DS30000.sl2 and a name-keyed index would
# collapse them into one reference. Where the names really do collide the list shows
# enough of each path to tell them apart, and where they do not it stays short.
# @param snaps Every snapshot in the document.
# @return ({path: number}, [(number, label, mtime, path), ...] in order).
def reference_index(snaps):
    seen = {}
    for s in snaps:
        if s["path"] not in seen or s["mtime"] < seen[s["path"]]:
            seen[s["path"]] = s["mtime"]
    order = sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))
    refs = {p: i + 1 for i, (p, _t) in enumerate(order)}
    dupes = {}
    for p, _t in order:
        dupes[os.path.basename(p)] = dupes.get(os.path.basename(p), 0) + 1
    # Paths are absolute by the time they get here, but a caller could still hand in a
    # single file or a mix, and commonpath raises rather than coping. A missing root
    # only means a colliding name shows its whole path, which is still unambiguous.
    try:
        root = os.path.commonpath([p for p, _t in order]) if len(order) > 1 else ""
    except ValueError:
        root = ""
    if root and not os.path.isdir(root):
        root = os.path.dirname(root)
    out = []
    for p, t in order:
        base = os.path.basename(p)
        label = base if dupes.get(base, 0) < 2 else (os.path.relpath(p, root)
                                                    if root else p)
        out.append((refs[p], label, t, p))
    return refs, out


##
# @brief Generic first-seen walk: the earliest snapshot each item appears in.
# @param get Pulls the iterable of items from a snapshot.
# @return [(item, snapshot), ...] in the order the items first showed up.
def first_seen(rows, get):
    seen, out = set(), []
    for r in rows:
        for item in get(r):
            if item not in seen:
                seen.add(item)
                out.append((item, r))
    return out
