// Render a parsed save into DOM cards — the visual view (the Markdown view lives in
// markdown.js and the Copy button here reuses it). Website-only extras the Markdown
// can't show: KPI stat tiles, attribute magnitude bars, and an SVG build radar.
// Item/boss names are set via textContent, never innerHTML.

import { STAT_ABBR, CAT_TITLE, CAT_ORDER, DS2_GREAT_SOULS, SRC, guessBuild, fmt } from "./tables.js";
import { buildMarkdown } from "./markdown.js";

const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  if (props) for (const k in props) {
    if (k === "class") n.className = props[k];
    else if (k === "text") n.textContent = props[k];
    else n.setAttribute(k, props[k]);
  }
  for (const c of kids.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
}
function svg(tag, props, ...kids) {
  const n = document.createElementNS(SVGNS, tag);
  if (props) for (const k in props) n.setAttribute(k, props[k]);
  for (const c of kids.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
}

const section = (title, kids) => el("section", { class: "sec" }, el("h4", { text: title }), ...kids);
const itemList = (items) => el("ul", { class: "items" },
  ...items.map(([n, q]) => el("li", null, n + (q && q > 1 ? ` ×${q}` : ""))));

// ── KPI tiles: the headline numbers as hero stats (no plot). ─────────────────
function kpiRow(ch) {
  const tiles = [];
  const tile = (label, val, accent) => tiles.push(el("div", { class: "kpi" + (accent ? " accent" : "") },
    el("div", { class: "kv", text: fmt(val) }), el("div", { class: "kl", text: label })));
  if (ch.soul_memory != null) tile("Soul Memory", ch.soul_memory, true);
  if (ch.souls != null) tile(ch.game === "er" ? "Runes Held" : "Souls Held", ch.souls);
  if (ch.hp != null) tile("Max HP", ch.hp);
  if (ch.stamina != null) tile("Stamina", ch.stamina);
  if (ch.bosses) tile("Bosses Defeated", Object.keys(ch.bosses).length, true);
  if (ch.bonfires) tile("Bonfires", ch.bonfires.length);
  return tiles.length ? el("div", { class: "kpis" }, ...tiles) : null;
}

// ── Attribute magnitude bars (single hue, value labels, baseline-anchored). ──
function statBars(stats) {
  const keys = Object.keys(stats);
  const MAX = 99;
  const rows = keys.map((k) => {
    const v = stats[k] || 0;
    const pct = Math.max(2, Math.min(100, (v / MAX) * 100));
    return el("div", { class: "bar-row" },
      el("span", { class: "bar-label", title: k, text: STAT_ABBR[k] || k.slice(0, 3).toUpperCase() }),
      el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${pct}%` })),
      el("span", { class: "bar-val", text: fmt(v) }));
  });
  return el("div", { class: "bars" }, ...rows);
}

// ── Build radar: single-series polygon over the attributes (full tier only). ─
function statRadar(stats) {
  const keys = Object.keys(stats);
  const n = keys.length;
  if (n < 3) return null;
  const SIZE = 240, C = SIZE / 2, R = C - 34, MAX = 99;
  const ang = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const at = (i, r) => [C + Math.cos(ang(i)) * r, C + Math.sin(ang(i)) * r];
  const kids = [];
  for (const f of [0.33, 0.66, 1]) {
    kids.push(svg("polygon", { points: keys.map((_, i) => at(i, R * f).map((x) => x.toFixed(1)).join(",")).join(" "), class: "radar-grid" }));
  }
  keys.forEach((k, i) => {
    const [x, y] = at(i, R);
    kids.push(svg("line", { x1: C, y1: C, x2: x.toFixed(1), y2: y.toFixed(1), class: "radar-grid" }));
    const [lx, ly] = at(i, R + 15);
    kids.push(svg("text", { x: lx.toFixed(1), y: ly.toFixed(1), class: "radar-axis",
      "text-anchor": Math.abs(lx - C) < 4 ? "middle" : lx > C ? "start" : "end", "dominant-baseline": "middle" },
      STAT_ABBR[k] || k.slice(0, 3).toUpperCase()));
  });
  kids.push(svg("polygon", { points: keys.map((k, i) => at(i, R * ((stats[k] || 0) / MAX)).map((x) => x.toFixed(1)).join(",")).join(" "), class: "radar-shape" }));
  keys.forEach((k, i) => {
    const [x, y] = at(i, R * ((stats[k] || 0) / MAX));
    kids.push(svg("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: 2.5, class: "radar-dot" }));
  });
  return el("div", { class: "radar-wrap" }, svg("svg", { viewBox: `0 0 ${SIZE} ${SIZE}`, class: "radar", role: "img", "aria-label": "attribute radar" }, ...kids));
}

function facts(ch) {
  const rows = [];
  const add = (label, val) => rows.push(el("div", { class: "fact" }, el("span", { class: "fk", text: label }), el("span", { class: "fv", text: val })));
  if (ch.level != null) add(ch.game === "er" ? "Level" : "Soul Level", fmt(ch.level));
  if (ch.klass) add("Class", ch.klass);
  if (ch.covenant) add("Covenant", ch.covenant);
  if (ch.ng_plus != null) add("Playthrough", ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`);
  if (ch.humanity != null) add("Humanity", fmt(ch.humanity));
  if (ch.hollow_lvl) add("Hollowing", fmt(ch.hollow_lvl));
  const build = guessBuild(ch.stats);
  if (build) add("Build", build);
  return rows.length ? el("div", { class: "facts" }, ...rows) : null;
}

function characterCard(slot, ch) {
  const card = el("article", { class: "char" });
  card.append(el("div", { class: "char-head" },
    el("h3", null, el("span", { class: "slot", text: `Slot ${slot}` }), el("span", { class: "cname", text: ch.name })),
    el("span", { class: `badge ${ch.tier}`, text: ch.tier === "full" ? "full data" : "inventory only" })));

  const kpis = kpiRow(ch);
  if (kpis) card.append(kpis);
  const f = facts(ch);
  if (f) card.append(f);

  if (Object.keys(ch.stats).length) {
    card.append(section("Attributes", [el("div", { class: "attr-grid" }, statBars(ch.stats), statRadar(ch.stats))]));
  } else if (ch.tier === "inventory") {
    card.append(el("p", { class: "note", text: "Attributes not shown for this slot — its stat block did not validate (unrecognised patch or edited save). A wrong number is worse than none; inventory and progress below are read directly." }));
  }

  if (ch.boss_souls && ch.boss_souls.length) {
    card.append(section(ch.game === "er" ? "Remembrances Held" : "Boss Souls Held", [
      el("p", { class: "hint", text: ch.game === "er" ? "major bosses defeated, not yet traded" : "bosses defeated, soul not yet consumed" }),
      itemList(ch.boss_souls)]));
  }
  if (ch.key_items && ch.key_items.length) card.append(section("Key Items", [el("p", { class: "hint", text: "progress / areas & shortcuts unlocked" }), itemList(ch.key_items)]));

  if (ch.bonfires && ch.bonfires.length) {
    card.append(section(`Bonfires Discovered (${ch.bonfires.length})`, [
      el("p", { class: "hint", text: "areas reached — a floor on progress" }),
      el("ul", { class: "items cols" }, ...ch.bonfires.map((b) => el("li", { text: b })))]));
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    const list = el("ul", { class: "items bosses" });
    for (const [boss, srcs] of Object.entries(ch.bosses)) {
      list.append(el("li", null, boss, " ", ...srcs.map((s) => el("span", { class: `tag ${s}`, text: SRC[s] }))));
    }
    card.append(section(`Bosses Defeated (${Object.keys(ch.bosses).length})`, [
      el("p", { class: "hint", text: "a floor — from defeat flags, held boss souls & progression; a consumed, ungated soul may still be missing" }), list]));
  }

  const invCard = el("div", { class: "inv" });
  let any = false;
  for (const cat of CAT_ORDER) {
    const items = ch.inv[cat];
    if (!items || !items.length) continue;
    if (cat === "bosssouls") {
      for (const [title, group] of [["Great Boss Souls", items.filter((it) => DS2_GREAT_SOULS.has(it[0]))],
                                     ["Boss Souls", items.filter((it) => !DS2_GREAT_SOULS.has(it[0]))]]) {
        if (group.length) { invCard.append(el("h5", { text: title }), itemList(group)); any = true; }
      }
    } else { invCard.append(el("h5", { text: CAT_TITLE[cat] || cat }), itemList(items)); any = true; }
  }
  if (any) card.append(section("Inventory", [invCard]));
  if (ch.unknown_count) card.append(el("p", { class: "note", text: `${ch.unknown_count} inventory item(s) had IDs not in the name database (upgraded / infused variants) and were omitted.` }));
  return card;
}

function copyButton(result, filename) {
  const btn = el("button", { class: "btn btn-ghost copy", type: "button", text: "⧉ Copy Markdown" });
  btn.addEventListener("click", async () => {
    const md = buildMarkdown(result, filename);
    try { await navigator.clipboard.writeText(md); btn.textContent = "✓ Copied"; }
    catch {
      const ta = el("textarea"); ta.value = md; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); btn.textContent = "✓ Copied"; } catch { btn.textContent = "Copy failed"; }
      ta.remove();
    }
    setTimeout(() => { btn.textContent = "⧉ Copy Markdown"; }, 1600);
  });
  return btn;
}

/** Build the DOM for a parsed save result. */
export function renderSave(result, filename) {
  const root = el("div", { class: "result" });
  root.append(el("div", { class: "gamebar" },
    el("div", { class: "gb-left" }, el("h2", { text: result.title }), el("p", { class: "src", text: filename || "" })),
    el("div", { class: "gb-right" },
      el("span", { class: "count", text: `${result.characters.length} character${result.characters.length === 1 ? "" : "s"}` }),
      copyButton(result, filename))));
  if (!result.characters.length) root.append(el("p", { class: "note", text: "No populated character slots found." }));
  for (const { slot, ch } of result.characters) root.append(characterCard(slot, ch));
  root.append(el("p", { class: "foot", text: "Everything above is read directly from the save in your browser. Progress sections are a floor — consumed boss souls and untracked flags can hide kills, never invent them." }));
  return root;
}
