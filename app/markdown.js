// Build the same Markdown the Python tool emits, in the browser — for the "Copy
// Markdown" button (paste a playthrough into an LLM as context). Faithful to
// md_for_character + convert's header; verified against the Python .md output by
// scratch/md_harness.mjs (timestamp line excluded).

import { STAT_ABBR, statGovernsFor, statCapsFor, capFirst, CAT_TITLE, CAT_ORDER, DS2_GREAT_SOULS, SRC, guessBuild, ds2DerivedStats, fmt, fmtPlaytime } from "./tables.js";

const REPO_URL = "https://github.com/darthdemono/sl2-analyzer";

// Per-game "how it works" note (verbatim from GAMES[...]["how"]) and the header tier.
const HOW = {
  ds2sotfs: "the save is scrambled with a lock (AES-128 encryption) whose key ships inside the game itself, so the tool applies that key to unlock the raw data. From there each character's details sit at fixed, known positions: name, level, the nine attributes, and souls are read straight from those spots. Every inventory entry stores a numeric item ID, which the tool looks up in a name table built from the community's SOTFS ID list, so you read 'Longsword' instead of a number; reinforcement level and infusion sit in a separate field of each item record and are shown as a '+N' suffix and an infusion prefix (e.g. 'Fire Longsword +6')",
  dsr: "the save is locked the same way (AES-128 encryption, key shipped inside the game), so the tool unlocks it first. The character block does not sit at a fixed spot — it shifts as the save grows — so the tool locates it by a fixed marker (a 'magic' byte pattern) that always sits beside it, then reads the level, stats, and souls at known distances from that marker. The inventory is found by a second, separate marker, and every item ID is matched to its real name",
  ptde: "this original edition does not encrypt its save at all, so there is nothing to unlock. It stores a character the same way Remastered does but without that version's marker, so the tool finds the character by locating the name text and reads the level, stats, souls, and inventory that sit at known distances around it",
  ds3: "the save is locked with AES-128 encryption, key shipped in the game, so the tool unlocks it first. The stats do not sit at a fixed position, and that position moves between game patches, so instead of trusting a location the tool searches for the stat block by its content: it looks for the run of nine numbers that, added together, equal the character's stored level — a rule the game itself follows, which makes a wrong match almost impossible. Items are found by scanning the slot for known IDs and matched to names",
  er: "the save is not encrypted, so the tool reads it directly. Like Dark Souls III, the stats are found by content rather than a fixed spot — the tool looks for the eight numbers that add up to the character's level — which matters more here because that stat block sits in a different place for every character. Every item the character owns is read from the game's item array and matched to its real name",
};

const ER_NOTE = "_Elden Ring identity, attributes, and runes are read directly; the **item list is partial**. Owned items come from the GaItem array, which holds weapons, armour and Ashes of War — each named against its own type table (so no cross-type mis-naming) and reinforced/affinity weapons resolve to the base weapon (the upgrade level itself is not read). Talismans, spells and consumable goods live in a separate held-inventory that shifts between patches and is not parsed, so they are not listed. What is listed is really owned._";

function bullets(items) {
  return items.map(([n, q]) => `- ${n}` + (q && q > 1 ? ` ×${q}` : ""));
}

function mdCharacter(ch, slot) {
  const L = [`## Slot ${slot}: ${ch.name}`, ""];
  if (ch.level != null) L.push(`- **${ch.game === "er" ? "Level" : "Soul Level"}:** ${ch.level}`);
  if (ch.klass) L.push(`- **Class:** ${ch.klass}`);
  if (ch.covenant) L.push(`- **Covenant:** ${ch.covenant}`);
  if (ch.gender) L.push(`- **Gender:** ${ch.gender}`);
  if (ch.ng_plus != null) L.push(`- **Playthrough:** ${ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`}`);
  if (ch.soul_memory != null) L.push(`- **Soul Memory:** ${fmt(ch.soul_memory)}  _(total souls earned — main progress metric)_`);
  if (ch.play_time) L.push(`- **Play Time:** ${fmtPlaytime(ch.play_time)}`);
  if (ch.souls != null) L.push(`- **${ch.game === "er" ? "Runes" : "Souls"} held:** ${fmt(ch.souls)}`);
  if (ch.humanity != null) L.push(`- **Humanity:** ${ch.humanity}`);
  if (ch.hp != null) L.push(`- **Max HP:** ${fmt(ch.hp)}`);
  if (ch.hollow_lvl) L.push(`- **Hollowing:** ${ch.hollow_lvl}  _(higher = more deaths without an effigy)_`);
  if (ch.deaths != null) L.push(`- **Deaths:** ${fmt(ch.deaths)}`);
  if (ch.stamina != null) L.push(`- **Stamina:** ${fmt(ch.stamina)}`);
  const build = guessBuild(ch.stats);
  if (build) L.push(`- **Build:** ${build}`);
  L.push("");

  const keys = Object.keys(ch.stats);
  if (keys.length) {
    L.push("### Attributes", "",
      "| " + keys.map((k) => STAT_ABBR[k] || k.slice(0, 3).toUpperCase()).join(" | ") + " |",
      "|" + "----|".repeat(keys.length),
      "| " + keys.map((k) => String(ch.stats[k])).join(" | ") + " |", "");
    const gov = statGovernsFor(ch.game), cap = statCapsFor(ch.game);
    const rows = keys.filter((k) => gov.has(k));
    if (rows.length) {
      L.push("### Attribute Scaling  _(what each stat scales, its soft caps, and your current value — game-mechanics reference, not a value read from this save)_", "");
      L.push(...rows.map((k) => `- **${k}** (${ch.stats[k]}) — ${gov.get(k)}.${cap.has(k) ? ` ${capFirst(cap.get(k))}.` : ""}`), "");
    }
    if (ch.game === "ds2sotfs") {
      const d = ds2DerivedStats(ch.stats);
      const agl = `${d.agility}` + (d.iframes ? `  _(${d.iframes} roll i-frames)_` : "");
      L.push("### Derived Stats  _(computed from attributes — base values before rings & equipment; the in-game screen adds ring/gear bonuses on top)_", "",
        `- **Stamina:** ${d.stamina}`,
        `- **Equip Load:** ${d.equip_load.toFixed(1)}`,
        `- **Attunement Slots:** ${d.slots}`,
        `- **Agility (AGL):** ${agl}`,
        `- **Poise (base):** ${d.poise.toFixed(1)}`,
        `- **ATK: Str:** ${d.atk_str}`,
        `- **ATK: Dex:** ${d.atk_dex}`,
        `- **Magic DEF:** ${d.magic_def}`,
        `- **Fire DEF:** ${d.fire_def}`,
        `- **Lightning DEF:** ${d.lightning_def}`,
        `- **Dark DEF:** ${d.dark_def}`, "");
    }
  } else if (ch.tier === "inventory") {
    L.push("_Attributes are not printed for this slot: its stat block did not validate (an unrecognised patch or an edited save), and a wrong number is worse than none. Inventory and progress below are read directly._", "");
  }

  if (ch.boss_souls && ch.boss_souls.length) {
    L.push(ch.game === "er"
      ? "### Remembrances Held  _(major bosses defeated, not yet traded)_"
      : "### Boss Souls Held  _(bosses defeated, soul not yet consumed)_", "", ...bullets(ch.boss_souls), "");
  }
  if (ch.key_items && ch.key_items.length) {
    L.push("### Key Items  _(progress / areas & shortcuts unlocked)_", "", ...bullets(ch.key_items), "");
  }
  if (ch.bonfires && ch.bonfires.length) {
    L.push(`### Bonfires Discovered (${ch.bonfires.length})  _(areas reached — a floor on progress)_`, "",
      ...ch.bonfires.map((b) => `- ${b}`), "");
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    L.push(`### Bosses Defeated (${Object.keys(ch.bosses).length})  _(a floor — from defeat flags, held boss souls, progression, and NG+ clears; a boss whose soul was consumed and isn't gated may still be missing)_`, "");
    for (const [boss, srcs] of Object.entries(ch.bosses)) L.push(`- ${boss}  _(${srcs.map((s) => SRC[s]).join(", ")})_`);
    L.push("");
  }

  L.push("### Inventory", "");
  for (const cat of CAT_ORDER) {
    const items = ch.inv[cat];
    if (!items || !items.length) continue;
    if (cat === "bosssouls") {
      for (const [title, group] of [["Great Boss Souls", items.filter((it) => DS2_GREAT_SOULS.has(it[0]))],
                                    ["Boss Souls", items.filter((it) => !DS2_GREAT_SOULS.has(it[0]))]]) {
        if (group.length) L.push(`#### ${title}`, "", ...bullets(group), "");
      }
    } else L.push(`#### ${CAT_TITLE[cat]}`, "", ...bullets(items), "");
  }
  if (ch.unknown_count) L.push(`_${ch.unknown_count} inventory item(s) had IDs not in the name database (upgraded / infused variants) and were omitted._`, "");
  return L.join("\n");
}

/** Full Markdown document for a parsed save, matching the Python tool's output. */
export function buildMarkdown(result, filename) {
  const stamp = new Date();
  const ts = `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, "0")}-${String(stamp.getDate()).padStart(2, "0")} ${String(stamp.getHours()).padStart(2, "0")}:${String(stamp.getMinutes()).padStart(2, "0")}`;
  const disclaimer = `> Automated dump of the save. Code Repo: ${REPO_URL} . How it works for ${result.title}: ${HOW[result.game]}.`;
  const head = [`# ${result.title} — Playthrough Save Summary`, "",
    `_Source: \`${filename}\` · generated ${ts} · sl2_to_md_`, "",
    `- **Game:** ${result.title}`, `- **Support tier:** full`, "",
    `- **Characters found:** ${result.characters.length}`, "", disclaimer, "", "---", ""];
  const body = [];
  if (!result.characters.length) body.push("_No populated character slots found._");
  for (const { slot, ch } of result.characters) { body.push(mdCharacter(ch, slot)); body.push("---", ""); }
  if (result.game === "er") body.push(ER_NOTE);
  return head.concat(body).join("\n");
}
