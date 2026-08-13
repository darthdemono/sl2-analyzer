"""Mermaid flowcharts for the combined document.

Two charts, and they mean two different things, which is exactly why they are two
charts. The JOURNEY chart is real-world time: which game you played, in what order,
by file date. A RUN chart is save lineage inside one character: which snapshot came
from which, by what progress it contains. Drawing both in one picture would leave an
arrow meaning "later that month" in one place and "reloaded and forked" in another.

Every node is one .sl2 file, referred to by its number in the document's reference
list rather than its name — a filename in a box makes the box wider than the chart.
"""
from datetime import datetime

from .timeline import achievements, children

## @brief Mermaid takes the label between double quotes, so the label may not contain
#  one; `#quot;` is its own escape. Line breaks inside a node are `<br/>`.
#  (Both are backticked so Doxygen reads them as literals — bare `#quot;` is a link
#  request to it, and a bare break tag is parsed as HTML.)
def mm(text):
    return str(text).replace('"', "#quot;")


def label(lines):
    return mm("<br/>".join(l for l in lines if l))


## @brief "1 boss" / "2 bosses". A fresh save really does hold one of things, and a
#  count that reads "1 bosses" makes the whole document look generated.
def plural(n, word):
    end = "" if n == 1 else ("es" if word.endswith(("s", "x", "ch")) else "s")
    return f"{n} {word}{end}"


##
# @brief Format a play time as H:MM:SS, or an em dash when the game does not store one.
def hms(sec):
    if not sec:
        return "—"
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


##
# @brief The number a game counts progress in, for a snapshot's label or table cell.
# @details Every game but one levels up, so "lv95" is the obvious shorthand — but
# Sekiro has no level at all, and printing "lv0" for it would state a field the game
# does not have. Its equivalent is Attack Power, which only ever climbs (one point per
# Memory consumed), so that is what its charts and tables count in.
# @param r A snapshot. @return e.g. @c "lv95" or @c "atk 7".
def rank(r):
    if r["game"] == "sdt":
        return "atk —" if r["attack"] is None else f"atk {r['attack']}"
    return f"lv{r['level']}"


## @brief The same value bare, for a table cell whose column is already labelled.
def rank_cell(r):
    return "—" if r["game"] == "sdt" and r["attack"] is None else str(
        r["attack"] if r["game"] == "sdt" else r["level"])


## @brief Header for that column, given the run's game.
def rank_label(game):
    return "Atk" if game == "sdt" else "Lv"


##
# @brief One run's snapshot tree, as a Mermaid flowchart.
# @details One node per save file, labelled with its reference number, the level it was
# at, and what it achieved that its parent had not. A node that achieved nothing still
# appears — it is a real save and its file is real — but it says so with nothing rather
# than with filler.
# @param rows    The run's snapshots in order.
# @param parents Parent index per row, @param restarts rows that start a fresh line.
# @param refs    {filename: reference number}.
# @param theme   Game id, used to colour the ending/leaf nodes.
# @return A list of Markdown lines, fenced as a mermaid block.
def run_chart(rows, parents, restarts, refs, theme=None):
    L = ["```mermaid", "flowchart TD"]
    kids = children(parents)
    for i, r in enumerate(rows):
        prev = rows[parents[i]] if parents[i] is not None else None
        head = f"^{refs.get(r['path'], '?')} · {hms(r['play_time'])}"
        if r["slot"] and any(x["slot"] != r["slot"] for x in rows):
            head += f" · slot {r['slot']}"
        lines = [head, rank(r)]
        if i in restarts:
            lines.insert(1, "SEPARATE LINE")
        body = label(lines + achievements(r, prev))
        L.append('  n%d["%s"]' % (i, body))
    for i, p in enumerate(parents):
        if p is not None:
            L.append(f"  n{p} --> n{i}")
    # A leaf is where a line stopped; an ending is where it FINISHED. Both are worth
    # seeing at a glance, and an ending outranks a leaf when a node is both.
    ends = [i for i, r in enumerate(rows)
            if set(r["endings"]) - (set(rows[parents[i]]["endings"])
                                    if parents[i] is not None else set())]
    leaves = [i for i in range(len(rows)) if i not in kids and i not in ends]
    if ends:
        L.append("  classDef ending fill:#3a2a12,stroke:#c9a227,color:#f0e6d2,stroke-width:2px;")
        L.append("  class " + ",".join(f"n{i}" for i in ends) + " ending;")
    if leaves:
        L.append("  classDef leaf stroke-dasharray:4 3;")
        L.append("  class " + ",".join(f"n{i}" for i in leaves) + " leaf;")
    if restarts:
        L.append("  classDef restart stroke:#9a3b3b,stroke-width:2px;")
        L.append("  class " + ",".join(f"n{i}" for i in sorted(restarts)) + " restart;")
    L.append("```")
    return L


##
# @brief The cross-game journey: one node per run, in the order they were played.
# @details Ordered and linked by FILE DATE, because that is the only clock shared
# across games — a Dark Souls II play time and a Dark Souls III one are unrelated
# numbers. Each node carries the run's span in files and where it got to, so the chart
# answers "what have I actually played" on its own.
# @param runs {(game, name): [snapshot, ...]}, @param refs {filename: number}.
def journey_chart(runs, refs):
    L = ["```mermaid", "flowchart LR"]
    items = list(runs.items())
    for n, ((_game, name, _slot), rows) in enumerate(items):
        last = rows[-1]
        nums = sorted({refs.get(r["path"], 0) for r in rows})
        span = f"^{nums[0]}" if len(nums) == 1 else f"^{nums[0]}–^{nums[-1]}"
        got = [f"{len(rows)} save{'' if len(rows) == 1 else 's'} · {span}",
               f"{rank(last)} · {hms(last['play_time'])}"]
        # The carried set when the run section worked one out — a boss whose soul was
        # spent is still a boss killed, and the journey chart should say so.
        known = last.get("carried_bosses") or last["bosses"]
        if known:
            got.append(plural(len(known), "boss"))
        if last["endings"]:
            got.append("FINISHED: " + " · ".join(sorted(last["endings"])))
        body = label(["%s — %s" % (last["title"], name)] + got)
        L.append('  r%d["%s"]' % (n, body))
    for n in range(1, len(items)):
        L.append(f"  r{n - 1} --> r{n}")
    L.append("```")
    return L


##
# @brief The reference list every chart node points at.
# @details Wiki-style [[links]] because that is what the owner reads these in, and
# ordered earliest to latest by file date so the numbering itself carries the history.
def reference_list(order):
    L = ["## References", "",
         "_Every node above is one save file. Numbered earliest to latest by file date._",
         ""]
    for num, name, mtime, _path in order:
        when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        L.append(f"^{num}: [[{name}]] — _{when}_")
    return L + [""]
