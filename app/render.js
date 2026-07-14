// Render a parsed save into DOM cards styled as that game's own status / level-up
// screen. The whole result wraps in a per-game theme class (t-ds1/ds2/ds3/er) that
// re-skins colour, type and ornament; each slot lays its attributes out in the game's
// on-screen order. Item/boss names are set via textContent, never innerHTML. No charts,
// no invented numbers — what the game shows, read from the file.

import { statGovernsFor, CAT_TITLE, CAT_ORDER, DS2_GREAT_SOULS, SRC, attrOrderFor, GAME_THEME, fmt, fmtPlaytime } from "./tables.js";
import { buildMarkdown } from "./markdown.js";

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

const section = (title, kids) => el("section", { class: "sec" }, el("h4", { text: title }), ...kids);
const itemList = (items) => el("ul", { class: "items" },
  ...items.map(([n, q]) => el("li", null, n + (q && q > 1 ? ` ×${q}` : ""))));

// ── Attributes, in the game's own level-up order. What each stat scales rides on
//    the row's hover title (the in-game panel shows it inline; we keep it quiet). ──
function orderedAttrKeys(game, stats) {
  const order = attrOrderFor(game);
  if (!order.length) return Object.keys(stats);
  const inOrder = order.filter((k) => k in stats);
  const rest = Object.keys(stats).filter((k) => !inOrder.includes(k));
  return [...inOrder, ...rest];
}

function attrPanel(ch) {
  const gov = statGovernsFor(ch.game);
  const rows = orderedAttrKeys(ch.game, ch.stats).map((k) => {
    const row = el("div", { class: "arow" },
      el("span", { class: "an", text: k }),
      el("span", { class: "av", text: fmt(ch.stats[k]) }));
    if (gov.has(k)) row.setAttribute("title", `${k} — ${gov.get(k)}`);
    return row;
  });
  return el("div", { class: "attrs" }, ...rows);
}

// ── The numeric HUD line under the attributes: souls/runes, memory, time, deaths —
//    the counters the game keeps on its status screen, each shown only when read. ──
function metaBlock(ch) {
  const out = [];
  const stat = (label, val, accent) => out.push(el("div", { class: "mrow" + (accent ? " accent" : "") },
    el("span", { class: "ml", text: label }), el("span", { class: "mv", text: fmt(val) })));
  if (ch.souls != null) stat(ch.game === "er" ? "Runes Held" : "Souls Held", ch.souls, true);
  if (ch.soul_memory != null) stat("Soul Memory", ch.soul_memory, true);
  if (ch.humanity != null) stat("Humanity", ch.humanity);
  if (ch.play_time) stat("Play Time", fmtPlaytime(ch.play_time));
  if (ch.deaths != null) stat("Deaths", ch.deaths);
  if (ch.hollow_lvl) stat("Hollowing", ch.hollow_lvl);
  return out.length ? el("div", { class: "meta" }, ...out) : null;
}

function statusTop(slot, ch) {
  const sub = [ch.klass, ch.covenant, ch.gender,
    ch.ng_plus != null ? (ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`) : null]
    .filter(Boolean).join("  ·  ");
  const titleblock = el("div", { class: "titleblock" },
    el("div", { class: "eyebrow", text: `Slot ${slot}` }),
    el("h3", { class: "cname", text: ch.name }));
  if (sub) titleblock.append(el("div", { class: "subid", text: sub }));
  const kids = [titleblock];
  if (ch.level != null) {
    kids.push(el("div", { class: "levelbadge" + (ch.tier === "full" ? "" : " dim") },
      el("div", { class: "lv", text: fmt(ch.level) }),
      el("div", { class: "lvl", text: ch.game === "er" ? "Level" : "Soul Level" })));
  }
  return el("div", { class: "status-top" }, ...kids);
}

function characterCard(slot, ch) {
  const card = el("article", { class: "status" });
  card.append(statusTop(slot, ch));
  card.append(el("span", { class: `badge ${ch.tier}`, text: ch.tier === "full" ? "full data" : "inventory only" }));

  if (Object.keys(ch.stats).length) card.append(attrPanel(ch));
  else if (ch.tier === "inventory") card.append(el("p", { class: "note", text: "No attributes for this slot. Its stat block did not check out — an unrecognised patch, or an edited save — and a wrong number is worse than none. Everything below is still read straight from the file." }));

  const meta = metaBlock(ch);
  if (meta) card.append(meta);

  if (ch.boss_souls && ch.boss_souls.length) {
    card.append(section(ch.game === "er" ? "Remembrances Held" : "Boss Souls Held", [
      el("p", { class: "hint", text: ch.game === "er" ? "Major bosses dead. The remembrance is still unspent." : "Bosses dead. The soul is still in your pack, so the kill is certain." }),
      itemList(ch.boss_souls)]));
  }
  if (ch.key_items && ch.key_items.length) card.append(section("Key Items", [el("p", { class: "hint", text: "Progress. The keys and items that open up the world." }), itemList(ch.key_items)]));

  if (ch.bonfires && ch.bonfires.length) {
    card.append(section(`Bonfires Discovered (${ch.bonfires.length})`, [
      el("p", { class: "hint", text: "Every bonfire you have lit. A floor on how far you got." }),
      el("ul", { class: "items cols" }, ...ch.bonfires.map((b) => el("li", { text: b })))]));
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    const list = el("ul", { class: "items bosses" });
    for (const [boss, srcs] of Object.entries(ch.bosses)) {
      list.append(el("li", null, boss, " ", ...srcs.map((s) => el("span", { class: `tag ${s}`, text: SRC[s] }))));
    }
    card.append(section(`Bosses Defeated (${Object.keys(ch.bosses).length})`, [
      el("p", { class: "hint", text: "A floor. Read from held souls, defeat flags, and points you could not have passed otherwise. A soul you already spent, with no flag, can still be missing." }), list]));
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
  if (ch.unknown_count) card.append(el("p", { class: "note", text: `${ch.unknown_count} item(s) carried IDs the name table does not have — upgraded or infused variants — and were left out.` }));
  return card;
}

function copyButton(result, filename) {
  const btn = el("button", { class: "btn btn-ghost copy", type: "button", text: "Copy Markdown" });
  btn.addEventListener("click", async () => {
    const md = buildMarkdown(result, filename);
    let ok = true;
    try { await navigator.clipboard.writeText(md); }
    catch {
      const ta = el("textarea"); ta.value = md; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); } catch { ok = false; }
      ta.remove();
    }
    btn.textContent = ok ? "Copied" : "Copy Markdown";
    setTimeout(() => { btn.textContent = "Copy Markdown"; }, 1600);
  });
  return btn;
}

/** Build the DOM for a parsed save result, themed to the detected game. */
export function renderSave(result, filename) {
  const theme = GAME_THEME[result.game] || "ds1";
  const root = el("div", { class: `result t-${theme}` });
  root.append(el("div", { class: "gamebar" },
    el("div", { class: "gb-left" },
      el("div", { class: "gb-eyebrow", text: "Status" }),
      el("h2", { text: result.title }),
      el("p", { class: "src", text: filename || "" })),
    el("div", { class: "gb-right" },
      el("span", { class: "count", text: `${result.characters.length} character${result.characters.length === 1 ? "" : "s"}` }),
      copyButton(result, filename))));
  if (!result.characters.length) root.append(el("p", { class: "note", text: "No populated character slots found." }));
  for (const { slot, ch } of result.characters) root.append(characterCard(slot, ch));
  root.append(el("p", { class: "foot", text: "All of it read from the save, in your browser. The progress sections are a floor: a spent soul or an unmapped flag can hide a kill. It never invents one." }));
  return root;
}
