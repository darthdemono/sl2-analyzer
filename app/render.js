// Render a parsed save into DOM cards — the visual equivalent of md_for_character.
// Same data, same guards (a field the tool can't read is simply absent). Item and
// boss names are set via textContent, never innerHTML.

const STAT_ABBR = { Vigor: "VGR", Endurance: "END", Vitality: "VIT", Attunement: "ATN",
  Strength: "STR", Dexterity: "DEX", Adaptability: "ADP", Intelligence: "INT", Faith: "FTH",
  Resistance: "RES", Luck: "LCK", Mind: "MND", Arcane: "ARC" };
const CAT_TITLE = { weapons: "Weapons", armors: "Armor", rings: "Rings", talismans: "Talismans",
  spells: "Spells", bolts: "Ammunition", upgrade: "Upgrade Materials", consumables: "Consumables",
  online: "Summon & Covenant Items", goods: "Consumables & Goods", ashes: "Ashes of War",
  emotes: "Gestures", bosssouls: "Boss Souls", items: "Items Owned" };
const CAT_ORDER = ["weapons", "armors", "rings", "talismans", "spells", "bolts", "upgrade",
  "consumables", "goods", "ashes", "online", "bosssouls", "emotes", "items"];
const DS2_GREAT_SOULS = new Set(["Old Witch Soul", "Old Dead One Soul", "Old King Soul", "Old Paledrake Soul"]);
const SRC = { flag: "confirmed", soul: "soul held", gate: "progression" };

function guessBuild(stats) {
  const keys = Object.keys(stats);
  if (!keys.length) return null;
  const g = (k) => stats[k] || 0;
  const phys = g("Strength") + g("Dexterity");
  const cast = g("Intelligence") + g("Faith") + g("Attunement");
  if (cast > phys) return "caster / hybrid (high INT/FTH/ATN)";
  if (g("Strength") >= g("Dexterity") + 6) return "strength-focused melee";
  if (g("Dexterity") >= g("Strength") + 6) return "dexterity-focused melee";
  return "quality / balanced melee";
}
const fmt = (v) => (v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-US") : String(v));

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

function section(title, kids) {
  return el("section", { class: "sec" }, el("h4", { text: title }), ...kids);
}

function itemList(items) {
  return el("ul", { class: "items" },
    ...items.map(([n, q]) => el("li", null, n + (q && q > 1 ? ` ×${q}` : ""))));
}

function statTable(stats) {
  const keys = Object.keys(stats);
  const head = el("tr", null, ...keys.map((k) => el("th", { text: STAT_ABBR[k] || k.slice(0, 3).toUpperCase() })));
  const row = el("tr", null, ...keys.map((k) => el("td", { text: fmt(stats[k]) })));
  return el("div", { class: "table-wrap" }, el("table", { class: "stats" }, el("thead", null, head), el("tbody", null, row)));
}

function facts(ch) {
  const rows = [];
  const add = (label, val) => rows.push(el("div", { class: "fact" }, el("span", { class: "fk", text: label }), el("span", { class: "fv", text: val })));
  if (ch.level != null) add(ch.game === "er" ? "Level" : "Soul Level", fmt(ch.level));
  if (ch.klass) add("Class", ch.klass);
  if (ch.covenant) add("Covenant", ch.covenant);
  if (ch.ng_plus != null) add("Playthrough", ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`);
  if (ch.soul_memory != null) add("Soul Memory", fmt(ch.soul_memory));
  if (ch.souls != null) add(ch.game === "er" ? "Runes Held" : "Souls Held", fmt(ch.souls));
  if (ch.humanity != null) add("Humanity", fmt(ch.humanity));
  if (ch.hp != null) add("Max HP", fmt(ch.hp));
  if (ch.hollow_lvl) add("Hollowing", fmt(ch.hollow_lvl));
  if (ch.stamina != null) add("Stamina", fmt(ch.stamina));
  const build = guessBuild(ch.stats);
  if (build) add("Build", build);
  return el("div", { class: "facts" }, ...rows);
}

function characterCard(slot, ch) {
  const card = el("article", { class: "char" });
  card.append(el("div", { class: "char-head" },
    el("h3", null, el("span", { class: "slot", text: `Slot ${slot}` }), el("span", { class: "cname", text: ch.name })),
    el("span", { class: `badge ${ch.tier}`, text: ch.tier === "full" ? "full data" : "inventory only" })));

  card.append(facts(ch));

  if (Object.keys(ch.stats).length) card.append(section("Attributes", [statTable(ch.stats)]));
  else if (ch.tier === "inventory") card.append(el("p", { class: "note", text: "Attributes not shown for this slot — its stat block did not validate (unrecognised patch or edited save). A wrong number is worse than none; inventory and progress below are read directly." }));

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

/** Build the DOM for a parsed save result. */
export function renderSave(result, filename) {
  const root = el("div", { class: "result" });
  root.append(el("div", { class: "gamebar" },
    el("div", null, el("h2", { text: result.title }), el("p", { class: "src", text: filename || "" })),
    el("span", { class: "count", text: `${result.characters.length} character${result.characters.length === 1 ? "" : "s"}` })));
  if (!result.characters.length) root.append(el("p", { class: "note", text: "No populated character slots found." }));
  for (const { slot, ch } of result.characters) root.append(characterCard(slot, ch));
  root.append(el("p", { class: "foot", text: "Everything above is read directly from the save in your browser. Progress sections are a floor — consumed boss souls and untracked flags can hide kills, never invent them." }));
  return root;
}
