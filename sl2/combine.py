"""Read a FOLDER of saves and write one document covering every run in it.

The single-save export answers "what is in this file". This answers "what have I
played" — drop a directory holding Dark Souls, Dark Souls II, Dark Souls III and
Elden Ring backups together and it sorts them into runs, reconstructs each run's
history from its backups, and writes one Markdown file with a cross-game journey
chart on top, a branch chart per run, and every source file numbered in a reference
list at the end.

Nothing here is filename-driven. Which game a file is comes from its header, which
character a save belongs to comes from the save, and the order comes from the game's
own play-time clock (falling back to the file date where a game does not store one).
Backups can be named anything.
"""
import os
from collections import OrderedDict
from datetime import datetime

from .chart import hms, journey_chart, plural, reference_list, run_chart
from .convert import GAMES, META_LABEL, parse_save
from .render import md_for_character
from .timeline import (build_tree, carried_only, carry_bosses, first_seen,
                       fork_count, group_runs, reference_index, snapshot)

## @brief Evidence tags, spelled out. Same words the single-save export uses.
SRC = {"flag": "confirmed", "soul": "soul held", "gate": "progression",
       "clear": "cleared (NG+)"}


##
# @brief Every .sl2 under @p folder, recursively.
# @details Case-insensitive, because Windows writes DS30000.sl2 and some tools write
# .SL2, and sorted so a run of the tool twice over the same folder reads the same.
def find_saves(folder):
    out = []
    for root, _dirs, files in os.walk(os.path.abspath(folder)):
        out += [os.path.join(root, f) for f in files if f.lower().endswith(".sl2")]
    return sorted(out)


##
# @brief Parse one file into a snapshot per populated character.
# @details A save that will not parse is SKIPPED, not fatal: a folder of backups
# collected over years will contain a truncated copy sooner or later, and losing the
# whole document to one bad file would be the wrong trade. Vanilla Dark Souls II
# raises SystemExit from the detector, which is caught for the same reason.
def read_file(path, base_dir):
    try:
        with open(path, "rb") as f:
            save = parse_save(f.read(), base_dir)
    except (OSError, ValueError, SystemExit):
        return []
    cfg = GAMES[save.game]
    start = cfg["slots"].start
    return [snapshot(ch, path, i - start + 1, save.game, cfg["title"])
            for i, ch in save.characters]


##
# @brief The one-line summary under a run's heading.
# @param carried The newest snapshot's carried boss set, from @ref carry_bosses.
def run_summary(rows, carried=None):
    first, last = rows[0], rows[-1]
    bits = [f"{len(rows)} save{'' if len(rows) == 1 else 's'}",
            f"lv{first['level']} → lv{last['level']}"]
    if last["play_time"]:
        bits.append(f"{hms(first['play_time'])} → {hms(last['play_time'])} played")
    if last["bonfires"]:
        bits.append(plural(len(last["bonfires"]), "bonfire"))
    known = carried if carried else last["bosses"]
    if known:
        extra = len(known) - len(last["bosses"])
        bits.append(plural(len(known), "boss")
                    + (f" ({len(last['bosses'])} still provable in the newest save, "
                       f"{extra} carried from earlier)" if extra else ""))
    if last["pickups"]:
        bits.append(f"{sum(last['pickups'].values())} of {last['pickup_total']} world items")
    if last["endings"]:
        bits.append("finished: " + " · ".join(sorted(last["endings"])))
    return "_" + " · ".join(bits) + "._"


##
# @brief A run's timeline tables — the "when did this first appear" half.
# @details Every section is skipped when the game has nothing to put in it, so a Dark
# Souls run does not print an empty Covenants table and an Elden Ring one does not
# print bonfires it cannot read. The tables walk snapshots in order regardless of
# branch, which is stated in the document rather than hidden.
def run_timeline(rows, refs):
    L = []
    ref = lambda r: f"^{refs.get(r['path'], '?')}"

    bosses = first_seen(rows, lambda r: r["bosses"])
    if bosses:
        L += ["#### Bosses — first appearance", "",
              "| Play Time | Lv | Boss | Evidence | Save |", "|---|---|---|---|---|"]
        for boss, r in bosses:
            ev = ", ".join(SRC.get(e, e) for e in sorted(r["bosses"][boss]))
            L.append(f"| {hms(r['play_time'])} | {r['level']} | {boss} | {ev} | {ref(r)} |")
        L.append("")

    covs = first_seen(rows, lambda r: r["covenants"])
    if covs:
        L += ["#### Covenants — first found", "",
              "| Play Time | Lv | Covenant | Progress | Save |", "|---|---|---|---|---|"]
        for cov, r in covs:
            L.append(f"| {hms(r['play_time'])} | {r['level']} | {cov} | "
                     f"{', '.join(r['covenants'][cov])} | {ref(r)} |")
        L.append("")

    rewards = first_seen(rows, lambda r: [(q, rw) for q, v in r["questlines"].items()
                                          for rw in v])
    if rewards:
        L += ["#### Rewards — first obtained", "",
              "_A floor: only rewards actually collected are visible._", "",
              "| Play Time | Lv | Source | Reward | Save |", "|---|---|---|---|---|"]
        for pair, r in rewards:
            L.append(f"| {hms(r['play_time'])} | {r['level']} | {pair[0]} | {pair[1]} "
                     f"| {ref(r)} |")
        L.append("")

    fires = first_seen(rows, lambda r: [tuple(b) for b in r["bonfires"]])
    if fires:
        L += ["#### Bonfires — first lit", ""]
        seen, total = set(), 0
        for r in rows:
            new = [tuple(b) for b in r["bonfires"] if tuple(b) not in seen]
            if not new:
                continue
            seen.update(new)
            total += len(new)
            L.append(f"**{hms(r['play_time'])} · lv{r['level']} · {ref(r)}** — "
                     f"{total} total (+{len(new)})")
            L += ["", *[f"- {a}: {n}" if a else f"- {n}" for a, n in sorted(new)], ""]

    est = [r for i, r in enumerate(rows)
           if r["estus"] is not None and (i == 0 or r["estus"] != rows[i - 1]["estus"])]
    if len(est) > 1:
        L += ["#### Estus — reinforcement", "",
              "_Each step is one Undead Bone Shard burned. The level is stored in the "
              "flask's own item id, so this is read, not inferred._", "",
              "| Play Time | Lv | Estus | Save |", "|---|---|---|---|"]
        for r in est:
            L.append(f"| {hms(r['play_time'])} | {r['level']} | +{r['estus']} | {ref(r)} |")
        L.append("")

    if any(r["pickups"] for r in rows):
        L += ["#### World items — where the count moved", "",
              "_Only the areas whose pickup-flag group is mapped are counted, so an area "
              "absent here is unmapped, not empty._", ""]
        prev = {}
        for r in rows:
            gained = [(a, c - prev.get(a, 0)) for a, c in sorted(r["pickups"].items())
                      if c > prev.get(a, 0)]
            if not gained:
                continue
            L.append(f"**{hms(r['play_time'])} · lv{r['level']} · {ref(r)}** — "
                     f"{sum(r['pickups'].values())} total "
                     f"(+{sum(n for _a, n in gained)})")
            L += ["", *[f"- {a}: +{n} (now {r['pickups'][a]})" for a, n in gained], ""]
            prev = r["pickups"]
    return L


##
# @brief One run's whole section: chart, current state, timeline.
# @details The newest snapshot is re-parsed so its FULL dump can be printed — the
# timeline knows what changed but not the character's inventory, and re-reading one
# file is cheaper than carrying every field of every backup through the walk.
def run_section(key, rows, refs, base_dir):
    game, name, _slot = key
    last = rows[-1]
    parents, restarts = build_tree(rows)
    forks = fork_count(parents)
    carried = carry_bosses(rows, parents)
    for row, got in zip(rows, carried):
        row["carried_bosses"] = {b: ev for b, (ev, _at) in got.items()}

    L = [f"## {last['title']} — {name}", "", run_summary(rows, carried[-1]), ""]
    L += ["### Save Tree", ""]
    L.append("_Each box is one save file, numbered as in the references at the end. A "
             "snapshot's parent is the latest earlier one whose progress it still "
             "entirely contains — event flags never clear, so a fork (the same save "
             "played on twice) lands both children on the shared ancestor._")
    L.append("")
    note = [f"{forks} fork{'' if forks == 1 else 's'}" if forks else "No forks",
            f"{len(restarts)} separate line{'' if len(restarts) == 1 else 's'}"
            if restarts else None,
            "a dashed box is where a line stopped"]
    L.append("_" + ", ".join(n for n in note if n) + "._")
    if restarts:
        L.append("")
        L.append("_A box marked SEPARATE LINE could not descend from anything before it "
                 "— it holds less progress than saves that came earlier, so it belongs to "
                 "a different playthrough that happens to share this character's name and "
                 "slot._")
    L.append("")
    L += run_chart(rows, parents, restarts, refs, game)
    L.append("")

    L += [f"### Current State — `{last['file']}` (^{refs.get(last['path'], '?')})", ""]
    try:
        with open(last["path"], "rb") as f:
            save = parse_save(f.read(), base_dir)
        start = GAMES[save.game]["slots"].start
        for i, ch in save.characters:
            # Matched on SLOT, not name: an all-characters mule holds several unnamed
            # slots, and matching by name would render the same one under each of them.
            if i - start + 1 == last["slot"]:
                # Demote every heading one level: the dump's own "## Slot 1" has to sit
                # under this run's "##", not beside it.
                L += [ln if not ln.startswith("#") else "#" + ln
                      for ln in md_for_character(ch, last["slot"]).split("\n")]
                break
    except (OSError, ValueError, SystemExit):
        L.append("_The newest save could not be re-read for a full dump._")
    L.append("")

    lost = carried_only(last, carried[-1])
    if lost:
        L += ["### Bosses Carried Forward", "",
              "_Proven by an EARLIER save on this line and not by the newest one. A held "
              "boss soul is proof of a kill, and spending the soul destroys the proof — "
              "but a kill is permanent, so the evidence stands. Only this save's own "
              "ancestors count; a boss killed on a different branch was never killed "
              "here._", "",
              "| Boss | Evidence | Proven in | Play Time |", "|---|---|---|---|"]
        for boss, ev, at in lost:
            src = rows[at]
            L.append(f"| {boss} | {', '.join(SRC.get(e, e) for e in ev)} | "
                     f"^{refs.get(src['path'], '?')} | {hms(src['play_time'])} |")
        L.append("")

    tl = run_timeline(rows, refs)
    if tl:
        L += ["### Timeline", ""] + tl
    return L


##
# @brief Build the whole combined document.
# @param folder   A directory to walk, or a list of files already found.
# @param base_dir Repo root, for the item databases.
# @param meta     The environment block from parse_meta, or None.
# @return The Markdown, as one string.
def build_combined(folder, base_dir, meta=None):
    paths = folder if isinstance(folder, list) else find_saves(folder)
    snaps = []
    for p in paths:
        snaps += read_file(p, base_dir)
    if not snaps:
        return None

    runs = group_runs(snaps)
    refs, order = reference_index(snaps)
    # The carry has to happen before the journey chart, not inside the run sections:
    # the chart is drawn first and would otherwise report the newest save's own count
    # while the section below it reports the carried one.
    for rows in runs.values():
        parents, _restarts = build_tree(rows)
        for row, got in zip(rows, carry_bosses(rows, parents)):
            row["carried_bosses"] = {b: ev for b, (ev, _at) in got.items()}
    games = OrderedDict((s["title"], None) for s in
                        sorted(snaps, key=lambda s: s["mtime"]))

    L = ["# FromSoftware Saves — Combined Playthrough Timeline", "",
         f"_Reconstructed from {len(order)} save file{'' if len(order) == 1 else 's'} "
         f"across {len(runs)} run{'' if len(runs) == 1 else 's'} and "
         f"{len(games)} game{'' if len(games) == 1 else 's'}: "
         + " · ".join(games) + "._", "",
         "_Every timestamp is an UPPER BOUND, not the moment it happened: a thing is "
         "dated to the first save it appears in, so the real event is somewhere between "
         "the previous save and that one. This is a reconstruction from sparse backups, "
         "not a log._", "",
         "---", "", "## The Journey", "",
         "_One box per character, in the order the files were last written — the only "
         "clock the games share, since a Dark Souls II play time and a Dark Souls III "
         "one are unrelated numbers._", ""]
    L += journey_chart(runs, refs)
    L += ["", "---", ""]

    for key, rows in runs.items():
        L += run_section(key, rows, refs, base_dir) + ["", "---", ""]

    L += reference_list(order)

    L += combined_footer(snaps, runs, meta)
    return "\n".join(L) + "\n"


##
# @brief The closing block: which games this document covers, how far to trust each,
#        and any setup the caller supplied.
# @details The single-save footer names one game because a save IS one game; a combined
# document spans several, each with its own support tier, so it lists them rather than
# picking one and quietly misreporting the rest.
def combined_footer(snaps, runs, meta):
    seen = OrderedDict()
    for s in sorted(snaps, key=lambda s: s["mtime"]):
        seen.setdefault(s["game"], s["title"])
    L = ["---", "", "<details>",
         "<summary>About this file — how it was produced, and how far to trust it"
         "</summary>", "",
         f"- **Save files read:** {len({s['path'] for s in snaps})}",
         f"- **Runs (characters):** {len(runs)}", "", "**Games covered**", ""]
    for game, title in seen.items():
        L.append(f"- **{title}:** support tier {GAMES[game]['tier']}")
    if meta:
        L += ["", "**Setup**  _(supplied by the caller — not read from the saves, "
              "which cannot know any of it)_", ""]
        for key, value in meta.items():
            lab = META_LABEL.get(key) or key.replace("_", " ").capitalize()
            shown = " · ".join(str(v) for v in value) if isinstance(value, list) else value
            L.append(f"- **{lab}:** {shown}")
    L += ["", "Everything above is read out of the saves themselves, in this browser or "
          "on this machine — nothing is uploaded. A field the tool cannot verify is "
          "left out rather than guessed, and every progress section is a FLOOR: it "
          "reports what the saves prove, never what they merely suggest.", "",
          f"_Generated {datetime.now():%Y-%m-%d %H:%M} by sl2-analyzer._", "",
          "</details>", ""]
    return L
