// Build the same Markdown the Python tool emits, in the browser — for the "Copy
// Markdown" button (paste a playthrough into an LLM as context). Faithful to
// md_for_character + convert's header; verified against the Python .md output by
// scratch/md_harness.mjs (timestamp line excluded).

import {
  STAT_ABBR,
  statGovernsFor,
  statCapsFor,
  capFirst,
  CAT_TITLE,
  CAT_ORDER,
  CURRENCY,
  DS2_GREAT_SOULS,
  SRC,
  guessBuild,
  ds1DerivedStats,
  ds2DerivedStats,
  ds3DerivedStats,
  DS2_GAMES,
  fmt,
  fmtPlaytime,
  countDupes,
  memoriesLine,
  vitalityNecklaces,
  catTitle,
} from "./tables.js";

export const REPO_URL = "https://github.com/darthdemono/sl2-analyzer";
// DS1 reads each bonfire's own record (so it knows the kindle level and can list a
// discovered-but-unlit one); DS3 only has per-area flag bits. See sl2_to_md.py.
const DS1_BONFIRE_NOTE = "each bonfire's own record, with how far it is kindled — a floor";
const DS3_BONFIRE_NOTE = "bonfires lit, inferred from each area's flag bits — a floor";
// DS2 reads the world block's own discovered-bonfire array, so it names every one it
// found; the areas are a grouping of that list, not an inference.
const DS2_BONFIRE_NOTE = "each bonfire the save records as discovered, by area — a floor";
// Sekiro's bonfire is a Sculptor's Idol, and unlike every other game's it starts again
// on a new journey. See SDT_BONFIRE_NOTE in sl2/render.py.
const SDT_BONFIRE_NOTE =
  "each idol's own flag bit, by area — a floor, and one that starts again on a new journey";
// Sekiro files a miniboss defeat under the enemy's own entity id, so these are exact
// rather than inferred. Verbatim from SDT_MINIBOSS_NOTE in sl2/render.py.
const DS1_WORLD_NOTE =
  "one-off world events, each read from its own flag — exact, but only the flags that have been named are counted";
const SDT_MINIBOSS_NOTE =
  "each miniboss's own defeat flag — exact, not inferred, but it resets on a new journey; names are the game's own, so a repeat in an area is a second placement of that character";
// Only six areas have a derived flag-group base, so this counts what is TRACKED, not
// what the game ships. An area absent from the list is unmapped, not empty.
const DS3_PICKUP_NOTE =
  "one-off world items picked up, from each area's pickup flags — covers only the areas whose flag group is mapped";
// Sekiro's gap is the reverse shape: the addressing is solved, but 237 of the 826 known
// lots sit in families no idol names. Verbatim from SDT_PICKUP_NOTE in sl2/render.py.
const SDT_PICKUP_NOTE =
  "one-off world items picked up, from each area's item-lot flags — covers the nine areas whose flag bank is mapped, 589 of the 826 lots the table knows";
// Enemies that do not respawn, so the game has to remember each one dead. These are the
// enemy's own DEATH flag, not the pickup flag its loot sets. Verbatim from DS3_ENEMY_NOTE
// in sl2/render.py.
// Sourced, not verified here; counts only, because the names are FromSoft's own Japanese.
// Verbatim from DS1_EVENT_NOTE in sl2/render.py.
const DS1_EVENT_NOTE =
  "world events from the game's own event scripts, counted by kind — sourced, not verified here; some are transient (set while the event runs), so a finished run can honestly read 0 in a family";
// Verbatim from DS3_NPC_NOTE in sl2/render.py.
const DS3_NPC_NOTE =
  "NPC deaths, hostility and questline milestones, each its own flag — the descriptions are the source's and one is known to be on the wrong flag, so an entity id is printed beside them where there is one";
const DS3_ENEMY_NOTE =
  "each enemy's own defeat flag — exact, not inferred, and it carries across a new journey; names are enemy types, so repeats in an area are different enemies";

// Per-game "how it works" note (verbatim from GAMES[...]["how"]) and the header tier.
const HOW = {
  ds2vanilla:
    "the original (pre-Scholar) release locks its save with a different AES-128 key from Scholar's, but stores everything in the same places once unlocked — so the same reader handles both. Name, level, the nine attributes, souls and the inventory sit at fixed known positions, and every item ID is looked up in the community SOTFS name table. Note the Scholar-only items and bonfires simply never appear in an original-edition save",
  ds2sotfs:
    "the save is scrambled with a lock (AES-128 encryption) whose key ships inside the game itself, so the tool applies that key to unlock the raw data. From there each character's details sit at fixed, known positions: name, level, the nine attributes, and souls are read straight from those spots. Every inventory entry stores a numeric item ID, which the tool looks up in a name table built from the community's SOTFS ID list, so you read 'Longsword' instead of a number; reinforcement level and infusion sit in a separate field of each item record and are shown as a '+N' suffix and an infusion prefix (e.g. 'Fire Longsword +6')",
  dsr: "the save is locked the same way (AES-128 encryption, key shipped inside the game), so the tool unlocks it first. The character block does not sit at a fixed spot — it shifts as the save grows — so the tool locates it by a fixed marker (a 'magic' byte pattern) that always sits beside it, then reads the level, stats, and souls at known distances from that marker. The inventory is found by a second, separate marker, and every item ID is matched to its real name",
  ptde: "this original edition does not encrypt its save at all, so there is nothing to unlock. It stores a character the same way Remastered does but without that version's marker, so the tool finds the character by locating the name text and reads the level, stats, souls, and inventory that sit at known distances around it",
  ds3: "the save is locked with AES-128 encryption, key shipped in the game, so the tool unlocks it first. The stats do not sit at a fixed position, and that position moves between game patches, so instead of trusting a location the tool searches for the stat block by its content: it looks for the run of nine numbers that, added together, equal the character's stored level — a rule the game itself follows, which makes a wrong match almost impossible. Items are found by scanning the slot for known IDs and matched to names",
  sdt: "the save is not encrypted and, unlike every other game here, its fields do not move between patches — so play time, journey (New Game+) count, Attack Power and Sen are read straight from fixed positions. The item lists are read the same way: each entry stores a type code beside its item ID, so a piece of armour can never be named as a weapon, and a prosthetic tool's upgrade tier is its own ID (there is no '+N' to work out). Sekiro has no character name and no attributes to level, so neither appears; Attack Power doubles as a count of the Memories already spent, which is how bosses whose token is long gone are still counted",
  er: "the save is not encrypted, so the tool reads it directly. Like Dark Souls III, the stats are found by content rather than a fixed spot — the tool looks for the eight numbers that add up to the character's level — which matters more here because that stat block sits in a different place for every character. Every item the character owns is read from the game's item array and matched to its real name",
};

const ER_NOTE =
  "_Elden Ring identity, attributes, and runes are read directly; the **item list is partial**. Owned items come from the GaItem array, which holds weapons, armour and Ashes of War — each named against its own type table (so no cross-type mis-naming) and reinforced/affinity weapons resolve to the base weapon (the upgrade level itself is not read). Talismans, spells and consumable goods live in a separate held-inventory that shifts between patches and is not parsed, so they are not listed. What is listed is really owned._";

// The Lords-of-Cinder line: how many of the four are on the throne, which ones the
// mapped flags name, and the counts behind the number. See lords_line in sl2_to_md.py.
// Sekiro's caveat. Verbatim from SDT_NOTE in convert.py — if one moves, both move, or
// the Markdown harness fails on the byte difference.
const SDT_NOTE =
  "_Sekiro has no character name and no attributes: both are absent from the game, not missing here. The item lists (carried, key items and the storage box) are read whole and named by type, so nothing in them is guessed. Max HP and max Posture come from the second of each field's two copies, because the offsets the published editor labels as maxima are the CURRENT values \u2014 a save pair either side of taking damage settled that. **Spirit Emblems** is not read as a number of its own: the documented field holds 15 across saves taken before and after the character gained a prosthetic, so it is the carry cap rather than the count \u2014 and emblems you actually hold are an ordinary inventory item, listed with everything else. The **Sculptor's Idols** and the boss-defeat **flags** are both read: the event-flag region is at a fixed place in the save, worked out from save pairs that lit one idol and killed one boss, so a kill tagged _(confirmed)_ is proven rather than counted off a Memory. Both RESET on a new journey — Attack Power carries and the flags do not, so an NG+ save reports fewer than the character has earned._";

function lordsLine(lords) {
  // Mid-dot separated: "Aldrich, Devourer of Gods" has a comma of its own.
  const named = lords.named && lords.named.length ? ` — ${lords.named.join(" · ")}` : "";
  if (lords.placed == null) {
    return (
      `${(lords.named || []).length} of ${lords.total}${named}` +
      "  _(NG+ — only the mapped throne flags are read, so this is a floor)_"
    );
  }
  return (
    `${lords.placed} of ${lords.total}${named}` +
    `  _(${lords.dead} of the four lords defeated, ${lords.held} set${lords.held === 1 ? "" : "s"} of cinders still held)_`
  );
}

// "N of M" plus the names still missing. Boss and bonfire names contain commas, so
// the list is mid-dot separated.
function missingNote(label, missing) {
  return missing && missing.length ? `_${label}: ${missing.join(" · ")}._` : null;
}

function bullets(items) {
  return items.map(([n, q]) => `- ${n}` + (q && q > 1 ? ` ×${q}` : ""));
}

export function mdCharacter(ch, slot) {
  const L = [`## Slot ${slot}: ${ch.name}`, ""];
  if (ch.level != null) L.push(`- **${ch.game === "er" ? "Level" : "Soul Level"}:** ${ch.level}`);
  if (ch.klass) L.push(`- **Class:** ${ch.klass}`);
  if (ch.covenant) L.push(`- **Covenant:** ${ch.covenant}`);
  if (ch.gender) L.push(`- **Gender:** ${ch.gender}`);
  if (ch.ng_plus != null)
    L.push(`- **Playthrough:** ${ch.ng_plus === 0 ? "New Game" : `New Game +${ch.ng_plus}`}`);
  if (ch.soul_memory != null)
    L.push(
      `- **Soul Memory:** ${fmt(ch.soul_memory)}  _(total souls earned — main progress metric)_`,
    );
  if (ch.play_time) L.push(`- **Play Time:** ${fmtPlaytime(ch.play_time)}`);
  if (ch.souls != null) L.push(`- **${CURRENCY[ch.game] || "Souls"} held:** ${fmt(ch.souls)}`);
  if (ch.attack != null) L.push(`- **Attack Power:** ${ch.attack}`);
  if (ch.vitality != null)
    L.push(`- **Vitality:** ${ch.vitality}  _(${vitalityNecklaces(ch.vitality)})_`);
  if (ch.skill_points != null)
    L.push(
      `- **Skill Points Held:** ${ch.skill_points}` +
        "  _(spendable at a Sculptor's Idol — the points already spent are not stored, so this is what is banked, not what has been earned)_",
    );
  if (ch.memories) L.push(`- **Memories:** ${memoriesLine(ch.memories)}`);
  if (ch.humanity != null) L.push(`- **Humanity:** ${ch.humanity}`);
  if (ch.hp != null) L.push(`- **Max HP:** ${fmt(ch.hp)}`);
  if (ch.posture != null) L.push(`- **Max Posture:** ${fmt(ch.posture)}`);
  if (ch.embered != null)
    L.push(
      ch.embered
        ? "- **Embered:** Yes  _(Max HP above includes the +30% ember bonus)_"
        : "- **Embered:** No  _(hollow — Max HP above is the base value)_",
    );
  if (ch.fp != null) L.push(`- **Max FP:** ${fmt(ch.fp)}`);
  if (ch.hollow_lvl)
    L.push(`- **Hollowing:** ${ch.hollow_lvl}  _(higher = more deaths without an effigy)_`);
  if (ch.deaths != null) L.push(`- **Deaths:** ${fmt(ch.deaths)}`);
  if (ch.stamina != null) L.push(`- **Stamina:** ${fmt(ch.stamina)}`);
  if (ch.lords) L.push(`- **Cinders of a Lord Placed:** ${lordsLine(ch.lords)}`);
  if (ch.endings && ch.endings.length) {
    L.push(`- **Ending${ch.endings.length === 1 ? "" : "s"} Reached:** ${ch.endings.join(" · ")}`);
  }
  const build = guessBuild(ch.stats);
  if (build) L.push(`- **Build:** ${build}`);
  L.push("");

  const keys = Object.keys(ch.stats);
  if (keys.length) {
    L.push(
      "### Attributes",
      "",
      "| " + keys.map((k) => STAT_ABBR[k] || k.slice(0, 3).toUpperCase()).join(" | ") + " |",
      "|" + "----|".repeat(keys.length),
      "| " + keys.map((k) => String(ch.stats[k])).join(" | ") + " |",
      "",
    );
    const gov = statGovernsFor(ch.game),
      cap = statCapsFor(ch.game);
    const rows = keys.filter((k) => gov.has(k));
    if (rows.length) {
      // Fixed game-mechanics reference, identical in every export bar the current
      // values — folded away so two exports diff cleanly. See sl2_to_md.py.
      L.push(
        "<details>",
        "<summary><b>Attribute Scaling</b> — what each stat scales and its soft caps (game-mechanics reference, not read from this save)</summary>",
        "",
      );
      L.push(
        ...rows.map(
          (k) =>
            `- **${k}** (${ch.stats[k]}) — ${gov.get(k)}.${cap.has(k) ? ` ${capFirst(cap.get(k))}.` : ""}`,
        ),
        "",
        "</details>",
        "",
      );
    }
    if (DS2_GAMES.has(ch.game)) {
      const d = ds2DerivedStats(ch.stats);
      const agl = `${d.agility}` + (d.iframes ? `  _(${d.iframes} roll i-frames)_` : "");
      L.push(
        "### Derived Stats  _(computed from attributes — base values before rings & equipment; the in-game screen adds ring/gear bonuses on top)_",
        "",
        `- **Stamina:** ${d.stamina}`,
        `- **Equip Load (max capacity):** ${d.equip_load.toFixed(1)}`,
        `- **Attunement Slots:** ${d.slots}`,
        `- **Agility (AGL):** ${agl}`,
        `- **Poise (base):** ${d.poise.toFixed(1)}`,
        `- **ATK: Str:** ${d.atk_str}`,
        `- **ATK: Dex:** ${d.atk_dex}`,
        `- **Magic DEF:** ${d.magic_def}`,
        `- **Fire DEF:** ${d.fire_def}`,
        `- **Lightning DEF:** ${d.lightning_def}`,
        `- **Dark DEF:** ${d.dark_def}`,
        "",
      );
    }
    if (ch.game === "ds3") {
      const d = ds3DerivedStats(ch.stats, ch.ring_mods),
        w = d.ring_bonus;
      // "73.0 base, +5% Ring of Favor, +15% Havel's Ring" — the sum is only as good as
      // its parts, so the parts are printed beside it.
      const credit = (base, kind, unit) =>
        w[kind].length
          ? `  _(${base} base, ${w[kind].map(([n, v]) => `+${v}${unit} ${n}`).join(", ")})_`
          : "";
      L.push(
        "### Derived Stats  _(computed from attributes, plus the documented bonus of any worn ring named beside the value — the game's other gear is not read)_",
        "",
        `- **Attunement Slots:** ${d.slots}` + credit(d.slots_base, "slots", ""),
        `- **Equip Load (max capacity):** ${d.equip_load.toFixed(1)}` +
          credit(d.equip_load_base.toFixed(1), "load_pct", "%"),
        `- **Item Discovery:** ${d.item_discovery}` +
          credit(d.item_discovery_base, "discovery", ""),
      );
      // HP and stamina are read fields, so a ring that boosts them is already in the
      // numbers above — say so rather than adding it a second time.
      const already = ["hp_pct", "stam_pct"].flatMap((k) =>
        w[k].map(([n, v]) => `+${v}% ${k === "hp_pct" ? "Max HP" : "Stamina"} (${n})`),
      );
      if (already.length)
        L.push(
          `- **Also from rings:** ${already.join(", ")}  _(Max HP and Stamina are read from the save, so they already include these)_`,
        );
      L.push("");
    }
    if (ch.game === "dsr" || ch.game === "ptde") {
      const d = ds1DerivedStats(ch.stats);
      L.push(
        "### Derived Stats  _(computed from attributes — base values before rings & equipment)_",
        "",
        `- **Attunement Slots:** ${d.slots}`,
        `- **Equip Load (max capacity):** ${d.equip_load.toFixed(1)}`,
        "",
      );
    }
  } else if (ch.tier === "inventory") {
    L.push(
      "_Attributes are not printed for this slot: its stat block did not validate (an unrecognised patch or an edited save), and a wrong number is worse than none. Inventory and progress below are read directly._",
      "",
    );
  }

  // Boss souls get a top section only where the inventory does NOT already have a
  // boss-souls category (DS2 and DS3 do) — printing both is the same list twice.
  if (
    ch.boss_souls &&
    ch.boss_souls.length &&
    !(ch.inv.bosssouls || []).length &&
    !(ch.inv.memories || []).length
  ) {
    L.push(
      ch.game === "er"
        ? "### Remembrances Held  _(major bosses defeated, not yet traded)_"
        : "### Boss Souls Held  _(bosses defeated, soul not yet consumed)_",
      "",
      ...bullets(ch.boss_souls),
      "",
    );
  }
  if (ch.key_items && ch.key_items.length) {
    L.push(
      "### Key Items  _(progress / areas & shortcuts unlocked)_",
      "",
      ...bullets(ch.key_items),
      "",
    );
  }
  // DS2 keeps a flat name list for the boss-gate logic, but renders the grouped view
  // when the area table resolved it; the flat list is the fallback.
  if (ch.bonfires && ch.bonfires.length && !(ch.bonfire_areas && ch.bonfire_areas.length)) {
    L.push(
      `### Bonfires Discovered (${ch.bonfires.length})  _(areas reached — a floor on progress)_`,
      "",
      ...ch.bonfires.map((b) => `- ${b}`),
      "",
    );
  }
  if (ch.bonfire_areas && ch.bonfire_areas.length) {
    const lit = ch.bonfire_areas.reduce((s, [, c]) => s + c, 0);
    const total = ch.bonfire_areas.reduce((s, [, , , t]) => s + t, 0);
    const n = ch.bonfire_areas.filter(([, c]) => c).length,
      areas = ch.bonfire_areas.length;
    const bfNote =
      ch.game === "dsr" || ch.game === "ptde"
        ? DS1_BONFIRE_NOTE
        : DS2_GAMES.has(ch.game)
          ? DS2_BONFIRE_NOTE
          : ch.game === "sdt"
            ? SDT_BONFIRE_NOTE
            : DS3_BONFIRE_NOTE;
    // Sekiro has no bonfires; calling its idols one would be the same kind of wrong as
    // printing a soul level for a game that has none.
    const bfHead = ch.game === "sdt" ? "Sculptor's Idols Lit" : "Bonfires Discovered";
    L.push(
      `### ${bfHead} (${lit} of ${total}, in ${n} of ${areas} areas)  _(${bfNote})_`,
      "",
      ...ch.bonfire_areas.map(([name, c, named, tot, missing]) => {
        let row = `- ${name}: ${c}/${tot}`;
        if (named && named.length) {
          row += ` — ${named.join(", ")}`;
          // Only a STARTED area lists what is left; an untouched area would just
          // print the whole game back at you.
          if (missing && missing.length) row += `  _(missing: ${missing.join(" · ")})_`;
        }
        return row;
      }),
      "",
    );
  }
  if (ch.covenants && Object.keys(ch.covenants).length) {
    const found = Object.keys(ch.covenants).length;
    L.push(
      `### Covenants Found (${ch.covenant_total ? `${found} of ${ch.covenant_total}` : found})  _(discovered — a floor; the one currently worn is the Covenant field above)_`,
      "",
    );
    for (const [cov, w] of Object.entries(ch.covenants)) L.push(`- **${cov}:** ${w.join(", ")}`);
    L.push("");
    const note = missingNote("Not found yet", ch.covenants_missing);
    if (note) L.push(note, "");
  }
  if (ch.world_flags && ch.world_flags.length) {
    const got = ch.world_flags.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.world_flags.reduce((s2, [, , , t]) => s2 + t, 0);
    L.push(
      `### World State (${got} of ${total} tracked)  _(${DS1_WORLD_NOTE})_`,
      "",
      ...ch.world_flags.map(([cat, c, names, tot, missing]) => {
        let row = `- ${cat}: ${c}/${tot}`;
        // Mid-dot: half these names carry a comma of their own.
        if (names.length) {
          row += ` — ${names.join(" · ")}`;
          if (missing.length) row += `  _(not yet: ${missing.join(" · ")})_`;
        }
        return row;
      }),
      "",
    );
  }
  if (ch.minibosses && ch.minibosses.length) {
    const dead = ch.minibosses.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.minibosses.reduce((s2, [, , , t]) => s2 + t, 0);
    L.push(
      `### Minibosses Defeated (${dead} of ${total} tracked)  _(${SDT_MINIBOSS_NOTE})_`,
      "",
      ...ch.minibosses.map(([area, c, names, tot, alive]) => {
        let row = `- ${area}: ${c}/${tot}`;
        if (names.length) {
          row += ` — ${countDupes(names).join(" · ")}`;
          if (alive.length) row += `  _(still alive: ${countDupes(alive).join(" · ")})_`;
        }
        return row;
      }),
      "",
    );
  }
  if (ch.npc_states && ch.npc_states.length) {
    const got = ch.npc_states.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.npc_states.reduce((s2, [, , , t]) => s2 + t, 0);
    L.push(
      `### NPC States (${got} of ${total} tracked)  _(${DS3_NPC_NOTE})_`,
      "",
      ...ch.npc_states.map(([family, c, names, tot]) => {
        let row = `- ${family}: ${c}/${tot}`;
        const said = names.filter((n) => !n.startsWith("character "));
        const rest = names.length - said.length;
        if (said.length) row += ` — ${countDupes(said).join(" · ")}`;
        if (rest) row += `  _(+${rest} more, known only by entity id)_`;
        return row;
      }),
      "",
    );
  }
  if (ch.world_events && ch.world_events.length) {
    const got = ch.world_events.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.world_events.reduce((s2, [, , t]) => s2 + t, 0);
    L.push(
      `### World Events (${got} of ${total} tracked)  _(${DS1_EVENT_NOTE})_`,
      "",
      ...ch.world_events.map(([family, c, tot]) => `- ${family}: ${c}/${tot}`),
      "",
    );
  }
  if (ch.enemies && ch.enemies.length) {
    const dead = ch.enemies.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.enemies.reduce((s2, [, , , t]) => s2 + t, 0);
    L.push(
      `### One-Time Enemies Defeated (${dead} of ${total} tracked)  _(${DS3_ENEMY_NOTE})_`,
      "",
      ...ch.enemies.map(([area, c, names, tot, alive]) => {
        let row = `- ${area}: ${c}/${tot}`;
        if (names.length) {
          row += ` — ${countDupes(names).join(" · ")}`;
          if (alive.length) row += `  _(still alive: ${countDupes(alive).join(" · ")})_`;
        }
        return row;
      }),
      "",
    );
  }
  if (ch.pickups && ch.pickups.length) {
    const got = ch.pickups.reduce((s2, [, c]) => s2 + c, 0);
    const total = ch.pickups.reduce((s2, [, , t]) => s2 + t, 0);
    L.push(
      `### Items Collected (${got} of ${total} tracked)  _(${ch.game === "sdt" ? SDT_PICKUP_NOTE : DS3_PICKUP_NOTE})_`,
      "",
      ...ch.pickups.map(([area, c, tot, missing]) => {
        let row = `- ${area}: ${c}/${tot}`;
        // Same rule as bonfires — an area you have started counts what is left in
        // it; an untouched one would print a walkthrough back at you.
        if (c && missing && missing.length) row += `  _(${missing.length} still out there)_`;
        return row;
      }),
      "",
    );
    // The list itself is folded away. It carries a location per item, which makes it a
    // to-do list rather than a tally — and also long enough to bury the numbers above
    // it if it were printed inline.
    const todo = ch.pickups.filter(([, c, , missing]) => c && missing && missing.length);
    if (todo.length) {
      L.push(
        "<details>",
        "<summary>Where the missing items are — the ones with a known location</summary>",
        "",
      );
      for (const [area, , , missing] of todo) {
        L.push(
          `**${area}** — ${missing.length} missing`,
          "",
          ...countDupes(missing).map((item) => `- ${item}`),
          "",
        );
      }
      L.push("</details>", "");
    }
  }
  if (ch.questlines && Object.keys(ch.questlines).length) {
    // Not all of these are NPCs — the same reward flags cover a few landmark
    // pickups and enemy drops, so the heading says rewards, not questlines.
    L.push(
      "### Rewards Obtained  _(one-off rewards from NPCs, invaders and landmark pickups — a progress floor)_",
      "",
    );
    for (const [src, rw] of Object.entries(ch.questlines)) L.push(`- **${src}:** ${rw.join(", ")}`);
    L.push("");
  }
  if (ch.bosses && Object.keys(ch.bosses).length) {
    const found = Object.keys(ch.bosses).length;
    L.push(
      `### Bosses Defeated (${ch.boss_total ? `${found} of ${ch.boss_total} tracked` : found})  _(a floor — from defeat flags, held boss souls, progression, and NG+ clears; a boss whose soul was consumed and isn't gated may still be missing)_`,
      "",
    );
    for (const [boss, srcs] of Object.entries(ch.bosses))
      L.push(`- ${boss}  _(${srcs.map((s) => SRC[s]).join(", ")})_`);
    L.push("");
    // The missing list splits in two where a route graph exists: what is open now,
    // and what is still behind something. Game structure, not a save read.
    const avail = ch.bosses_available || [];
    const rest = (ch.bosses_missing || []).filter((b) => !avail.includes(b));
    if (avail.length) {
      L.push(
        `_Available now — every prerequisite dead and the area already reached (from the game's fixed route, not this save): ${avail.join(" · ")}._`,
        "",
      );
    }
    const note = missingNote(
      "No evidence yet" + (avail.length ? ", and behind something else" : ""),
      rest,
    );
    if (note) L.push(note, "");
  }

  const weapons = ch.equipped_weapons || {},
    armor = ch.equipped_armor || {},
    rings = ch.equipped_rings || [],
    ammo = ch.equipped_ammo || [];
  if (Object.keys(weapons).length || Object.keys(armor).length || rings.length || ammo.length) {
    L.push("### Equipped  _(worn gear read from the equip slots)_", "");
    for (const [slot, name] of Object.entries(weapons)) L.push(`- **${slot}:** ${name}`);
    for (const [slot, name] of Object.entries(armor)) L.push(`- **${slot}:** ${name}`);
    if (rings.length) {
      // With the effect table loaded each ring gets its own line and what it does;
      // without it the old one-line list is still the fallback.
      const eff = Object.fromEntries(ch.ring_effects || []);
      if (Object.keys(eff).length) {
        L.push("- **Rings:**");
        for (const n of rings) L.push(`    - ${n}` + (eff[n] ? ` — ${eff[n]}` : ""));
      } else {
        L.push(`- **Rings:** ${rings.join(", ")}`);
      }
    }
    if (ammo.length) L.push(`- **Ammo:** ${ammo.join(", ")}`);
    L.push("");
  }

  L.push("### Inventory", "");
  // DS1 and ER keep boss souls and key items inside the flat `goods` bucket, which
  // already has its own section above — list each item once and point at it.
  const listed = new Set([
    ...(ch.boss_souls || []).map(([n]) => n),
    ...(ch.key_items || []).map(([n]) => n),
  ]);
  for (const cat of CAT_ORDER) {
    let items = ch.inv[cat];
    if (!items || !items.length) continue;
    if (cat === "goods" && listed.size) {
      items = items.filter(([n]) => !listed.has(n));
      if (!items.length) continue;
    }
    if (cat === "bosssouls") {
      for (const [title, group] of [
        ["Great Boss Souls", items.filter((it) => DS2_GREAT_SOULS.has(it[0]))],
        ["Boss Souls", items.filter((it) => !DS2_GREAT_SOULS.has(it[0]))],
      ]) {
        if (group.length) L.push(`#### ${title}`, "", ...bullets(group), "");
      }
    } else {
      const title =
        catTitle(ch.game, cat) +
        (cat === "goods" && listed.size ? "  _(boss souls and key items are listed above)_" : "");
      L.push(`#### ${title}`, "", ...bullets(items), "");
    }
  }
  if (ch.unknown_count)
    L.push(
      `_${ch.unknown_count} inventory item(s) had IDs not in the name database (upgraded / infused variants) and were omitted._`,
      "",
    );
  if (ch.internal_count) {
    L.push(
      `_${ch.internal_count} further entr${ch.internal_count === 1 ? "y" : "ies"} carried only an engine development name — placeholder rows and debug items rather than anything the game hands you — and were left out._`,
      "",
    );
  }
  if (ch.suppressed_count) {
    L.push(
      `_${ch.suppressed_count} further entr${ch.suppressed_count === 1 ? "y" : "ies"} were engine state rather than inventory — Sekiro has no armour system, so the character's own body models sit in the protector table, and the \`Virtual Weapon:\` rows restate a Combat Art already listed under its own name. Counted here, not printed._`,
      "",
    );
  }
  return L.join("\n");
}

/** Full Markdown document for a parsed save, matching the Python tool's output. */
export function buildMarkdown(result, filename) {
  const stamp = new Date();
  const ts = `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, "0")}-${String(stamp.getDate()).padStart(2, "0")} ${String(stamp.getHours()).padStart(2, "0")}:${String(stamp.getMinutes()).padStart(2, "0")}`;
  const disclaimer = `> Automated dump of the save. Code Repo: ${REPO_URL} . How it works for ${result.title}: ${HOW[result.game]}.`;
  // Only the save's own identity up top; what the TOOL is and how far to trust it is
  // the same in every export, so it goes in the closing block.
  const head = [
    `# ${result.title} — Playthrough Save Summary`,
    "",
    `_Source: \`${filename}\` · generated ${ts} · sl2_to_md_`,
    "",
    "---",
    "",
  ];
  const body = [];
  if (!result.characters.length) body.push("_No populated character slots found._");
  for (const { slot, ch } of result.characters) {
    body.push(mdCharacter(ch, slot));
    body.push("---", "");
  }
  if (result.game === "er") body.push(ER_NOTE, "");
  if (result.game === "sdt") body.push(SDT_NOTE, "");
  // The save version is the one footer line that is about the FILE rather than the
  // tool; it sits here because it belongs to no single character. See footer_for.
  const ver =
    result.saveVersion != null ? [`- **Save format version:** ${result.saveVersion}`] : [];
  if (result.gamePatch != null)
    ver.push(`- **Game patch:** ${result.gamePatch}  _(from the save's own regulation)_`);
  if (result.steam != null) {
    ver.push(
      `- **Steam account:** ${result.steam[0]}  _(SteamID64 ${result.steam[1]} — the account this save was written by)_`,
    );
  }
  if (result.saveFolder != null) {
    ver.push(
      `- **Save folder:** \`${result.saveFolder}\`  _(the game loads this save only from a folder of this name)_`,
    );
  }
  const footer = [
    "<details>",
    "<summary>About this file — how it was produced, and how far to trust it</summary>",
    "",
    `- **Game:** ${result.title}`,
    `- **Support tier:** ${result.tier || "full"}` +
      (result.coverage ? `  _(${result.coverage})_` : ""),
    `- **Character slots read:** ${result.characters.length}`,
    ...ver,
    "",
    disclaimer,
    "",
    "</details>",
    "",
  ];
  return head.concat(body, footer).join("\n");
}
