// Load the item / progress databases into the shape parser.js expects. Mirrors the
// Python loaders' three id schemes exactly:
//   DS2  — id-keyed {LE-hex: name}  → Map(id → [name, cat]); setdefault (first wins)
//   DS1/DS3 — name-keyed {name: decimal-id} → invert (DS1 last-wins, DS3 first-wins)
//   ER   — {8-hex-id: name} per type → Map(id → name)
// bonfires/boss_flags use big-endian int(hex); DS2 items use little-endian bytes.

const DS2_FILES = { weapons: "weapons", armors: "armors", rings: "rings", spells: "spells",
  key: "keys", bolts: "bolts", upgrade: "upgrade", consumables: "consumables",
  online: "online", emotes: "emotes", bosssouls: "bosssouls" };
const DS1_FILES = { MeleeWeapons: "weapons", Armor: "armors", Rings: "rings", Consumables: "goods" };
const DS3_FILES = { weapons: "weapons", armors: "armors", rings: "rings", goods: "goods", bolts: "bolts", spells: "spells" };
const ER_FILES = ["weapons", "armors", "talismans", "goods", "ashes"];

/** Little-endian byte-hex ("d0093500") → integer, matching Python from_bytes(...,"little"). */
function hexLE(hx) {
  hx = hx.replace(/\s+/g, "");
  let v = 0;
  for (let i = 0; i < hx.length; i += 2) v += parseInt(hx.substr(i, 2), 16) * 256 ** (i / 2);
  return v;
}

async function jget(getJSON, path) {
  try { return await getJSON(path); } catch { return null; }
}

/**
 * Load every database. `getJSON(relPath)` returns parsed JSON (or throws if missing).
 * Returns the `dbs` bundle consumed by parseSave.
 */
export async function loadAllDbs(getJSON) {
  // DS2 items: id-keyed, setdefault.
  const ds2Items = new Map();
  for (const [stem, cat] of Object.entries(DS2_FILES)) {
    const j = await jget(getJSON, `db_ds2/${stem}.json`);
    if (!j) continue;
    for (const [hx, name] of Object.entries(j)) {
      const id = hexLE(hx);
      if (!ds2Items.has(id)) ds2Items.set(id, [name, cat]);
    }
  }
  const toMap16 = (j) => { const m = new Map(); if (j) for (const [k, v] of Object.entries(j)) m.set(parseInt(k, 16), v); return m; };
  const ds2Bonfires = toMap16(await jget(getJSON, "db_ds2/bonfires.json"));
  const ds2BossFlags = toMap16(await jget(getJSON, "db_ds2/boss_flags.json"));

  // DS1 items: name-keyed decimal, per-category, last-wins.
  const ds1Items = {};
  for (const [stem, cat] of Object.entries(DS1_FILES)) {
    const j = await jget(getJSON, `db_ds1/${stem}.json`);
    if (!j) continue;
    const m = new Map();
    for (const [name, id] of Object.entries(j)) m.set(Number(id), name);
    ds1Items[cat] = m;
  }

  // DS3 items: name-keyed decimal, flat id→[name,cat], first-wins.
  const ds3Items = new Map();
  for (const [stem, cat] of Object.entries(DS3_FILES)) {
    const j = await jget(getJSON, `db_ds3/${stem}.json`);
    if (!j) continue;
    for (const [name, id] of Object.entries(j)) {
      const n = Number(id);
      if (!ds3Items.has(n)) ds3Items.set(n, [name, cat]);
    }
  }

  // ER items: hex-id → name, per category.
  const erItems = {};
  for (const cat of ER_FILES) {
    const j = await jget(getJSON, `db_er/${cat}.json`);
    if (!j) continue;
    const m = new Map();
    for (const [k, v] of Object.entries(j)) m.set(parseInt(k, 16), v);
    erItems[cat] = m;
  }

  return {
    ds2: { items: ds2Items, bonfires: ds2Bonfires, bossFlags: ds2BossFlags,
           bossSouls: (await jget(getJSON, "db_ds2/boss_souls.json")) || {} },
    ds1: { items: ds1Items, bossSouls: (await jget(getJSON, "db_ds1/boss_souls.json")) || {} },
    ds3: { items: ds3Items, bossSouls: (await jget(getJSON, "db_ds3/boss_souls.json")) || {} },
    er: { items: erItems, bossSouls: (await jget(getJSON, "db_er/boss_souls.json")) || {} },
  };
}
