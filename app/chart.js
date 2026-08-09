/**
 * Mermaid flowcharts for the combined document. Port of sl2/chart.py.
 *
 * Two charts, and they mean two different things, which is why they are two charts.
 * The JOURNEY chart is real-world time: which game you played, in what order, by file
 * date. A RUN chart is save lineage inside one character: which snapshot came from
 * which, by what progress it contains. One picture would leave an arrow meaning "later
 * that month" in one place and "reloaded and forked" in another.
 */
import { achievements, children } from "./timeline.js";

/** Mermaid takes the label between double quotes, so the label may not contain one. */
export const mm = (text) => String(text).replaceAll('"', "#quot;");

export const label = (lines) => mm(lines.filter(Boolean).join("<br/>"));

/** "1 boss" / "2 bosses". A fresh save really does hold one of things, and a count
 *  that reads "1 bosses" makes the whole document look generated. */
export function plural(n, word) {
  const end = n === 1 ? "" : (/(s|x|ch)$/.test(word) ? "es" : "s");
  return `${n} ${word}${end}`;
}

/** H:MM:SS, or an em dash where the game stores no clock. */
export function hms(sec) {
  if (!sec) return "—";
  const s = Math.trunc(sec);
  const h = Math.trunc(s / 3600), m = Math.trunc((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * One run's snapshot tree. One node per save file, labelled with its reference number,
 * its level, and what it achieved that its parent had not. A node that achieved
 * nothing still appears — it is a real save — but it says so with nothing.
 */
export function runChart(rows, parents, restarts, refs) {
  const L = ["```mermaid", "flowchart TD"];
  const kids = children(parents);
  const multiSlot = rows.some((x) => x.slot !== rows[0].slot);
  rows.forEach((r, i) => {
    const prev = parents[i] === null ? null : rows[parents[i]];
    let head = `^${refs.get(r.path) ?? "?"} · ${hms(r.play_time)}`;
    if (r.slot && multiSlot) head += ` · slot ${r.slot}`;
    const lines = [head, `lv${r.level}`];
    if (restarts.has(i)) lines.splice(1, 0, "SEPARATE LINE");
    L.push(`  n${i}["${label(lines.concat(achievements(r, prev)))}"]`);
  });
  parents.forEach((p, i) => { if (p !== null) L.push(`  n${p} --> n${i}`); });
  // A leaf is where a line stopped; an ending is where it FINISHED. An ending outranks
  // a leaf when a node is both.
  const ends = [];
  rows.forEach((r, i) => {
    const had = parents[i] === null ? new Set() : new Set(rows[parents[i]].endings);
    if (r.endings.some((e) => !had.has(e))) ends.push(i);
  });
  const leaves = rows.map((_r, i) => i)
    .filter((i) => !kids.has(i) && !ends.includes(i));
  if (ends.length) {
    L.push("  classDef ending fill:#3a2a12,stroke:#c9a227,color:#f0e6d2,stroke-width:2px;");
    L.push("  class " + ends.map((i) => `n${i}`).join(",") + " ending;");
  }
  if (leaves.length) {
    L.push("  classDef leaf stroke-dasharray:4 3;");
    L.push("  class " + leaves.map((i) => `n${i}`).join(",") + " leaf;");
  }
  if (restarts.size) {
    L.push("  classDef restart stroke:#9a3b3b,stroke-width:2px;");
    L.push("  class " + [...restarts].sort((a, b) => a - b).map((i) => `n${i}`).join(",")
      + " restart;");
  }
  L.push("```");
  return L;
}

/**
 * The cross-game journey: one node per run, in the order they were played. Linked by
 * FILE DATE, the only clock the games share — a Dark Souls II play time and a Dark
 * Souls III one are unrelated numbers.
 */
export function journeyChart(runs, refs) {
  const L = ["```mermaid", "flowchart LR"];
  const items = [...runs.entries()];
  items.forEach(([key, rows], n) => {
    const name = JSON.parse(key)[1];
    const last = rows[rows.length - 1];
    const nums = [...new Set(rows.map((r) => refs.get(r.path) ?? 0))].sort((a, b) => a - b);
    const span = nums.length === 1 ? `^${nums[0]}` : `^${nums[0]}–^${nums[nums.length - 1]}`;
    const got = [`${rows.length} save${rows.length === 1 ? "" : "s"} · ${span}`,
      `lv${last.level} · ${hms(last.play_time)}`];
    // The carried set when one was worked out — a boss whose soul was spent is still a
    // boss killed, and the journey chart should say so.
    const known = last.carried_bosses || last.bosses;
    if (Object.keys(known).length) got.push(plural(Object.keys(known).length, "boss"));
    if (last.endings.length) {
      got.push("FINISHED: " + [...last.endings].sort().join(" · "));
    }
    L.push(`  r${n}["${label([`${last.title} — ${name}`].concat(got))}"]`);
  });
  for (let n = 1; n < items.length; n++) L.push(`  r${n - 1} --> r${n}`);
  L.push("```");
  return L;
}

/** The reference list every chart node points at. */
export function referenceList(order) {
  const L = ["## References", "",
    "_Every node above is one save file. Numbered earliest to latest by file date._", ""];
  for (const [num, name, mtime] of order) {
    L.push(`^${num}: [[${name}]] — _${stamp(mtime)}_`);
  }
  return L.concat([""]);
}

/** Local time, formatted the way Python's strftime writes it. */
export function stamp(mtime) {
  const d = new Date(mtime * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}`;
}
