// Render a parsed save as that game's own in-game Level-Up screen: a stone-framed
// panel with a title bar, a left column (level, souls, the attributes), and right-side
// panels (DS2's derived Attributes block; a Character panel for the rest). Only values
// the save proves are shown — fields the screen has but we can't verify (weapon AR,
// resistances, bonuses) are omitted, never faked. Names via textContent, never innerHTML.

import { STAT_ABBR, statGovernsFor, statCapsFor, CAT_TITLE, CAT_ORDER, DS2_GREAT_SOULS, SRC, attrOrderFor, GAME_THEME, DS2_GAMES, ds1DerivedStats, ds2DerivedStats, ds3DerivedStats, fmt, fmtPlaytime, countDupes } from "./tables.js";
import { buildMarkdown } from "./markdown.js";
import { buildJsonText } from "./jsonout.js";

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
  if (!DS2_GAMES.has(ch.game)) {
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

/** DS1's derived panel: the two values that are pure attribute functions. */
function ds1DerivedPanel(ch) {
  const d = ds1DerivedStats(ch.stats);
  return el("div", { class: "lp" },
    el("div", { class: "lp-h", text: "Derived (base)" }),
    el("div", { class: "lp-rows" },
      statRow("load", "Attunement Slots", d.slots),
      statRow("load", "Equip Load", d.equip_load.toFixed(1))),
    el("p", { class: "lp-note", text: "Base values from attributes — before rings and equipment. Stamina and Max HP are read from the save above; poise is armour-only and item discovery needs covenant/gear, so both are left off." }));
}

/**
 * Attribute Scaling: what each stat governs and where it soft-caps, beside the
 * character's own value. The CLI has printed this for a while; on the web it only
 * existed as a title= tooltip, which touch can't reach and a keyboard can't focus.
 *
 * These are documented game mechanics, NOT values read from the save, and the note
 * says so — the same reason the CLI labels the section that way.
 */
function scalingPanel(ch) {
  const gov = statGovernsFor(ch.game), caps = statCapsFor(ch.game);
  const rows = [];
  for (const k of orderedAttrKeys(ch.game, ch.stats)) {
    const g = gov.get(k), c = caps.get(k);
    if (!g && !c) continue;
    rows.push(el("div", { class: "lp-scale" },
      el("div", { class: "sc-h" },
        el("span", { class: "sc-n", text: k }),
        el("span", { class: "sc-v", text: fmt(ch.stats[k]) })),
      g ? el("div", { class: "sc-g", text: g }) : null,
      c ? el("div", { class: "sc-c", text: capFirstLetter(c) }) : null));
  }
  if (!rows.length) return null;
  // Folded shut by default. It is a reference table, not save data, and left open it
  // is taller than the whole level-up screen it sits beside. <details> also gives
  // keyboard open/close for free.
  return el("details", { class: "lp lp-fold" },
    el("summary", { class: "lp-h", text: "Attribute Scaling" }),
    el("div", { class: "lp-foldbody" }, ...rows,
      el("p", { class: "lp-note", text: "What each attribute does in this game and where it soft-caps — a mechanics reference, not a value read from your save. Your own number is on the right of each row." })));
}
const capFirstLetter = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Character panel: identity + counters that aren't in the left column. */
function characterPanel(ch) {
  const rows = [];
  if (ch.klass) rows.push(statRow(null, "Class", ch.klass));
  if (ch.covenant) rows.push(statRow(null, "Covenant", ch.covenant));
  if (ch.gender) rows.push(statRow(null, "Gender", ch.gender));
  if (ch.ng_plus != null) rows.push(statRow(null, "Playthrough", ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`));
  if (ch.embered != null) rows.push(statRow(null, "Embered", ch.embered ? "Yes (+30% HP)" : "No (hollow)"));
  if (ch.play_time) rows.push(statRow(null, "Play Time", fmtPlaytime(ch.play_time)));
  if (ch.deaths != null) rows.push(statRow(null, "Deaths", ch.deaths));
  if (ch.hollow_lvl) rows.push(statRow(null, "Hollowing", ch.hollow_lvl));
  if (ch.lords) {
    // "N of 4" — a closed set, so the denominator is real. See lords_line / lordsLine.
    const named = ch.lords.named && ch.lords.named.length ? ` (${ch.lords.named.join(" · ")})` : "";
    const n = ch.lords.placed == null ? (ch.lords.named || []).length : ch.lords.placed;
    rows.push(statRow(null, "Cinders Placed", `${n} of ${ch.lords.total}${named}`));
  }
  return rows.length ? el("div", { class: "lp" }, el("div", { class: "lp-h", text: "Character" }), ...rows) : null;
}

function levelUpScreen(slot, ch) {
  const rightPanels = [];
  if (DS2_GAMES.has(ch.game) && Object.keys(ch.stats).length) rightPanels.push(ds2DerivedPanel(ch));
  if (ch.game === "ds3" && Object.keys(ch.stats).length) rightPanels.push(ds3DerivedPanel(ch));
  if ((ch.game === "dsr" || ch.game === "ptde") && Object.keys(ch.stats).length) rightPanels.push(ds1DerivedPanel(ch));
  const cp = characterPanel(ch);
  if (cp) rightPanels.push(cp);
  const sp = Object.keys(ch.stats).length ? scalingPanel(ch) : null;
  if (sp) rightPanels.push(sp);

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

/**
 * "22 of 77" plus a bar, for bonfires only. The bonfire tables are COMPLETE for
 * every game that has one (DS3 77/77, DS2 77/77, DS1 43/43), so the denominator is
 * a real total rather than "however many we happened to map". Deliberately not done
 * for bosses: those tables are a mapped subset (DS2 has 6 of ~41), so a fraction
 * there would state a roster the data does not support.
 * @returns the heading text, and a bar element or null when there is no total.
 */
function bonfireProgress(count, total, suffix) {
  const usable = total > 0 && count <= total;
  const title = usable
    ? `Bonfires Discovered (${count} of ${total}${suffix})`
    : `Bonfires Discovered (${count}${suffix})`;
  if (!usable) return [title, null];
  const pct = Math.round((count / total) * 100);
  const bar = el("div", { class: "pbar", role: "progressbar", "aria-valuenow": String(count),
    "aria-valuemin": "0", "aria-valuemax": String(total),
    "aria-label": `${count} of ${total} bonfires discovered` },
    el("span", { class: "pbar-f", style: `width:${pct}%` }));
  return [title, bar];
}

function characterCard(slot, ch, bonfireTotal) {
  const card = el("article", { class: "status" });
  card.append(levelUpScreen(slot, ch));

  // Boss souls get their own panel only where the inventory has no boss-souls
  // category (DS2 and DS3 do) — otherwise the same list would render twice.
  if (ch.boss_souls && ch.boss_souls.length && !(ch.inv.bosssouls || []).length) {
    card.append(section(ch.game === "er" ? "Remembrances Held" : "Boss Souls Held", [
      el("p", { class: "hint", text: ch.game === "er" ? "Major bosses dead. The remembrance is still unspent." : "Bosses dead. The soul is still in your pack, so the kill is certain." }),
      itemList(ch.boss_souls)]));
  }
  if (ch.key_items && ch.key_items.length) card.append(section("Key Items", [el("p", { class: "hint", text: "Progress. The keys and items that open up the world." }), itemList(ch.key_items)]));

  // DS2 keeps the flat list for the boss-gate logic; the grouped view wins when the
  // area table resolved it.
  if (ch.bonfires && ch.bonfires.length && !(ch.bonfire_areas && ch.bonfire_areas.length)) {
    const [title, bar] = bonfireProgress(ch.bonfires.length, bonfireTotal, "");
    card.append(section(title, [
      el("p", { class: "hint", text: "Every bonfire you have lit. A floor on how far you got." }),
      bar,
      el("ul", { class: "items cols" }, ...ch.bonfires.map((b) => el("li", { text: b })))]));
  }
  if (ch.bonfire_areas && ch.bonfire_areas.length) {
    const lit = ch.bonfire_areas.reduce((s, [, c]) => s + c, 0);
    const n = ch.bonfire_areas.filter(([, c]) => c).length, areas = ch.bonfire_areas.length;
    const [title, bar] = bonfireProgress(lit, bonfireTotal, `, in ${n} of ${areas} areas`);
    card.append(section(title, [
      el("p", { class: "hint", text: ch.game === "dsr" || ch.game === "ptde" ? "Each bonfire's own record, with how far it is kindled. A floor on how far you got." : DS2_GAMES.has(ch.game) ? "Every bonfire the save records as discovered, by area. A floor on how far you got." : "Bonfires lit, inferred from each area's flag bits. A floor on how far you got." }),
      bar,
      el("ul", { class: "items cols" }, ...ch.bonfire_areas.map(([name, c, named, tot, missing]) => {
        const li = el("li", null, el("span", { class: "slot", text: `${name}: ${c}/${tot} ` }));
        if (named && named.length) {
          li.append(named.join(", "));
          // Only a started area lists what is left; an untouched one would print
          // the whole game back at you.
          if (missing && missing.length) li.append(el("span", { class: "hint", text: ` missing: ${missing.join(" · ")}` }));
        }
        return li;
      }))]));
  }
  if (ch.covenants && Object.keys(ch.covenants).length) {
    const list = el("ul", { class: "items" });
    for (const [cov, w] of Object.entries(ch.covenants)) {
      list.append(el("li", null, el("span", { class: "slot", text: `${cov}: ` }), w.join(", ")));
    }
    const covN = Object.keys(ch.covenants).length;
    const covBits = [el("p", { class: "hint", text: "Covenants discovered — a floor. The covenant currently worn is in the Character panel." }), list];
    if (ch.covenants_missing && ch.covenants_missing.length) {
      covBits.push(el("p", { class: "hint", text: `Not found yet: ${ch.covenants_missing.join(" · ")}.` }));
    }
    card.append(section(`Covenants Found (${ch.covenant_total ? `${covN} of ${ch.covenant_total}` : covN})`, covBits));
  }
  if (ch.pickups && ch.pickups.length) {
    const got = ch.pickups.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.pickups.reduce((s2, [, , t]) => s2 + t, 0);
    const pct = total ? Math.round((got / total) * 100) : 0;
    const bar = el("div", { class: "pbar", role: "progressbar", "aria-valuenow": String(got),
      "aria-valuemin": "0", "aria-valuemax": String(total),
      "aria-label": `${got} of ${total} tracked world items picked up` },
      el("span", { class: "pbar-f", style: `width:${pct}%` }));
    const list = el("ul", { class: "items cols" }, ...ch.pickups.map(([area, c, tot, missing]) => {
      const li = el("li", null, el("span", { class: "slot", text: `${area}: ${c}/${tot} ` }));
      // Same rule as bonfires — a started area lists what is left in it.
      if (c && missing && missing.length) {
        li.append(el("span", { class: "hint", text: ` missing: ${countDupes(missing).join(" · ")}` }));
      }
      return li;
    }));
    card.append(section(`Items Collected (${got} of ${total} tracked)`, [
      el("p", { class: "hint", text: "One-off world items picked up, from each area's pickup flags. Only the areas whose flag group is mapped are counted — an area not listed is untracked, not empty." }),
      bar, list]));
  }
  if (ch.questlines && Object.keys(ch.questlines).length) {
    const list = el("ul", { class: "items" });
    for (const [src, rw] of Object.entries(ch.questlines)) {
      list.append(el("li", null, el("span", { class: "slot", text: `${src}: ` }), rw.join(", ")));
    }
    card.append(section("Rewards Obtained", [
      el("p", { class: "hint", text: "One-off rewards from NPCs, invaders and landmark pickups — a progress floor." }), list]));
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    const list = el("ul", { class: "items bosses" });
    for (const [boss, srcs] of Object.entries(ch.bosses)) {
      list.append(el("li", null, boss, " ", ...srcs.map((s) => el("span", { class: `tag ${s}`, text: SRC[s] }))));
    }
    const bossN = Object.keys(ch.bosses).length;
    const bossBits = [el("p", { class: "hint", text: "A floor. Read from held souls, defeat flags, points you could not have passed otherwise, and NG+ clears (reaching NG+ proves every mandatory boss dead). A soul you already spent, with no flag, can still be missing." }), list];
    const avail = ch.bosses_available || [];
    const rest = (ch.bosses_missing || []).filter((b) => !avail.includes(b));
    if (avail.length) {
      bossBits.push(el("p", { class: "hint", text: `Available now — every prerequisite dead and the area already reached (the game's fixed route, not this save): ${avail.join(" · ")}.` }));
    }
    if (rest.length) {
      bossBits.push(el("p", { class: "hint", text: `No evidence yet${avail.length ? ", and behind something else" : ""}: ${rest.join(" · ")}.` }));
    }
    card.append(section(`Bosses Defeated (${ch.boss_total ? `${bossN} of ${ch.boss_total} tracked` : bossN})`, bossBits));
  }

  const eqWeapons = ch.equipped_weapons || {}, eqArmor = ch.equipped_armor || {},
    eqRings = ch.equipped_rings || [], eqAmmo = ch.equipped_ammo || [];
  if (Object.keys(eqWeapons).length || Object.keys(eqArmor).length || eqRings.length || eqAmmo.length) {
    const list = el("ul", { class: "items" });
    for (const [slot, name] of Object.entries(eqWeapons)) {
      list.append(el("li", null, el("span", { class: "slot", text: `${slot}: ` }), name));
    }
    for (const [slot, name] of Object.entries(eqArmor)) {
      list.append(el("li", null, el("span", { class: "slot", text: `${slot}: ` }), name));
    }
    if (eqRings.length) {
      list.append(el("li", null, el("span", { class: "slot", text: "Rings: " }), eqRings.join(", ")));
    }
    if (eqAmmo.length) {
      list.append(el("li", null, el("span", { class: "slot", text: "Ammo: " }), eqAmmo.join(", ")));
    }
    card.append(section("Equipped", [
      el("p", { class: "hint", text: "Worn gear read from the equip slots." }), list]));
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

/**
 * Hand the browser a generated file. Shared by both download buttons so the blob/anchor
 * dance exists once.
 * @param {string} text the file contents
 * @param {string} mime
 * @param {string} name the download filename
 */
function saveText(text, mime, name) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  // Revoke on the next tick — revoking synchronously can beat the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** The save's basename, for naming whatever we hand back. */
const stem = (filename) => (filename || "save").replace(/\.sl2$/i, "");

/** Save the same Markdown to a file, for anyone who wants it on disk not on the clipboard. */
function downloadButton(result, filename) {
  const btn = el("button", { class: "btn btn-ghost", type: "button", text: "Download .md" });
  btn.addEventListener("click", () => {
    saveText(buildMarkdown(result, filename), "text/markdown;charset=utf-8", `${stem(filename)}.md`);
  });
  return btn;
}

/**
 * The same data as JSON, against the published schema — for anything that is going to be
 * read by a program rather than a person. Byte-identical to what the CLI writes.
 */
function downloadJsonButton(result, filename) {
  const btn = el("button", { class: "btn btn-ghost", type: "button", text: "Download .json" });
  btn.addEventListener("click", () => {
    saveText(buildJsonText(result, filename), "application/json;charset=utf-8", `${stem(filename)}.json`);
  });
  return btn;
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

/**
 * A tab strip for a save holding more than one character. A 10-slot mule otherwise
 * renders as ten full sheets stacked, which is unreadable — so all cards are built
 * (Copy Markdown still covers every one) and only the selected one is shown.
 *
 * Follows the ARIA tabs pattern: roving tabindex, arrows/Home/End move selection,
 * each panel labelled by its tab.
 */
function slotTabs(cards, chars, uid) {
  const tabs = chars.map(({ slot, ch }, i) => el("button", {
    class: "slot-tab", type: "button", role: "tab", id: `${uid}-t${i}`,
    "aria-controls": `${uid}-p${i}`, "aria-selected": i === 0 ? "true" : "false",
    tabindex: i === 0 ? "0" : "-1",
  }, el("span", { class: "st-n", text: ch.name || "(unnamed)" }),
     el("span", { class: "st-s", text: `Slot ${slot}${ch.level != null ? ` · Lv ${ch.level}` : ""}` })));

  const select = (i) => {
    tabs.forEach((t, j) => {
      t.setAttribute("aria-selected", j === i ? "true" : "false");
      t.setAttribute("tabindex", j === i ? "0" : "-1");
      if (j === i) t.classList.add("on"); else t.classList.remove("on");
    });
    cards.forEach((c, j) => { if (j === i) c.removeAttribute("hidden"); else c.setAttribute("hidden", ""); });
  };

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(i));
    t.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      let next = null;
      if (step != null) next = (i + step + tabs.length) % tabs.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = tabs.length - 1;
      if (next == null) return;
      e.preventDefault();
      select(next);
      tabs[next].focus();
    });
  });

  tabs[0].classList.add("on");
  cards.forEach((c, j) => { if (j) c.setAttribute("hidden", ""); });
  return el("div", { class: "slot-tabs", role: "tablist", "aria-label": "Characters in this save" }, ...tabs);
}

let uidSeq = 0;

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
      downloadButton(result, filename),
      downloadJsonButton(result, filename),
      copyButton(result, filename))));
  if (!result.characters.length) root.append(el("p", { class: "note", text: "No populated character slots found." }));

  const uid = `slot${++uidSeq}`;
  const cards = result.characters.map(({ slot, ch }) => characterCard(slot, ch, result.bonfireTotal));
  if (cards.length > 1) {
    cards.forEach((c, i) => {
      c.setAttribute("role", "tabpanel");
      c.setAttribute("id", `${uid}-p${i}`);
      c.setAttribute("aria-labelledby", `${uid}-t${i}`);
    });
    root.append(slotTabs(cards, result.characters, uid));
  }
  for (const c of cards) root.append(c);

  root.append(el("p", { class: "foot", text: "All of it read from the save, in your browser. The progress sections are a floor: a spent soul or an unmapped flag can hide a kill. It never invents one." }));
  return root;
}
