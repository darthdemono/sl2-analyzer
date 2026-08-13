/**
 * Turn a pile of saves into runs, and each run into a tree of snapshots.
 *
 * Port of sl2/timeline.py — if you change the inference there, change it here too;
 * scratch/combined_harness.mjs holds the two byte-for-byte.
 *
 * A folder of backups is not a list. Sorted by time they LOOK linear, but reloading
 * an earlier save and playing on forks the run — the four Dark Souls III endings are
 * exactly that, one pre-ending save finished four ways. Lineage is recoverable because
 * event flags never clear: a snapshot's parent is the latest earlier one whose progress
 * it still entirely contains, so a sibling branch (holding a flag this one lacks) fails
 * that test and both land on the shared ancestor.
 */

/** The Estus Flask's reinforcement level, or null. Not a stored field: DS3 keeps the
 *  level IN the flask's goods id, so it rides in the resolved name. */
const ESTUS_RE = /^Estus Flask(?: \+(\d+))?$/;

export function estusLevel(ch) {
  for (const [name] of ((ch.inv || {}).consumables || [])) {
    const mt = ESTUS_RE.exec(name);
    if (mt) return Number(mt[1] || 0);
  }
  return null;
}

/**
 * Flatten one parsed character into the fields a timeline needs. Bonfires become
 * (area, name) pairs so two areas sharing a bonfire name cannot collide in a
 * first-seen set. A game that lacks a field simply does not get it.
 * @param {object} ch parsed character
 * @param {{path: string, file: string, mtime: number, size: number}} file
 * @param {number} slot 1-based slot number
 */
export function snapshot(ch, file, slot, game, title) {
  const areas = ch.bonfire_areas || [];
  let bonfires = [];
  for (const [a, , names] of areas) for (const n of names) bonfires.push([a, n]);
  if (!bonfires.length && ch.bonfires) bonfires = ch.bonfires.map((n) => [null, n]);
  const bosses = {};
  for (const [b, ev] of Object.entries(ch.bosses || {})) bosses[b] = [...ev];
  const covenants = {};
  for (const [c, v] of Object.entries(ch.covenants || {})) covenants[c] = [...v];
  const questlines = {};
  for (const [q, v] of Object.entries(ch.questlines || {})) questlines[q] = [...v];
  const pickups = {};
  let pickupTotal = 0;
  for (const [a, c, t] of (ch.pickups || [])) { pickups[a] = c; pickupTotal += t; }
  return {
    path: file.path, file: file.file, mtime: file.mtime, size: file.size,
    game, title, slot, name: ch.name || "?", tier: ch.tier,
    play_time: ch.play_time || 0, level: ch.level || 0, souls: ch.souls || 0,
    attack: ch.attack == null ? null : ch.attack,
    vitality: ch.vitality == null ? null : ch.vitality,
    key_items: [...new Set((ch.key_items || []).map(([n]) => n))].sort(),
    soul_memory: ch.soul_memory == null ? null : ch.soul_memory,
    deaths: ch.deaths == null ? null : ch.deaths,
    hollow_lvl: ch.hollow_lvl == null ? null : ch.hollow_lvl,
    embered: ch.embered == null ? null : ch.embered,
    covenant: ch.covenant || null,
    ng_plus: ch.ng_plus == null ? null : ch.ng_plus,
    estus: estusLevel(ch),
    bonfires, bosses, covenants, questlines, pickups,
    pickup_total: pickupTotal,
    endings: [...(ch.endings || [])],
    cinders: [...(ch.cinders || [])],
    boss_total: ch.boss_total == null ? null : ch.boss_total,
  };
}

/**
 * Group snapshots into runs — one per character, across every file holding it.
 * Keyed by (game, name, slot): an all-characters mule really does hold ten slots
 * called the same thing, and merging those would invent a history none of them had.
 * Ordered inside a run by PLAY TIME, the game's own clock, since file dates reorder
 * when saves are copied around.
 * @returns {Map<string, object[]>} key JSON [game, name, slot] → snapshots
 */
export function groupRuns(snaps) {
  const runs = new Map();
  for (const s of snaps) {
    const k = runKey(s);
    if (!runs.has(k)) runs.set(k, []);
    runs.get(k).push(s);
  }
  for (const rows of runs.values()) {
    rows.sort((a, b) => a.play_time - b.play_time || a.mtime - b.mtime
      || cmp(a.file, b.file) || a.slot - b.slot);
  }
  // Ties keep insertion order, which is what Python's stable sort does too.
  return new Map([...runs.entries()].sort((x, y) =>
    Math.min(...x[1].map((s) => s.mtime)) - Math.min(...y[1].map((s) => s.mtime))));
}

/** A run's identity as a string key. JSON rather than a joined string: it needs no
 *  separator that a character name might contain, and it parses straight back. */
export const runKey = (s) => JSON.stringify([s.game, s.name, s.slot]);

/**
 * An (area, name) bonfire pair as a string key, joined on NUL.
 *
 * It has to sort exactly like the Python tuple, and JSON does NOT — it is right until
 * one element is a PREFIX of another, where JSON puts the closing quote (0x22) against
 * the next real character and can order the pair backwards. "Farron Keep" and "Farron
 * Keep Perimeter" are a real pair that does it. NUL is below every character a name can
 * contain, so the shorter element sorts first, which is Python's rule for a prefix.
 * (A null area joins as the empty string, and every key in that run then starts with
 * NUL, so they still order among themselves the way Python orders (None, name).)
 */
export const PAIR_SEP = "\u0000";
export const pairKey = (a, n) => [a, n].join(PAIR_SEP);
export const pairName = (key) => key.split(PAIR_SEP)[1];

/** Python sorts strings by code point; so must this, or the two orders drift. */
export function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

/** Boss kills that came from a FLAG — the only boss evidence that cannot go
 *  backwards. A boss known by its held soul vanishes the moment the soul is spent. */
export function flagBosses(s) {
  return new Set(Object.entries(s.bosses)
    .filter(([, ev]) => ev.includes("flag") || ev.includes("clear")).map(([b]) => b));
}

/** The monotone progress a snapshot holds — only one-way signals. Souls are spent, a
 *  covenant is switched, embered is consumed: any of those would fork on every death. */
export function progress(s) {
  return {
    bonfires: new Set(s.bonfires.map(([a, n]) => pairKey(a, n))),
    bosses: flagBosses(s),
    endings: new Set(s.endings),
    cinders: new Set(s.cinders),
    covenants: new Set(Object.keys(s.covenants)),
    pickups: s.pickups,
    level: s.level,
    // Sekiro's only one-way signal: it has no level, no bonfires and no flags
    // this tool reads, and a Memory consumed is never un-consumed — not even
    // by a New Game+ lap. See progress() in sl2/timeline.py.
    attack: s.attack == null ? -1 : s.attack,
    vitality: s.vitality == null ? -1 : s.vitality,
    estus: s.estus == null ? -1 : s.estus,
    ng_plus: s.ng_plus == null ? -1 : s.ng_plus,
  };
}

/** Progress a New Game+ lap wipes. */
const RESETTABLE = ["bonfires", "bosses", "cinders", "covenants"];

const subset = (a, b) => [...a].every((x) => b.has(x));

/** Could `b` be a continuation of `a`? A journey bump waives what a lap resets;
 *  endings are never waived, which is what separates two saves finished differently
 *  from the same parent. */
export function descends(a, b) {
  const pa = progress(a), pb = progress(b);
  if (pa.ng_plus > pb.ng_plus) return false;
  if (!subset(pa.endings, pb.endings)) return false;
  if (pa.level > pb.level || pa.estus > pb.estus) return false;
  if (pa.attack > pb.attack || pa.vitality > pb.vitality) return false;
  if (pb.ng_plus > pa.ng_plus) return true;
  for (const k of RESETTABLE) if (!subset(pa[k], pb[k])) return false;
  return Object.entries(pa.pickups).every(([area, n]) => n <= (pb.pickups[area] || 0));
}

/**
 * Each snapshot's parent — a run becomes a forest. When nothing earlier qualifies the
 * snapshot becomes a root of its own rather than hanging off whatever preceded it:
 * a save that lost progress cannot be a continuation of anything before it, and
 * drawing it as a second tree says so.
 * @returns {{parents: (number|null)[], restarts: Set<number>}}
 */
export function buildTree(rows) {
  const parents = [], restarts = new Set();
  for (let i = 0; i < rows.length; i++) {
    let best = null;
    for (let j = i - 1; j >= 0; j--) if (descends(rows[j], rows[i])) { best = j; break; }
    if (best === null && i > 0) restarts.add(i);
    parents.push(best);
  }
  return { parents, restarts };
}

/**
 * Carry every boss kill forward down each line of descent.
 *
 * A single save is a floor and it can only fall: the held-soul evidence that proves a
 * kill DISAPPEARS when the soul is spent, so a later save reports fewer bosses than an
 * earlier one on the same run. Honest for one file; wasteful for a document holding
 * both. A kill is permanent, so a boss proven at any ancestor is proven here.
 *
 * ANCESTORS, not "every earlier snapshot": a sibling branch is a different line, and a
 * boss killed there was never killed on this one.
 * @returns {Map<string, [string[], number]>[]} per row: boss -> [evidence, row it came from]
 */
export function carryBosses(rows, parents) {
  const out = [];
  rows.forEach((r, i) => {
    const got = new Map(parents[i] === null ? [] : out[parents[i]]);
    // The current save's own evidence always wins: it is the one still standing.
    for (const [boss, ev] of Object.entries(r.bosses)) got.set(boss, [[...ev].sort(), i]);
    out.push(got);
  });
  return out;
}

/** The bosses a snapshot can only prove through an ancestor. */
export function carriedOnly(row, carried) {
  return [...carried.entries()].filter(([b]) => !(b in row.bosses))
    .map(([b, [ev, at]]) => [b, ev, at])
    .sort((x, y) => x[2] - y[2] || cmp(x[0], y[0]));
}

/** Children of each node, in order. */
export function children(parents) {
  const kids = new Map();
  parents.forEach((p, i) => {
    if (p === null) return;
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(i);
  });
  return kids;
}

/** How many snapshots have more than one child. */
export function forkCount(parents) {
  return [...children(parents).values()].filter((v) => v.length > 1).length;
}

const sortedSet = (s) => [...s].sort(cmp);
const diff = (a, b) => sortedSet(new Set([...a].filter((x) => !b.has(x))));

/**
 * What this snapshot achieved that its parent had not — the node's headline, ordered
 * by how much it means and capped so a node stays readable.
 */
export function achievements(cur, prev, cap = 3) {
  const was = prev ? progress(prev) : {
    bonfires: new Set(), bosses: new Set(), endings: new Set(), cinders: new Set(),
    covenants: new Set(), pickups: {}, level: 0, attack: -1, vitality: -1,
    estus: -1,
    ng_plus: -1,
  };
  const cp = progress(cur);
  const out = [];
  for (const end of diff(cp.endings, was.endings)) out.push(`ENDING: ${end}`);
  if (prev && (cur.ng_plus || 0) > (prev.ng_plus || 0)) {
    out.push(`NEW JOURNEY: NG+${cur.ng_plus}`);
  }
  // Bosses are compared on the WHOLE set here, not the flag-only one containment
  // uses: a kill proven by a held soul is still news worth putting in the box, and
  // both sides of the subtraction have to be the same kind of set.
  const had = prev ? new Set(Object.keys(prev.bosses)) : new Set();
  const nb = diff(new Set(Object.keys(cur.bosses)), had);
  if (nb.length) {
    out.push("BOSS: " + nb.slice(0, 2).join(" · ")
      + (nb.length > 2 ? ` +${nb.length - 2} more` : ""));
  }
  // Sekiro's version of the same news, and the only one it can give: Attack Power
  // rises by one per Memory consumed, so a step here IS a boss whose token has
  // already been spent — the kill the boss list can no longer see. And a Prayer
  // Necklace leaves no trace either once used; only Vitality remembers it.
  if (cur.attack != null && was.attack >= 0 && cur.attack > was.attack) {
    out.push(`MEMORY SPENT: attack ${was.attack} \u2192 ${cur.attack}`);
  }
  if (cur.vitality != null && was.vitality >= 0 && cur.vitality > was.vitality) {
    out.push(`NECKLACE USED: vitality ${was.vitality} \u2192 ${cur.vitality}`);
  }
  // Key items are the one per-save delta Sekiro can show besides its two counters.
  // NOT in the containment test — some key items are consumed on use.
  const nk = diff(new Set(cur.key_items), new Set(prev ? prev.key_items : []));
  if (nk.length) {
    out.push("KEY ITEM: " + nk.slice(0, 2).join(" \u00b7 ")
      + (nk.length > 2 ? ` +${nk.length - 2} more` : ""));
  }
  const nc = diff(cp.cinders, was.cinders);
  if (nc.length) out.push("CINDERS: " + nc.join(" · "));
  const nv = diff(cp.covenants, was.covenants);
  if (nv.length) out.push("COVENANT: " + nv.slice(0, 2).join(" · "));
  const nf = diff(cp.bonfires, was.bonfires);
  if (nf.length) {
    const named = nf.slice(0, 2).map(pairName).join(" · ");
    out.push(nf.length <= 2
      ? `+${nf.length} bonfire${nf.length === 1 ? "" : "s"}: ${named}`
      : `+${nf.length} bonfires`);
  }
  if (cur.estus != null && was.estus >= 0 && cur.estus > was.estus) {
    out.push(`Estus +${was.estus} → +${cur.estus}`);
  }
  let gained = 0;
  for (const [a, n] of Object.entries(cur.pickups)) gained += Math.max(0, n - (was.pickups[a] || 0));
  if (gained) out.push(`+${gained} world item${gained === 1 ? "" : "s"}`);
  if (cur.level > was.level) {
    out.push(prev ? `lv${was.level} → lv${cur.level}` : `lv${cur.level}`);
  }
  return out.slice(0, cap);
}

/**
 * Number every file in the document, earliest to latest by FILE DATE — the only clock
 * shared across games. Keyed by full PATH, never by name: every game writes to a fixed
 * filename, so a name-keyed index would collapse a whole folder into one reference.
 * @returns {{refs: Map<string, number>, order: [number, string, number, string][]}}
 */
export function referenceIndex(snaps) {
  const seen = new Map();
  for (const s of snaps) {
    if (!seen.has(s.path) || s.mtime < seen.get(s.path)) seen.set(s.path, s.mtime);
  }
  const order = [...seen.entries()].sort((a, b) => a[1] - b[1] || cmp(a[0], b[0]));
  const refs = new Map(order.map(([p], i) => [p, i + 1]));
  const dupes = new Map();
  for (const [p] of order) {
    const b = basename(p);
    dupes.set(b, (dupes.get(b) || 0) + 1);
  }
  const root = order.length > 1 ? commonDir(order.map(([p]) => p)) : "";
  const out = order.map(([p, t]) => {
    const b = basename(p);
    const label = (dupes.get(b) || 0) < 2 ? b : (root ? relTo(p, root) : p);
    return [refs.get(p), label, t, p];
  });
  return { refs, order: out };
}

const basename = (p) => p.split("/").pop();

/** The deepest folder every path shares, so a disambiguated label stays short.
 *  Paths from different trees share only the root, which is "/" and not "" — the
 *  difference matters, because Python's commonpath says "/" there and a label relative
 *  to "/" loses its leading slash. */
function commonDir(paths) {
  const parts = paths.map((p) => p.split("/").slice(0, -1));
  const first = parts[0] || [];
  let n = 0;
  while (n < first.length && parts.every((q) => q[n] === first[n])) n++;
  const joined = first.slice(0, n).join("/");
  return joined === "" && n === 1 ? "/" : joined;
}

function relTo(p, root) {
  if (root === "/") return p.replace(/^\//, "");
  return root && p.startsWith(root + "/") ? p.slice(root.length + 1) : p;
}

/** Generic first-seen walk: the earliest snapshot each item appears in. */
export function firstSeen(rows, get) {
  const seen = new Set(), out = [];
  for (const r of rows) {
    for (const item of get(r)) {
      const k = typeof item === "string" ? item : JSON.stringify(item);
      if (!seen.has(k)) { seen.add(k); out.push([item, r]); }
    }
  }
  return out;
}
