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

export const CAT_TITLE = { weapons: "Weapons", armors: "Armor", rings: "Rings", talismans: "Talismans",
  spells: "Spells", bolts: "Ammunition", upgrade: "Upgrade Materials", consumables: "Consumables",
  online: "Summon & Covenant Items", goods: "Consumables & Goods", ashes: "Ashes of War",
  emotes: "Gestures", bosssouls: "Boss Souls", items: "Items Owned" };

export const CAT_ORDER = ["weapons", "armors", "rings", "talismans", "spells", "bolts", "upgrade",
  "consumables", "goods", "ashes", "online", "bosssouls", "emotes", "items"];

export const DS2_GREAT_SOULS = new Set(["Old Witch Soul", "Old Dead One Soul", "Old King Soul", "Old Paledrake Soul"]);

// Boss-defeat evidence tag → printed label.
export const SRC = { flag: "confirmed", soul: "soul held", gate: "progression" };

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

/** Format a value, or "—" when null. Integers get thousands separators (Python fmt). */
export const fmt = (v) => (v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-US") : String(v));

/** Format a play-time count of seconds as H:MM:SS (hours can exceed 24). */
export const fmtPlaytime = (s) =>
  `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
