// Render a parsed save as that game's own in-game Level-Up screen: a stone-framed
// panel with a title bar, a left column (level, souls, the attributes), and right-side
// panels (DS2's derived Attributes block; a Character panel for the rest). Only values
// the save proves are shown — fields the screen has but we can't verify (weapon AR,
// resistances, bonuses) are omitted, never faked. Names via textContent, never innerHTML.

import { STAT_ABBR, statGovernsFor, CAT_TITLE, CAT_ORDER, DS2_GREAT_SOULS, SRC, attrOrderFor, GAME_THEME, ds2DerivedStats, ds3DerivedStats, fmt, fmtPlaytime } from "./tables.js";
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

// ── Item thumbnails (DS2 only): fextralife images keyed by base item name. These
//    are the one thing that leaves the browser — the privacy note says so. Names
//    carry infusion prefixes / "+N" the image map doesn't, so normalise before lookup.
const IMG_BASE = "https://darksouls2.wiki.fextralife.com/file/Dark-Souls-2/";
const INFUSIONS = ["Fire ", "Magic ", "Lightning ", "Dark ", "Poison ", "Bleed ", "Raw ", "Enchanted ", "Mundane "];
let imgResolve = () => null;
function makeImgResolver(images) {
  if (!images) return () => null;
  return (name) => {
    if (images[name]) return images[name];
    const base = name.replace(/ \+\d+$/, "");
    if (images[base]) return images[base];
    for (const p of INFUSIONS) if (base.startsWith(p)) return images[base.slice(p.length)] || null;
    return null;
  };
}
function itemLi(name, qty) {
  const li = el("li", null);
  const fn = imgResolve(name);
  if (fn) {
    const img = el("img", { class: "item-img", src: IMG_BASE + encodeURIComponent(fn), alt: "", loading: "lazy" });
    img.addEventListener("error", () => { img.remove(); li.classList.add("noimg"); });
    li.append(img);
  } else li.classList.add("noimg");
  li.append(name + (qty && qty > 1 ? ` ×${qty}` : ""));
  return li;
}
const itemList = (items) => el("ul", { class: "items" }, ...items.map(([n, q]) => itemLi(n, q)));

// ── Level-Up screen building blocks ─────────────────────────────────────────

/** A boxed sub-panel with a header label sitting on its top rule (the in-game box). */
const panel = (header, ...rows) => el("div", { class: "lp" },
  header ? el("div", { class: "lp-h", text: header }) : null, ...rows);

/** One value row: colour-coded icon square, label, right-aligned number. */
function statRow(icon, name, value, opts = {}) {
  const row = el("div", { class: "lp-row" + (opts.big ? " big" : "") },
    el("span", { class: "ic" + (icon ? " " + icon : "") }),
    el("span", { class: "nm", text: name }),
    el("span", { class: "vl", text: fmt(value) }));
  if (opts.title) row.setAttribute("title", opts.title);
  return row;
}

/** An attribute row: the dim ▲▼ arrow pair, abbreviation, value — the left column. */
function attrRow(fullName, value, title) {
  const row = el("div", { class: "lp-row attr" },
    el("span", { class: "arw", text: "▲▼" }),
    el("span", { class: "nm", text: STAT_ABBR[fullName] || fullName.slice(0, 3).toUpperCase() }),
    el("span", { class: "vl", text: fmt(value) }));
  if (title) row.setAttribute("title", title);
  return row;
}

/** Attribute keys in the game's own level-up order, unknowns pushed to the end. */
function orderedAttrKeys(game, stats) {
  const order = attrOrderFor(game);
  if (!order.length) return Object.keys(stats);
  const inOrder = order.filter((k) => k in stats);
  const rest = Object.keys(stats).filter((k) => !inOrder.includes(k));
  return [...inOrder, ...rest];
}

/** Left column: level + currency, then the attribute list. */
function leftColumn(slot, ch) {
  const rows = [];
  if (ch.level != null) rows.push(statRow(null, ch.game === "er" ? "Level" : "Lv", ch.level, { big: true }));
  if (ch.souls != null) rows.push(statRow("souls", ch.game === "er" ? "Runes" : "Souls", ch.souls));
  if (ch.soul_memory != null) rows.push(statRow("mem", "Soul Memory", ch.soul_memory));
  if (ch.humanity != null) rows.push(statRow("hp", "Humanity", ch.humanity));
  // Max HP/FP live in the DS2 derived panel for DS2; every other game shows them here.
  if (ch.game !== "ds2sotfs") {
    if (ch.hp != null) rows.push(statRow("hp", "Max HP", ch.hp));
    if (ch.fp != null) rows.push(statRow("mag", "Max FP", ch.fp));
  }
  const head = el("div", { class: "lp" }, ...rows);
  const gov = statGovernsFor(ch.game);
  const keys = orderedAttrKeys(ch.game, ch.stats);
  if (keys.length) {
    head.append(el("div", { class: "lp-div" }));
    for (const k of keys) head.append(attrRow(k, ch.stats[k], gov.has(k) ? `${k} — ${gov.get(k)}` : null));
  } else if (ch.tier === "inventory") {
    head.append(el("p", { class: "lp-note", text: "Attributes for this slot did not check out — an unrecognised patch or an edited save. A wrong number is worse than none, so they are left off. Everything below is still read from the file." }));
  }
  return head;
}

// ── DS2 derived Attributes panel — the middle block of the DS2 level-up screen.
//    Only the pure-attribute values verified byte-exact; the gear/weapon-dependent
//    fields the screen also shows (BNS, RES, Phys DEF, weapon AR, VS) are omitted. ──
function ds2DerivedPanel(ch) {
  const d = ds2DerivedStats(ch.stats);
  const colA = el("div", { class: "lp-rows" },
    ...(ch.hp != null ? [statRow("hp", "HP", ch.hp)] : []),
    statRow("stam", "Stamina", d.stamina),
    statRow("load", "Equip Load", d.equip_load.toFixed(1)),
    statRow("load", "Attunement Slots", d.slots),
    statRow("atk", "ATK: Str", d.atk_str),
    statRow("atk", "ATK: Dex", d.atk_dex));
  const colB = el("div", { class: "lp-rows" },
    statRow("agl", d.iframes ? `AGL · ${d.iframes} i-fr` : "AGL", d.agility),
    statRow("poise", "Poise", d.poise.toFixed(1)),
    statRow("mag", "Magic DEF", d.magic_def),
    statRow("fire", "Fire DEF", d.fire_def),
    statRow("lit", "Lightning DEF", d.lightning_def),
    statRow("dark", "Dark DEF", d.dark_def));
  return el("div", { class: "lp" },
    el("div", { class: "lp-h", text: "Attributes (derived)" }),
    el("div", { class: "lp-cols" }, colA, colB),
    el("p", { class: "lp-note", text: "Base values computed from attributes — before rings & equipment. Fields the screen also shows but the save can't prove (weapon AR, bonuses, resistances, physical defence, cast speed) are omitted, not guessed." }));
}

// DS3 derived panel — the base attribute-only values the status screen shows that
// aren't already read from the save. See ds3DerivedStats.
function ds3DerivedPanel(ch) {
  const d = ds3DerivedStats(ch.stats);
  return el("div", { class: "lp" },
    el("div", { class: "lp-h", text: "Derived (base)" }),
    el("div", { class: "lp-rows" },
      statRow("load", "Attunement Slots", d.slots),
      statRow("load", "Equip Load", d.equip_load.toFixed(1)),
      statRow(null, "Item Discovery", d.item_discovery)),
    el("p", { class: "lp-note", text: "Base values from attributes — before rings, covenant and equipment. HP/FP/stamina are read from the save above; poise, defences and attack power are gear-scaled, so they're left off." }));
}

/** Character panel: identity + counters that aren't in the left column. */
function characterPanel(ch) {
  const rows = [];
  if (ch.klass) rows.push(statRow(null, "Class", ch.klass));
  if (ch.covenant) rows.push(statRow(null, "Covenant", ch.covenant));
  if (ch.gender) rows.push(statRow(null, "Gender", ch.gender));
  if (ch.ng_plus != null) rows.push(statRow(null, "Playthrough", ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`));
  if (ch.play_time) rows.push(statRow(null, "Play Time", fmtPlaytime(ch.play_time)));
  if (ch.deaths != null) rows.push(statRow(null, "Deaths", ch.deaths));
  if (ch.hollow_lvl) rows.push(statRow(null, "Hollowing", ch.hollow_lvl));
  return rows.length ? el("div", { class: "lp" }, el("div", { class: "lp-h", text: "Character" }), ...rows) : null;
}

function levelUpScreen(slot, ch) {
  const rightPanels = [];
  if (ch.game === "ds2sotfs" && Object.keys(ch.stats).length) rightPanels.push(ds2DerivedPanel(ch));
  if (ch.game === "ds3" && Object.keys(ch.stats).length) rightPanels.push(ds3DerivedPanel(ch));
  const cp = characterPanel(ch);
  if (cp) rightPanels.push(cp);

  const body = el("div", { class: "lvlup-body" + (rightPanels.length ? "" : " solo") },
    leftColumn(slot, ch),
    ...(rightPanels.length ? [el("div", { class: "lp-stack" }, ...rightPanels)] : []));

  return el("div", { class: "lvlup" },
    el("div", { class: "lvlup-bar" },
      el("span", { class: "lu-t", text: ch.name }),
      el("span", { class: "lu-r" },
        el("span", { class: "lu-s", text: `Slot ${slot}` }),
        el("span", { class: `badge ${ch.tier}`, text: ch.tier === "full" ? "full data" : "inventory only" }))),
    body);
}

function characterCard(slot, ch) {
  const card = el("article", { class: "status" });
  card.append(levelUpScreen(slot, ch));

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
  if (ch.bonfire_areas && ch.bonfire_areas.length) {
    const total = ch.bonfire_areas.reduce((s, [, c]) => s + c, 0), n = ch.bonfire_areas.length;
    card.append(section(`Bonfires Discovered (${total} across ${n} area${n !== 1 ? "s" : ""})`, [
      el("p", { class: "hint", text: "Bonfires lit, inferred from each area's flag bits. A floor on how far you got." }),
      el("ul", { class: "items cols" }, ...ch.bonfire_areas.map(([name, c]) => el("li", { text: `${name} (${c})` })))]));
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    const list = el("ul", { class: "items bosses" });
    for (const [boss, srcs] of Object.entries(ch.bosses)) {
      list.append(el("li", null, boss, " ", ...srcs.map((s) => el("span", { class: `tag ${s}`, text: SRC[s] }))));
    }
    card.append(section(`Bosses Defeated (${Object.keys(ch.bosses).length})`, [
      el("p", { class: "hint", text: "A floor. Read from held souls, defeat flags, points you could not have passed otherwise, and NG+ clears (reaching NG+ proves every mandatory boss dead). A soul you already spent, with no flag, can still be missing." }), list]));
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
  imgResolve = makeImgResolver(result.images);
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
