// Load the item / progress databases into the shape parser.js expects. Mirrors the
// Python loaders' three id schemes exactly:
//   DS2  — id-keyed {LE-hex: name}  → Map(id → [name, cat]); setdefault (first wins)
//   DS1/DS3 — name-keyed {name: decimal-id} → invert (DS1 last-wins, DS3 first-wins)
//   ER   — {8-hex-id: name} per type → Map(id → name)
// bonfires/boss_flags use big-endian int(hex); DS2 items use little-endian bytes.
//
// Two things matter for page load. Every file in a family is fetched with one
// Promise.all rather than awaited in turn (40 sequential round trips was ~40x RTT
// before the first parse could start), and a caller that already knows the game —
// detectSaveGame only needs the BND4 header — can load that family alone. A DS3
// save needs 11 files, not 40.

const DS2_FILES = { weapons: "weapons", armors: "armors", rings: "rings", spells: "spells",
  key: "keys", bolts: "bolts", upgrade: "upgrade", consumables: "consumables",
  online: "online", emotes: "emotes", bosssouls: "bosssouls" };
const DS1_FILES = { MeleeWeapons: "weapons", Armor: "armors", Rings: "rings", Consumables: "goods" };
const DS3_FILES = { weapons: "weapons", armors: "armors", rings: "rings", goods: "goods", bolts: "bolts", spells: "spells" };
const ER_FILES = ["weapons", "armors", "talismans", "goods", "ashes"];
// Sekiro: decimal id-keyed, one file per item type, plus a dev-name file per type kept
// SEPARATE on purpose — those are engine strings, not item names. See load_sdt_db.
const SDT_FILES = ["weapons", "armors", "goods"];

/** Detected per-slot game id → the db_* family it reads. Mirrors the Python routing. */
export const DB_FAMILY = { dsr: "ds1", ptde: "ds1", ds2sotfs: "ds2", ds2vanilla: "ds2",
  ds3: "ds3", er: "er", sdt: "sdt" };

export const ALL_FAMILIES = ["ds1", "ds2", "ds3", "er", "sdt"];

/** Little-endian byte-hex ("d0093500") → integer, matching Python from_bytes(...,"little"). */
function hexLE(hx) {
  hx = hx.replace(/\s+/g, "");
  let v = 0;
  for (let i = 0; i < hx.length; i += 2) v += parseInt(hx.substr(i, 2), 16) * 256 ** (i / 2);
  return v;
}

/** Fetch one JSON file, or null if it is missing — a db file is always optional. */
async function jget(getJSON, path) {
  try { return await getJSON(path); } catch { return null; }
}

/**
 * Fetch every path in one round instead of one at a time.
 * @returns {Promise<Array>} results in the SAME order as `paths` — which the
 * first-wins / last-wins id rules depend on, so the order is load-bearing.
 */
const jgetAll = (getJSON, paths) => Promise.all(paths.map((p) => jget(getJSON, p)));

const toMap16 = (j) => {
  const m = new Map();
  if (j) for (const [k, v] of Object.entries(j)) m.set(parseInt(k, 16), v);
  return m;
};

// ── Per-family loaders. Each returns the slice of the bundle parser.js reads. ──

async function loadDs1(getJSON) {
  const stems = Object.keys(DS1_FILES);
  const [items, extra] = await Promise.all([
    jgetAll(getJSON, stems.map((s) => `db_ds1/${s}.json`)),
    jgetAll(getJSON, ["db_ds1/boss_souls.json", "db_ds1/bonfires.json", "db_ds1/boss_flags.json"]),
  ]);
  // name-keyed decimal, per-category, last-wins.
  const table = {};
  stems.forEach((stem, i) => {
    if (!items[i]) return;
    const m = new Map();
    for (const [name, id] of Object.entries(items[i])) m.set(Number(id), name);
    table[DS1_FILES[stem]] = m;
  });
  const bonfires = extra[1] || {};
  return { items: table, bossSouls: extra[0] || {}, bonfires, bossFlags: extra[2] || {},
           bonfireTotal: Object.keys(bonfires).length };
}

async function loadDs2(getJSON) {
  const stems = Object.keys(DS2_FILES);
  const [items, extra] = await Promise.all([
    jgetAll(getJSON, stems.map((s) => `db_ds2/${s}.json`)),
    jgetAll(getJSON, ["db_ds2/bonfires.json", "db_ds2/boss_flags.json", "db_ds2/bonfire_areas.json",
                      "db_ds2/boss_souls.json"]),
  ]);
  // id-keyed, setdefault — first file to claim an id keeps it, so stem order matters.
  const table = new Map();
  stems.forEach((stem, i) => {
    if (!items[i]) return;
    for (const [hx, name] of Object.entries(items[i])) {
      const id = hexLE(hx);
      if (!table.has(id)) table.set(id, [name, DS2_FILES[stem]]);
    }
  });
  const bonfires = toMap16(extra[0]);
  return { items: table, bonfires, bossFlags: toMap16(extra[1]),
           bonfireAreas: toMap16(extra[2]), bossSouls: extra[3] || {},
           bonfireTotal: bonfires.size };
}

// DS3 keeps every "good" in one file, but the ids block out by kind — so `goods`
// splits into the finer categories the render already prints for DS2. Ranges read
// off db_ds3/goods.json itself; see DS3_GOODS_RANGES in sl2_to_md.py.
const DS3_GOODS_ID_BASE = 0x40000000;
const DS3_GOODS_RANGES = [[100, 149, "online"], [150, 519, "consumables"],
  [520, 599, "online"], [600, 699, "consumables"], [700, 799, "bosssouls"],
  [1000, 1299, "upgrade"], [2000, 2199, "keys"]];
const DS3_GOODS_OVERRIDE = { 117: "consumables",  // Darksign (not a summon item)
  2141: "upgrade", 2143: "upgrade" };             // Estus Shard / Undead Bone Shard

function ds3GoodsCat(iid) {
  const real = iid - DS3_GOODS_ID_BASE;
  if (DS3_GOODS_OVERRIDE[real]) return DS3_GOODS_OVERRIDE[real];
  for (const [lo, hi, cat] of DS3_GOODS_RANGES) if (real >= lo && real <= hi) return cat;
  return "goods";
}

async function loadDs3(getJSON) {
  const stems = Object.keys(DS3_FILES);
  const [items, extra] = await Promise.all([
    jgetAll(getJSON, stems.map((s) => `db_ds3/${s}.json`)),
    jgetAll(getJSON, ["db_ds3/boss_souls.json", "db_ds3/bonfires.json", "db_ds3/boss_flags.json",
                      "db_ds3/questlines.json", "db_ds3/covenants.json",
                      "db_ds3/boss_victory.json", "db_ds3/lord_cinders.json",
                      "db_ds3/boss_route.json", "db_ds3/item_pickups.json",
                      "db_ds3/ring_effects.json", "db_ds3/endings.json"]),
  ]);
  // name-keyed decimal, flat id→[name,cat], first-wins.
  const table = new Map();
  stems.forEach((stem, i) => {
    if (!items[i]) return;
    for (const [name, id] of Object.entries(items[i])) {
      const n = Number(id);
      const cat = DS3_FILES[stem];
      if (!table.has(n)) table.set(n, [name, cat === "goods" ? ds3GoodsCat(n) : cat]);
    }
  });
  const bonfires = extra[1] || {};
  return { items: table, bossSouls: extra[0] || {}, bonfires, bossFlags: extra[2] || {},
           questlines: extra[3] || {}, covenants: extra[4] || {},
           bossVictory: extra[5] || {}, lordCinders: extra[6] || {},
           bossRoute: extra[7] || {}, pickups: extra[8] || {},
           ringEffects: extra[9] || {}, endings: extra[10] || {},
           // DS3 groups bonfires by area, so the total is the sum of the area lists.
           bonfireTotal: Object.values(bonfires).reduce((s, a) => s + a.length, 0) };
}

async function loadEr(getJSON) {
  const [items, bossSouls] = await Promise.all([
    jgetAll(getJSON, ER_FILES.map((c) => `db_er/${c}.json`)),
    jget(getJSON, "db_er/boss_souls.json"),
  ]);
  const table = {};
  ER_FILES.forEach((cat, i) => { if (items[i]) table[cat] = toMap16(items[i]); });
  return { items: table, bossSouls: bossSouls || {} };
}

/** Decimal id-keyed {id: name} → Map(number → name). Sekiro's scheme, the simplest. */
const toMap10 = (j) => {
  const m = new Map();
  if (j) for (const [k, v] of Object.entries(j)) m.set(Number(k), v);
  return m;
};

async function loadSdt(getJSON) {
  const paths = [...SDT_FILES.map((c) => `db_sdt/${c}.json`),
    ...SDT_FILES.map((c) => `db_sdt/${c}_devnames.json`),
    "db_sdt/prosthetics.json", "db_sdt/boss_souls.json", "db_sdt/boss_flags.json"];
  const got = await jgetAll(getJSON, paths);
  const names = {}, dev = {};
  SDT_FILES.forEach((cat, i) => {
    names[cat] = toMap10(got[i]);
    dev[cat] = toMap10(got[i + SDT_FILES.length]);
  });
  const rest = SDT_FILES.length * 2;
  return { names, dev, prosthetics: new Set(toMap10(got[rest]).keys()),
           bossSouls: got[rest + 1] || {}, bossFlags: got[rest + 2] || {} };
}

const LOADERS = { ds1: loadDs1, ds2: loadDs2, ds3: loadDs3, er: loadEr, sdt: loadSdt };

/**
 * An unloaded family still has to answer every lookup parseSave makes, so a family
 * that was skipped is present and empty rather than missing. That way loading one
 * game can never turn a lookup into a TypeError.
 */
const EMPTY = {
  ds1: () => ({ items: {}, bossSouls: {}, bonfires: {}, bossFlags: {}, bonfireTotal: 0 }),
  ds2: () => ({ items: new Map(), bonfires: new Map(), bonfireAreas: new Map(),
                bossFlags: new Map(), bossSouls: {}, bonfireTotal: 0 }),
  ds3: () => ({ items: new Map(), bossSouls: {}, bonfires: {}, bossFlags: {},
                questlines: {}, covenants: {}, bossVictory: {}, lordCinders: {},
                bossRoute: {}, pickups: {}, ringEffects: {}, endings: {},
                bonfireTotal: 0 }),
  er: () => ({ items: {}, bossSouls: {} }),
  sdt: () => ({ names: {}, dev: {}, prosthetics: new Set(), bossSouls: {}, bossFlags: {} }),
};

/**
 * Load only the families named, in parallel. `getJSON(relPath)` returns parsed JSON
 * (or throws if missing). Families not requested come back empty, so the returned
 * bundle is always the full shape parseSave expects.
 * @param {(p: string) => Promise<any>} getJSON
 * @param {string[]} families subset of ALL_FAMILIES
 */
export async function loadDbsFor(getJSON, families) {
  const want = ALL_FAMILIES.filter((f) => families.includes(f));
  const loaded = await Promise.all(want.map((f) => LOADERS[f](getJSON)));
  const dbs = {};
  for (const f of ALL_FAMILIES) dbs[f] = EMPTY[f]();
  want.forEach((f, i) => { dbs[f] = loaded[i]; });
  return dbs;
}

/** Every database, all four games. The parity harnesses and any offline use want this. */
export const loadAllDbs = (getJSON) => loadDbsFor(getJSON, ALL_FAMILIES);

/** The db_* files a family needs — used by the service worker to precache them. */
export function dbPathsFor(family) {
  if (family === "ds1") {
    return [...Object.keys(DS1_FILES).map((s) => `db_ds1/${s}.json`),
      "db_ds1/boss_souls.json", "db_ds1/bonfires.json", "db_ds1/boss_flags.json"];
  }
  if (family === "ds2") {
    return [...Object.keys(DS2_FILES).map((s) => `db_ds2/${s}.json`),
      "db_ds2/bonfires.json", "db_ds2/boss_flags.json", "db_ds2/bonfire_areas.json",
      "db_ds2/boss_souls.json"];
  }
  if (family === "ds3") {
    return [...Object.keys(DS3_FILES).map((s) => `db_ds3/${s}.json`),
      "db_ds3/boss_souls.json", "db_ds3/bonfires.json", "db_ds3/boss_flags.json",
      "db_ds3/questlines.json", "db_ds3/covenants.json", "db_ds3/boss_victory.json",
      "db_ds3/lord_cinders.json", "db_ds3/boss_route.json", "db_ds3/item_pickups.json",
      "db_ds3/ring_effects.json", "db_ds3/endings.json"];
  }
  if (family === "er") {
    return [...ER_FILES.map((c) => `db_er/${c}.json`), "db_er/boss_souls.json"];
  }
  return [...SDT_FILES.map((c) => `db_sdt/${c}.json`),
    ...SDT_FILES.map((c) => `db_sdt/${c}_devnames.json`),
    "db_sdt/prosthetics.json", "db_sdt/boss_souls.json", "db_sdt/boss_flags.json"];
}
