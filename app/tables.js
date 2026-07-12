// Shared lookup tables and formatters used by the DOM renderer (render.js).

export const STAT_ABBR = { Vigor: "VGR", Endurance: "END", Vitality: "VIT", Attunement: "ATN",
  Strength: "STR", Dexterity: "DEX", Adaptability: "ADP", Intelligence: "INT", Faith: "FTH",
  Resistance: "RES", Luck: "LCK", Mind: "MND", Arcane: "ARC" };

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
