// Shared lookup tables and formatters used by the DOM renderer (render.js).

export const STAT_ABBR = { Vigor: "VGR", Endurance: "END", Vitality: "VIT", Attunement: "ATN",
  Strength: "STR", Dexterity: "DEX", Adaptability: "ADP", Intelligence: "INT", Faith: "FTH",
  Resistance: "RES", Luck: "LCK", Mind: "MND", Arcane: "ARC" };

// What each attribute governs, per game. Static game fact (not read from the save,
// never a copied stat value) so it is true for any build — obeys the "never print
// wrong" rule. Keyed by game family: the same attribute name differs across games
// (DS1 Vitality is HP; DS2/DS3 Vitality is equip load). Mirrors Python STAT_GOVERNS.
export const STAT_GOVERNS = {
  ds1: [
    ["Vitality", "Max HP"],
    ["Attunement", "Attunement (spell) slots"],
    ["Endurance", "Stamina, equip load, physical defense"],
    ["Strength", "Physical attack, strength-weapon scaling"],
    ["Dexterity", "Physical attack, dex-weapon scaling, faster casting"],
    ["Resistance", "Poison/bleed resistance, fire defense"],
    ["Intelligence", "Magic attack, sorcery scaling"],
    ["Faith", "Miracle scaling, lightning & magic defense"],
  ],
  ds2sotfs: [
    ["Vigor", "Max HP"],
    ["Endurance", "Stamina"],
    ["Vitality", "Equip load, physical defense, petrify resistance"],
    ["Attunement", "Attunement (spell) slots, casting speed"],
    ["Strength", "Physical attack, strength-weapon scaling"],
    ["Dexterity", "Physical attack, dex-weapon scaling, casting speed"],
    ["Adaptability", "Agility (i-frames), poison/bleed/petrify resistance"],
    ["Intelligence", "Magic & dark attack, sorcery/hex scaling"],
    ["Faith", "Lightning & dark attack, miracle/hex scaling"],
  ],
  ds3: [
    ["Vigor", "Max HP"],
    ["Attunement", "FP, attunement (spell) slots"],
    ["Endurance", "Stamina"],
    ["Vitality", "Equip load, physical defense"],
    ["Strength", "Physical attack, strength-weapon scaling"],
    ["Dexterity", "Physical attack, dex-weapon scaling, faster casting"],
    ["Intelligence", "Magic attack, sorcery & pyromancy scaling"],
    ["Faith", "Lightning & dark attack, miracle & pyromancy scaling"],
    ["Luck", "Item discovery, bleed/poison buildup, hollow-weapon scaling"],
  ],
  er: [
    ["Vigor", "Max HP, fire defense & immunity"],
    ["Mind", "FP (skill/spell points), focus resistance"],
    ["Endurance", "Stamina, equip load, robustness"],
    ["Strength", "Physical attack, strength-weapon scaling"],
    ["Dexterity", "Dex-weapon scaling, faster casting, less fall damage"],
    ["Intelligence", "Sorcery scaling, magic defense"],
    ["Faith", "Incantation scaling"],
    ["Arcane", "Item discovery, arcane-weapon scaling, death/holy resistance"],
  ],
};

/** Attribute→governs map for a per-slot game id (DSR and PtDE share DS1). */
export function statGovernsFor(game) {
  const m = STAT_GOVERNS[game === "dsr" || game === "ptde" ? "ds1" : game] || [];
  return new Map(m);
}

/**
 * Attribute display order for a game's own level-up screen. STAT_GOVERNS already
 * lists each family in that exact on-screen order, so reuse it — the renderer walks
 * this to lay a slot's attributes out the way the game itself does.
 */
export function attrOrderFor(game) {
  const fam = game === "dsr" || game === "ptde" ? "ds1" : game;
  return (STAT_GOVERNS[fam] || []).map(([n]) => n);
}

/** Detected per-slot game id → visual theme family (dsr/ptde collapse to ds1). */
export const GAME_THEME = { dsr: "ds1", ptde: "ds1", ds2sotfs: "ds2", ds3: "ds3", er: "er" };

// Soft-cap / per-level breakpoint reference per attribute, per game. Documented
// scaling RATES and soft-cap levels — a game-mechanics fact, NOT a per-character
// computed value (computing the absolute would be wrong: DS2 Vigor 36 reads HP 1351
// in-save vs 1420 from the flat table). Mirrors Python STAT_CAPS.
export const STAT_CAPS = {
  ds1: [
    ["Vitality", "soft caps 30 (~1,100 HP) & 50 (~1,500 HP), rising to ~1,900 at 99"],
    ["Attunement", "1 slot at 10, then 12/14/16/19/23/28/34/41/50 — 10 slots max at 50"],
    ["Endurance", "stamina maxes at 40 (160); equip load keeps rising (~+1/lvl) to 99"],
    ["Strength", "scaling soft cap 40"],
    ["Dexterity", "scaling soft cap 40; cast speed improves to 45"],
    ["Resistance", "minor per-level gains — commonly a dump stat"],
    ["Intelligence", "scaling soft cap 40"],
    ["Faith", "scaling soft cap 40"],
  ],
  ds2sotfs: [
    ["Vigor", "soft caps 20 & 50; +30 HP/lvl to 20, +20 to 50, +5 after"],
    ["Endurance", "soft cap 20; +2 stamina/lvl to 20, +1 after"],
    ["Vitality", "soft caps 29/49/70; +1.5 load/lvl to 29, +1 to 49, +0.5 to 69, +0.25 after"],
    ["Attunement", "slots at 10/13/16/20/25/30/40/50/60/75/94; cast-speed breakpoints 30/45/60/80"],
    ["Strength", "scaling soft caps 40 & 50"],
    ["Dexterity", "scaling soft caps 40 & 50"],
    ["Adaptability", "raises Agility (with Attunement); gains taper past ~40"],
    ["Intelligence", "scaling soft caps 40 & 50"],
    ["Faith", "scaling soft caps 40 & 50"],
  ],
  ds3: [
    ["Vigor", "soft caps ~27 & 50; ~1,300 HP at 50, only ~100 more to 99"],
    ["Attunement", "FP soft cap 35 (450 max at 99); slots at 10/14/18/24/30/40/50/60/80/99"],
    ["Endurance", "stamina soft cap 40"],
    ["Vitality", "roughly linear to 99"],
    ["Strength", "scaling soft caps 40 & 60"],
    ["Dexterity", "scaling soft caps 40 & 60"],
    ["Intelligence", "scaling soft caps 40 & 60"],
    ["Faith", "scaling soft caps 40 & 60"],
    ["Luck", "+1 item discovery/pt (base 100); bleed/poison speed soft cap 50"],
  ],
  er: [
    ["Vigor", "soft caps 40 & 60"],
    ["Mind", "soft caps 50 & 60"],
    ["Endurance", "stamina soft caps 15/30/50; equip load 25/60"],
    ["Strength", "scaling soft caps 20/50/80"],
    ["Dexterity", "scaling soft caps 20/50/80"],
    ["Intelligence", "scaling soft caps 20/50/80"],
    ["Faith", "scaling soft caps 20/50/80"],
    ["Arcane", "scaling soft caps 20/50/80; also raises item discovery"],
  ],
};

/** Soft-cap reference map for a per-slot game id (DSR and PtDE share DS1). */
export function statCapsFor(game) {
  const m = STAT_CAPS[game === "dsr" || game === "ptde" ? "ds1" : game] || [];
  return new Map(m);
}

/** Capitalize the first character only (keeps "HP"/"FP" intact, unlike toUpperCase). */
export const capFirst = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export const CAT_TITLE = { weapons: "Weapons", armors: "Armor", rings: "Rings", talismans: "Talismans",
  spells: "Spells", bolts: "Ammunition", upgrade: "Upgrade Materials", consumables: "Consumables",
  online: "Summon & Covenant Items", goods: "Consumables & Goods", ashes: "Ashes of War",
  emotes: "Gestures", bosssouls: "Boss Souls", items: "Items Owned" };

export const CAT_ORDER = ["weapons", "armors", "rings", "talismans", "spells", "bolts", "upgrade",
  "consumables", "goods", "ashes", "online", "bosssouls", "emotes", "items"];

export const DS2_GREAT_SOULS = new Set(["Old Witch Soul", "Old Dead One Soul", "Old King Soul", "Old Paledrake Soul"]);

// Boss-defeat evidence tag → printed label.
export const SRC = { flag: "confirmed", soul: "soul held", gate: "progression", clear: "cleared (NG+)" };

/** Rough build label from the attribute spread. Mirrors Python guess_build. */
export function guessBuild(stats) {
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

/** Roll i-frames by Agility value (fextralife/community breakpoints); highest key <= AGL. */
const DS2_IFRAMES = [[85, 5], [86, 8], [88, 9], [92, 10], [96, 11], [99, 12], [105, 13], [111, 14], [114, 15], [116, 16]];
/** Attunement values that unlock a spell slot; slot count = how many are <= ATN. */
const DS2_SLOT_BREAKS = [10, 13, 16, 20, 25, 30, 40, 50, 60, 75, 94];
/** Physical attack bonus (ATK: Str/Dex) decade breakpoints; weapon-independent curve. */
const DS2_PHYS_ATK_BP = [[0, 50], [10, 57], [20, 80], [30, 102], [40, 140], [50, 155], [60, 162], [70, 170], [80, 185], [90, 192], [99, 200]];

/** ATK: Str/Dex at a stat value: linear-interpolate the decade breakpoints, floored. */
function ds2PhysAtk(stat) {
  stat = Math.max(0, Math.min(stat, 99));
  const lo = Math.min(Math.floor(stat / 10) * 10, 90);
  const hi = lo === 90 ? 99 : lo + 10;
  const vlo = DS2_PHYS_ATK_BP.find(([k]) => k === lo)[1];
  const vhi = DS2_PHYS_ATK_BP.find(([k]) => k === hi)[1];
  return hi === lo ? vlo : Math.floor(vlo + ((vhi - vlo) * (stat - lo)) / (hi - lo));
}

/** Shared DS2 elemental-defence curve: +6/pt to 10, +8/pt to 20, +1/pt to 60, +0.5/pt to 99. */
function ds2ElemDef(stat) {
  stat = Math.max(0, Math.min(stat, 99));
  let d = 6 * Math.min(stat, 10);
  if (stat > 10) d += 8 * (Math.min(stat, 20) - 10);
  if (stat > 20) d += 1 * (Math.min(stat, 60) - 20);
  if (stat > 60) d += Math.floor((Math.min(stat, 99) - 60) / 2);
  return d;
}

/**
 * DS2 base derived stats (before rings/equipment) from the attribute block. Pure
 * attribute functions verified byte-exact against a real save's Level-Up screen.
 * Mirrors Python ds2_derived_stats. @returns {{stamina, equip_load, agility, iframes}}
 */
export function ds2DerivedStats(stats) {
  const end = stats.Endurance || 0, vit = stats.Vitality || 0;
  const adp = stats.Adaptability || 0, atn = stats.Attunement || 0;
  const stg = stats.Strength || 0, dex = stats.Dexterity || 0;
  const intel = stats.Intelligence || 0, fth = stats.Faith || 0;
  let stamina = 80 + 2 * Math.min(end, 20) + Math.max(0, Math.min(end, 99) - 20);
  if (end >= 99) stamina += 1;
  let load = 38.5 + 1.5 * Math.min(vit, 29);
  if (vit > 29) load += 1.0 * (Math.min(vit, 49) - 29);
  if (vit > 49) load += 0.5 * (Math.min(vit, 70) - 49);
  if (vit > 70) load += 0.5 * Math.floor((Math.min(vit, 99) - 70) / 2);
  const agility = 80 + Math.floor(0.75 * adp + 0.25 * atn + 1e-9);
  let iframes = null;
  for (const [k, v] of DS2_IFRAMES) if (agility >= k) iframes = v;
  const slots = DS2_SLOT_BREAKS.filter((b) => atn >= b).length;
  const nn = Math.min(end, adp);
  let poise = 0.3 * Math.min(nn, 30);
  if (nn > 30) poise += 0.2 * (Math.min(nn, 50) - 30);
  if (nn > 50) poise += 0.1 * (Math.min(nn, 98) - 50);
  if (nn >= 99) poise += 0.2;
  return {
    stamina, equip_load: load, agility, iframes, slots, poise,
    atk_str: ds2PhysAtk(stg), atk_dex: ds2PhysAtk(dex),
    magic_def: ds2ElemDef(intel), fire_def: ds2ElemDef(Math.floor((intel + fth) / 2)),
    lightning_def: ds2ElemDef(fth), dark_def: ds2ElemDef(Math.min(intel, fth)),
  };
}

// DS3 attunement-slot breakpoints (fextralife). Mirror of Python DS3_SLOT_BREAKS.
const DS3_SLOT_BREAKS = [10, 14, 18, 24, 30, 40, 50, 60, 80, 99];
/** DS3 base derived stats from attributes only — attunement slots, base equip load
 *  (40 + VIT), base item discovery (100 + LUCK, cap 199). See sl2_to_md.py. */
export function ds3DerivedStats(stats) {
  const atn = stats.Attunement || 0, vit = stats.Vitality || 0, lck = stats.Luck || 0;
  return {
    slots: DS3_SLOT_BREAKS.filter((b) => atn >= b).length,
    equip_load: 40 + vit,
    item_discovery: Math.min(199, 100 + lck),
  };
}

/** Format a value, or "—" when null. Integers get thousands separators (Python fmt). */
export const fmt = (v) => (v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-US") : String(v));

/** Format a play-time count of seconds as H:MM:SS (hours can exceed 24). */
export const fmtPlaytime = (s) =>
  `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
