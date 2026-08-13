/**
 * One document covering every run in a pile of saves. Port of sl2/combine.py, and
 * held byte-for-byte against it by scratch/combined_harness.mjs.
 *
 * The single-save view answers "what is in this file". This answers "what have I
 * played": drop a folder holding Dark Souls, Dark Souls II, Dark Souls III and Elden
 * Ring backups together and it sorts them into runs, reconstructs each run's history,
 * and writes a cross-game journey chart, a branch chart per run, and a numbered
 * reference list of every file it read.
 *
 * Nothing is filename-driven — the game comes from the header, the character from the
 * save, the order from the game's own clock. Backups can be named anything.
 */
import {
  hms,
  journeyChart,
  plural,
  rank,
  rankCell,
  rankLabel,
  referenceList,
  runChart,
  stamp,
} from "./chart.js";
import { mdCharacter } from "./markdown.js";
import { GAMES } from "./parser.js";
import {
  buildTree,
  carriedOnly,
  carryBosses,
  firstSeen,
  forkCount,
  groupRuns,
  pairKey,
  referenceIndex,
  snapshot,
} from "./timeline.js";

/** Evidence tags, spelled out. Same words the single-save export uses. */
const SRC = { flag: "confirmed", soul: "soul held", gate: "progression", clear: "cleared (NG+)" };

/**
 * Snapshots for one parsed file.
 * @param {object} result what parseSave returned
 * @param {{path: string, file: string, mtime: number, size: number}} file
 */
export function fileSnapshots(result, file) {
  return result.characters.map(({ slot, ch }) =>
    snapshot(ch, file, slot, result.game, result.title),
  );
}

/** The one-line summary under a run's heading. `carried` is the newest snapshot's
 *  carried boss set, from carryBosses. */
function runSummary(rows, carried) {
  const first = rows[0],
    last = rows[rows.length - 1];
  const bits = [
    `${rows.length} save${rows.length === 1 ? "" : "s"}`,
    `${rank(first)} → ${rank(last)}`,
  ];
  if (last.play_time) bits.push(`${hms(first.play_time)} → ${hms(last.play_time)} played`);
  if (last.bonfires.length) bits.push(plural(last.bonfires.length, "bonfire"));
  const own = Object.keys(last.bosses).length;
  const known = carried ? carried.size : own;
  if (known) {
    const extra = known - own;
    bits.push(
      plural(known, "boss") +
        (extra ? ` (${own} still provable in the newest save, ${extra} carried from earlier)` : ""),
    );
  }
  const picked = Object.values(last.pickups).reduce((a, b) => a + b, 0);
  if (Object.keys(last.pickups).length) {
    bits.push(`${picked} of ${last.pickup_total} world items`);
  }
  if (last.endings.length) bits.push("finished: " + [...last.endings].sort().join(" · "));
  return "_" + bits.join(" · ") + "._";
}

/** A run's timeline tables. Every section is skipped when the game has nothing for it. */
function runTimeline(rows, refs) {
  const L = [];
  const ref = (r) => `^${refs.get(r.path) ?? "?"}`;
  const lv = rankLabel(rows.length ? rows[0].game : null);

  const bosses = firstSeen(rows, (r) => Object.keys(r.bosses));
  if (bosses.length) {
    L.push(
      "#### Bosses — first appearance",
      "",
      `| Play Time | ${lv} | Boss | Evidence | Save |`,
      "|---|---|---|---|---|",
    );
    for (const [boss, r] of bosses) {
      const ev = [...r.bosses[boss]]
        .sort()
        .map((e) => SRC[e] || e)
        .join(", ");
      L.push(`| ${hms(r.play_time)} | ${rankCell(r)} | ${boss} | ${ev} | ${ref(r)} |`);
    }
    L.push("");
  }

  const covs = firstSeen(rows, (r) => Object.keys(r.covenants));
  if (covs.length) {
    L.push(
      "#### Covenants — first found",
      "",
      `| Play Time | ${lv} | Covenant | Progress | Save |`,
      "|---|---|---|---|---|",
    );
    for (const [cov, r] of covs) {
      L.push(
        `| ${hms(r.play_time)} | ${rankCell(r)} | ${cov} | ` +
          `${r.covenants[cov].join(", ")} | ${ref(r)} |`,
      );
    }
    L.push("");
  }

  const rewards = firstSeen(rows, (r) =>
    Object.entries(r.questlines).flatMap(([q, v]) => v.map((rw) => [q, rw])),
  );
  if (rewards.length) {
    L.push(
      "#### Rewards — first obtained",
      "",
      "_A floor: only rewards actually collected are visible._",
      "",
      `| Play Time | ${lv} | Source | Reward | Save |`,
      "|---|---|---|---|---|",
    );
    for (const [pair, r] of rewards) {
      L.push(`| ${hms(r.play_time)} | ${rankCell(r)} | ${pair[0]} | ${pair[1]} | ${ref(r)} |`);
    }
    L.push("");
  }

  if (rows.some((r) => r.bonfires.length)) {
    L.push("#### Bonfires — first lit", "");
    const seen = new Set();
    let total = 0;
    for (const r of rows) {
      const fresh = r.bonfires.filter(([a, n]) => !seen.has(pairKey(a, n)));
      if (!fresh.length) continue;
      for (const [a, n] of fresh) seen.add(pairKey(a, n));
      total += fresh.length;
      L.push(
        `**${hms(r.play_time)} · ${rank(r)} · ${ref(r)}** — ` + `${total} total (+${fresh.length})`,
      );
      // Keyed so this orders exactly like Python's sort over (area, name) tuples.
      const sorted = fresh
        .slice()
        .sort((x, y) => (pairKey(x[0], x[1]) < pairKey(y[0], y[1]) ? -1 : 1));
      L.push("", ...sorted.map(([a, n]) => (a ? `- ${a}: ${n}` : `- ${n}`)), "");
    }
  }

  const est = rows.filter((r, i) => r.estus != null && (i === 0 || r.estus !== rows[i - 1].estus));
  if (est.length > 1) {
    L.push(
      "#### Estus — reinforcement",
      "",
      "_Each step is one Undead Bone Shard burned. The level is stored in the flask's " +
        "own item id, so this is read, not inferred._",
      "",
      `| Play Time | ${lv} | Estus | Save |`,
      "|---|---|---|---|",
    );
    for (const r of est) {
      L.push(`| ${hms(r.play_time)} | ${rankCell(r)} | +${r.estus} | ${ref(r)} |`);
    }
    L.push("");
  }

  if (rows.some((r) => Object.keys(r.pickups).length)) {
    L.push(
      "#### World items — where the count moved",
      "",
      "_Only the areas whose pickup-flag group is mapped are counted, so an area absent " +
        "here is unmapped, not empty._",
      "",
    );
    let prev = {};
    for (const r of rows) {
      const gained = Object.entries(r.pickups)
        .sort((a, b) => (a[0] < b[0] ? -1 : 1))
        .filter(([a, c]) => c > (prev[a] || 0))
        .map(([a, c]) => [a, c - (prev[a] || 0)]);
      if (!gained.length) continue;
      const total = Object.values(r.pickups).reduce((a, b) => a + b, 0);
      L.push(
        `**${hms(r.play_time)} · ${rank(r)} · ${ref(r)}** — ${total} total ` +
          `(+${gained.reduce((a, [, n]) => a + n, 0)})`,
      );
      L.push("", ...gained.map(([a, n]) => `- ${a}: +${n} (now ${r.pickups[a]})`), "");
      prev = r.pickups;
    }
  }
  return L;
}

/** One run's whole section: chart, current state, timeline. */
function runSection(key, rows, refs, charFor) {
  const name = JSON.parse(key)[1];
  const last = rows[rows.length - 1];
  const { parents, restarts } = buildTree(rows);
  const forks = forkCount(parents);
  const carried = carryBosses(rows, parents);

  const L = [
    `## ${last.title} — ${name}`,
    "",
    runSummary(rows, carried[carried.length - 1]),
    "",
    "### Save Tree",
    "",
  ];
  L.push(
    "_Each box is one save file, numbered as in the references at the end. A " +
      "snapshot's parent is the latest earlier one whose progress it still entirely " +
      "contains — event flags never clear, so a fork (the same save played on twice) " +
      "lands both children on the shared ancestor._",
  );
  L.push("");
  const note = [
    forks ? `${forks} fork${forks === 1 ? "" : "s"}` : "No forks",
    restarts.size ? `${restarts.size} separate line${restarts.size === 1 ? "" : "s"}` : null,
    "a dashed box is where a line stopped",
  ];
  L.push("_" + note.filter(Boolean).join(", ") + "._");
  if (restarts.size) {
    L.push("");
    L.push(
      "_A box marked SEPARATE LINE could not descend from anything before it — it " +
        "holds less progress than saves that came earlier, so it belongs to a different " +
        "playthrough that happens to share this character's name and slot._",
    );
  }
  L.push("");
  L.push(...runChart(rows, parents, restarts, refs));
  L.push("");

  L.push(`### Current State — \`${last.file}\` (^${refs.get(last.path) ?? "?"})`, "");
  const ch = charFor(last);
  if (ch) {
    // Demote every heading one level: the dump's own "## Slot 1" has to sit under this
    // run's "##", not beside it.
    L.push(
      ...mdCharacter(ch, last.slot)
        .split("\n")
        .map((ln) => (ln.startsWith("#") ? "#" + ln : ln)),
    );
  } else {
    L.push("_The newest save could not be re-read for a full dump._");
  }
  L.push("");

  const lost = carriedOnly(last, carried[carried.length - 1]);
  if (lost.length) {
    L.push(
      "### Bosses Carried Forward",
      "",
      "_Proven by an EARLIER save on this line and not by the newest one. A held boss " +
        "soul is proof of a kill, and spending the soul destroys the proof — but a kill " +
        "is permanent, so the evidence stands. Only this save's own ancestors count; a " +
        "boss killed on a different branch was never killed here._",
      "",
      "| Boss | Evidence | Proven in | Play Time |",
      "|---|---|---|---|",
    );
    for (const [boss, ev, at] of lost) {
      const src = rows[at];
      L.push(
        `| ${boss} | ${ev.map((e) => SRC[e] || e).join(", ")} | ` +
          `^${refs.get(src.path) ?? "?"} | ${hms(src.play_time)} |`,
      );
    }
    L.push("");
  }

  const tl = runTimeline(rows, refs);
  if (tl.length) L.push("### Timeline", "", ...tl);
  return L;
}

/**
 * Build the whole combined document.
 * @param {object[]} entries [{result, file}] — one per parsed save file.
 * @param {object|null} meta caller-supplied setup, or null.
 * @param {Date} [now] the generation stamp, injectable so a harness can pin it.
 * @returns {string|null} the Markdown, or null if nothing could be read.
 */
export function buildCombined(entries, meta = null, now = new Date()) {
  const snaps = [];
  const chars = new Map(); // path → [{slot, ch}], for the per-run full dump
  for (const { result, file } of entries) {
    if (!result) continue;
    snaps.push(...fileSnapshots(result, file));
    chars.set(file.path, result.characters);
  }
  if (!snaps.length) return null;

  const runs = groupRuns(snaps);
  const { refs, order } = referenceIndex(snaps);
  // The carry has to happen before the journey chart, not inside the run sections: the
  // chart is drawn first and would otherwise report the newest save's own count while
  // the section below it reports the carried one.
  for (const rows of runs.values()) {
    const { parents } = buildTree(rows);
    carryBosses(rows, parents).forEach((got, i) => {
      rows[i].carried_bosses = Object.fromEntries([...got].map(([b, [ev]]) => [b, ev]));
    });
  }
  const titles = [];
  for (const s of snaps.slice().sort((a, b) => a.mtime - b.mtime)) {
    if (!titles.includes(s.title)) titles.push(s.title);
  }

  const L = [
    "# FromSoftware Saves — Combined Playthrough Timeline",
    "",
    `_Reconstructed from ${order.length} save file${order.length === 1 ? "" : "s"} ` +
      `across ${runs.size} run${runs.size === 1 ? "" : "s"} and ` +
      `${titles.length} game${titles.length === 1 ? "" : "s"}: ${titles.join(" · ")}._`,
    "",
    "_Every timestamp is an UPPER BOUND, not the moment it happened: a thing is dated " +
      "to the first save it appears in, so the real event is somewhere between the " +
      "previous save and that one. This is a reconstruction from sparse backups, not a " +
      "log._",
    "",
    "---",
    "",
    "## The Journey",
    "",
    "_One box per character, in the order the files were last written — the only clock " +
      "the games share, since a Dark Souls II play time and a Dark Souls III one are " +
      "unrelated numbers._",
    "",
  ];
  L.push(...journeyChart(runs, refs));
  L.push("", "---", "");

  for (const [key, rows] of runs) {
    // The full dump comes from the character that IS this snapshot — matched on
    // slot, since a file can hold several characters that share a name.
    const charFor = (s) => {
      const hit = (chars.get(s.path) || []).find((c) => c.slot === s.slot);
      return hit ? hit.ch : null;
    };
    L.push(...runSection(key, rows, refs, charFor), "", "---", "");
  }

  L.push(...referenceList(order));
  L.push(...combinedFooter(snaps, runs, meta, now));
  return L.join("\n") + "\n";
}

/**
 * The closing block: which games this document covers, how far to trust each, and any
 * setup the caller supplied. The single-save footer names one game because a save IS
 * one game; a combined document spans several, each with its own support tier.
 */
function combinedFooter(snaps, runs, meta, now) {
  const seen = new Map();
  for (const s of snaps.slice().sort((a, b) => a.mtime - b.mtime)) {
    // The GAME's tier, not the character's: a slot can degrade to inventory tier on an
    // unrecognised patch, but that says nothing about how far the game as a whole is
    // supported, which is what this line claims.
    if (!seen.has(s.game)) seen.set(s.game, [s.title, (GAMES[s.game] || {}).tier || "full"]);
  }
  const files = new Set(snaps.map((s) => s.path));
  const L = [
    "---",
    "",
    "<details>",
    "<summary>About this file — how it was produced, and how far to trust it</summary>",
    "",
    `- **Save files read:** ${files.size}`,
    `- **Runs (characters):** ${runs.size}`,
    "",
    "**Games covered**",
    "",
  ];
  for (const [, [title, tier]] of seen) L.push(`- **${title}:** support tier ${tier}`);
  if (meta && Object.keys(meta).length) {
    L.push(
      "",
      "**Setup**  _(supplied by the caller — not read from the saves, which " +
        "cannot know any of it)_",
      "",
    );
    for (const [key, value] of Object.entries(meta)) {
      const lab =
        META_LABEL[key] ||
        key.replace(/_/g, " ").charAt(0).toUpperCase() + key.replace(/_/g, " ").slice(1);
      L.push(`- **${lab}:** ${Array.isArray(value) ? value.join(" · ") : value}`);
    }
  }
  L.push(
    "",
    "Everything above is read out of the saves themselves, in this browser or " +
      "on this machine — nothing is uploaded. A field the tool cannot verify is left out " +
      "rather than guessed, and every progress section is a FLOOR: it reports what the " +
      "saves prove, never what they merely suggest.",
    "",
    `_Generated ${stamp(Math.trunc(now.getTime() / 1000))} by sl2-analyzer._`,
    "",
    "</details>",
    "",
  );
  return L;
}

/** Acronyms --meta would otherwise mangle. Mirror of Python's META_LABEL. */
const META_LABEL = {
  dlc: "DLC",
  os: "OS",
  cpu: "CPU",
  gpu: "GPU",
  ram: "RAM",
  mangohud: "MangoHud",
  gamemode: "GameMode",
  dxvk: "DXVK",
  fps: "FPS",
  hdr: "HDR",
  url: "URL",
  id: "ID",
};
