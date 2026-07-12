// Port of sl2_to_md.py's parsing pipeline to the browser: parse_bnd4 → detect_game
// → per-game parse/augment → unified `ch` objects. Byte-for-byte faithful to the
// Python tool (gated by scratch/harness.mjs, which diffs this against the Python
// reference dumps). Render lives in render.js; this module produces data only.

import { u8, u16, u32, u64, readUtf16, isValidName, indexOf } from "./reader.js";
import { aesCbcDecrypt, hexToBytes } from "./aes.js";

const DS2_KEY = hexToBytes("599F9B699640A55236EE2D70835EC744");
const DSR_KEY = hexToBytes("0123456789ABCDEFFEDCBA9876543210");
const DS3_KEY = hexToBytes("FD464D695E69A39A10E319A7ACE8B7FA");

const BND4_HEADER_LEN = 64, BND4_ENTRY_LEN = 32;

class ParseError extends Error {}

// ── BND4 archive ────────────────────────────────────────────────────────────
function parseBnd4(data) {
  if (data.length < BND4_HEADER_LEN ||
      !(data[0] === 0x42 && data[1] === 0x4e && data[2] === 0x44 && data[3] === 0x34)) {
    throw new ParseError("Not a BND4 / .sl2 file.");
  }
  const count = u32(data, 12);
  if (count == null || !(count > 0 && count <= 64)) {
    throw new ParseError(`Implausible BND4 entry count: ${count}`);
  }
  const entries = [];
  for (let i = 0; i < count; i++) {
    const base = BND4_HEADER_LEN + BND4_ENTRY_LEN * i;
    if (base + BND4_ENTRY_LEN > data.length) throw new ParseError(`Truncated entry header #${i}.`);
    const size = u64(data, base + 8);
    const offset = u32(data, base + 16);
    if (size == null || offset == null || offset + size > data.length || size <= 0) {
      throw new ParseError(`Entry #${i} points outside the file.`);
    }
    entries.push({ index: i, offset, size });
  }
  return entries;
}

const blobOf = (data, e) => data.subarray(e.offset, e.offset + e.size);

// ── AES helpers ─────────────────────────────────────────────────────────────
function aesCbc(key, iv, ct) {
  const n = Math.floor(ct.length / 16) * 16;
  return aesCbcDecrypt(key, iv, ct.subarray(0, n));
}
function decryptDs2(blob) {
  const pt = aesCbc(DS2_KEY, blob.subarray(16, 32), blob.subarray(32));
  const dlen = u32(pt, 0);
  return dlen == null ? null : pt.subarray(4, 4 + dlen);
}
function decryptIvPrefixed(blob, key) {
  const dec = aesCbc(key, blob.subarray(16, 32), blob.subarray(16));
  const dlen = u32(dec, 16);
  return dlen == null ? null : dec.subarray(20, 20 + dlen);
}
const decryptNone = (blob) => blob.subarray(16);

// ── Detection ─────────────────────────────────────────────────────────────
const DS2_SIGNATURE = [0x31, 0x34, 0x65, 0x35, 0x30, 0x33, 0x63, 0x62]; // "14e503cb"
function sigMatch(data, bytes) {
  for (let i = 0; i < bytes.length; i++) if (data[24 + i] !== bytes[i]) return false;
  return true;
}
function detectGame(data, entries) {
  const n = entries.length;
  if (sigMatch(data, DS2_SIGNATURE)) {
    const blob = blobOf(data, entries[1]);
    const pt = aesCbc(DS2_KEY, blob.subarray(16, 32), blob.subarray(32));
    const dlen = u32(pt, 0);
    if (dlen != null && dlen > 0 && dlen <= pt.length - 4) return "ds2sotfs";
    throw new ParseError("Vanilla Dark Souls II is not supported — its AES key is not public. Re-save in Scholar of the First Sin.");
  }
  if (n === 11) {
    let allZero = true;
    for (let i = 24; i < 32; i++) if (data[i] !== 0) { allZero = false; break; }
    return allZero ? "dsr" : "ptde";
  }
  if (n === 12) return entries[0].size > 2_000_000 ? "er" : "ds3";
  throw new ParseError("Unrecognised .sl2 — not a supported Souls save.");
}

// ── Shared progress inference ────────────────────────────────────────────────
const GENERIC_SOULS = new Set([
  "Fading Soul", "Soul of a Lost Undead", "Large Soul of a Lost Undead",
  "Soul of a Nameless Soldier", "Large Soul of a Nameless Soldier",
  "Soul of a Proud Knight", "Large Soul of a Proud Knight",
  "Soul of a Brave Warrior", "Large Soul of a Brave Warrior",
  "Soul of a Hero", "Soul of a Great Hero", "Soul of a Old Hero",
  "Wandering Soul", "Old Soul",
  "Soul of a Deserted Corpse", "Large Soul of a Deserted Corpse",
  "Soul of an Unknown Traveler", "Large Soul of an Unknown Traveler",
  "Soul of a Weary Warrior", "Large Soul of a Weary Warrior",
  "Soul of a Crestfallen Knight", "Large Soul of a Crestfallen Knight",
  "Soul of a Venerable Old Hand", "Soul of a Champion", "Soul of a Great Champion",
  "Soul of a Seasoned Warrior", "Large Soul of a Seasoned Warrior",
  "Soul of an Intrepid Hero", "Large Soul of an Intrepid Hero",
]);
const DS1_PROGRESSION = new Set(["Lordvessel", "Peculiar Doll", "Broken Pendant", "Rite of Kindling"]);
const BOSS_SOUL_EXTRA = new Set(["Core of an Iron Golem", "Guardian Soul", "Soul (Nito)", "Soul (Bed of Chaos)"]);

function findBossSouls(goods) {
  const out = [];
  for (const [n, q] of goods) {
    if (GENERIC_SOULS.has(n)) continue;
    if (n.includes("Soul of ") || n.includes("Lord Soul") || BOSS_SOUL_EXTRA.has(n)) out.push([n, q]);
  }
  return out;
}
function findKeyGoods(goods) {
  return goods.filter(([n]) => n.includes("Key") || DS1_PROGRESSION.has(n));
}

const BOSS_SOUL_DB_DIR = { dsr: "ds1", ptde: "ds1", ds3: "ds3", er: "er" };
const BOSS_PREREQ = {
  ds3: {
    "Soul of Cinder": ["Iudex Gundyr", "Vordt of the Boreal Valley",
      "Dancer of the Boreal Valley", "Abyss Watchers", "Aldrich, Devourer of Gods",
      "Yhorm the Giant", "Lothric, Younger Prince"],
    "Lothric, Younger Prince": ["Dancer of the Boreal Valley", "Vordt of the Boreal Valley", "Iudex Gundyr"],
    "Aldrich, Devourer of Gods": ["Pontiff Sulyvahn", "Vordt of the Boreal Valley", "Iudex Gundyr"],
    "Dancer of the Boreal Valley": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
    "Pontiff Sulyvahn": ["Vordt of the Boreal Valley", "Iudex Gundyr"],
    "Vordt of the Boreal Valley": ["Iudex Gundyr"],
  },
  er: {
    "Godfrey, First Elden Lord (Hoarah Loux)": ["Maliketh, the Black Blade", "Fire Giant", "Morgott, the Omen King"],
    "Maliketh, the Black Blade": ["Fire Giant", "Morgott, the Omen King"],
    "Fire Giant": ["Morgott, the Omen King"],
  },
};

function attachDefeatedBosses(ch, dbs) {
  const family = BOSS_SOUL_DB_DIR[ch.game];
  if (!family || ch.bosses) return;
  const soulDb = dbs[family].bossSouls || {};
  const bosses = new Map();
  for (const [name] of ch.boss_souls || []) {
    const boss = soulDb[name];
    if (boss) (bosses.get(boss) || bosses.set(boss, new Set()).get(boss)).add("soul");
  }
  const prereq = BOSS_PREREQ[ch.game] || {};
  for (const boss of [...bosses.keys()]) {
    for (const pre of prereq[boss] || []) {
      (bosses.get(pre) || bosses.set(pre, new Set()).get(pre)).add("gate");
    }
  }
  if (bosses.size) ch.bosses = mapToSortedEvidence(bosses, false);
}

// Evidence sets → {boss: sorted[str]}. sortKeys mirrors ds2_infer_bosses (sorted by
// boss name); attach keeps insertion order (Python dict), matching the Python paths.
function mapToSortedEvidence(map, sortKeys) {
  const keys = sortKeys ? [...map.keys()].sort() : [...map.keys()];
  const out = {};
  for (const k of keys) out[k] = [...map.get(k)].sort();
  return out;
}

function mergeQty(items) {
  const order = [], agg = new Map();
  for (const [name, q] of items) {
    if (!agg.has(name)) { agg.set(name, 0); order.push(name); }
    agg.set(name, agg.get(name) + q);
  }
  return order.map((n) => [n, agg.get(n)]);
}

// ── DS2 ───────────────────────────────────────────────────────────────────
const DS2_NAME_OFF = 960, DS2_SOULS_OFF = 60, DS2_SOULMEM_OFF = 64, DS2_HP_OFF = 72, DS2_NG_OFF = 1028;
const DS2_TITLE_NAME_OFF = 1286, DS2_TITLE_STRIDE = 496, DS2_TITLE_PLAYTIME_OFF = 66;
const DS2_CLASS_OFF = 1024, DS2_COVENANT_OFF = 189, DS2_GENDER_OFF = 378, DS2_HOLLOW_OFF = 379, DS2_DEATHS_OFF = 104;
const DS2_WORLD_ENTRY_DELTA = 10, DS2_BONFIRE_FLAG_DELTA = 0x200, DS2_BONFIRE_MIN_RUN = 16;
const DS2_REINF_OFF = 12, DS2_INFUSE_OFF = 13;
const DS2_CLASS = { 1: "Warrior", 2: "Knight", 4: "Bandit", 6: "Cleric", 7: "Sorcerer", 8: "Explorer", 9: "Swordsman", 10: "Deprived" };
const DS2_COVENANT = { 1: "Heirs of the Sun", 2: "Blue Sentinels", 3: "Brotherhood of Blood", 4: "Way of Blue", 5: "Rat King", 6: "Bell Keepers", 7: "Dragon Remnants", 8: "Company of Champions", 9: "Pilgrims of Dark" };
const DS2_INFUSION = { 1: "Fire", 2: "Magic", 3: "Lightning", 4: "Dark", 5: "Poison", 6: "Bleed", 7: "Raw", 8: "Enchanted", 9: "Mundane" };
// Gender at +378: Female = 1, Male = 0 (verified by a real F→M differential save pair).
const DS2_GENDER = { 0: "Male", 1: "Female" };
const DS2_STAT_OFF = [["Vigor", 32], ["Endurance", 34], ["Vitality", 36], ["Attunement", 38],
  ["Strength", 40], ["Dexterity", 42], ["Adaptability", 48], ["Intelligence", 44], ["Faith", 46], ["Level", 0x38]];
const DS2_INV_RANGE = [0x1E2C, 0x10E1C], DS2_KEY_RANGE = [0x10E30, 0x11DF0];
const DS2_STACKABLE = new Set(["consumables", "online", "bolts", "spells", "upgrade", "keys", "bosssouls"]);
const DS2_UPGRADEABLE = new Set(["weapons", "armors"]);

function ds2Name(buf) {
  const name = readUtf16(buf, DS2_NAME_OFF, 16);
  return isValidName(name) ? name : null;
}
function ds2Inventory(buf, itemDb) {
  const buckets = {}; let unknown = 0;
  const push = (c, v) => (buckets[c] || (buckets[c] = [])).push(v);
  for (const [start, end] of [DS2_INV_RANGE, DS2_KEY_RANGE]) {
    let o = start;
    const lim = Math.min(end, buf.length);
    while (o + 16 <= lim) {
      const iid = u32(buf, o), qty = u16(buf, o + 8);
      const cur = u8(buf, o + 10), mx = u8(buf, o + 11);
      const reinf = u8(buf, o + DS2_REINF_OFF), infuse = u8(buf, o + DS2_INFUSE_OFF);
      o += 16;
      if (!iid) continue;
      const info = itemDb.get(iid);
      if (info === undefined) { unknown++; continue; }
      let [name, cat] = info;
      if (name === "Estus Flask" && mx) name = `${name} (${cur}/${mx} charges)`;
      if (DS2_UPGRADEABLE.has(cat)) {
        if (cat === "weapons" && DS2_INFUSION[infuse]) name = `${DS2_INFUSION[infuse]} ${name}`;
        if (reinf) name = `${name} +${reinf}`;
      }
      push(cat, [name, DS2_STACKABLE.has(cat) ? qty : 1]);
    }
  }
  return { buckets, unknown };
}
function ds2Parse(buf, itemDb) {
  if (ds2Name(buf) === null) return null;
  const stats = {};
  for (const [k, o] of DS2_STAT_OFF) stats[k] = u16(buf, o) || 0;
  const level = stats["Level"]; delete stats["Level"];
  const { buckets, unknown } = ds2Inventory(buf, itemDb);
  const inv = {};
  for (const c in buckets) inv[c] = mergeQty(buckets[c]);
  const keyItems = inv["keys"] || []; delete inv["keys"];
  return {
    tier: "full", game: "ds2sotfs", name: ds2Name(buf),
    klass: DS2_CLASS[u8(buf, DS2_CLASS_OFF)] ?? null,
    covenant: DS2_COVENANT[u8(buf, DS2_COVENANT_OFF)] ?? null,
    gender: DS2_GENDER[u8(buf, DS2_GENDER_OFF)] ?? null,
    level, stats, souls: u32(buf, DS2_SOULS_OFF), soul_memory: u32(buf, DS2_SOULMEM_OFF),
    humanity: null, stamina: null, hp: u32(buf, DS2_HP_OFF),
    ng_plus: Math.max(0, (u16(buf, DS2_NG_OFF) || 1) - 1),
    hollow_lvl: u8(buf, DS2_HOLLOW_OFF),
    deaths: u32(buf, DS2_DEATHS_OFF),
    boss_souls: [], key_items: keyItems, inv, unknown_count: unknown,
  };
}
const DS2_BOSS_GATE = {
  "Undead Crypt Entrance": ["Looking Glass Knight", "Demon of Song"],
  "Throne Floor": ["Looking Glass Knight", "Demon of Song", "Velstadt, the Royal Aegis"],
};
const DS2_ITEM_GATE = { "King's Ring": ["Velstadt, the Royal Aegis"] };
const DS2_BOSS_PREREQ = {
  "Nashandra": ["Throne Watcher", "Throne Defender", "Velstadt, the Royal Aegis", "Demon of Song", "Looking Glass Knight"],
  "Throne Watcher": ["Velstadt, the Royal Aegis", "Demon of Song", "Looking Glass Knight"],
  "Throne Defender": ["Velstadt, the Royal Aegis", "Demon of Song", "Looking Glass Knight"],
  "Velstadt, the Royal Aegis": ["Demon of Song", "Looking Glass Knight"],
  "Demon of Song": ["Looking Glass Knight"],
};
function ds2InferBosses(world, ch, dbs) {
  const out = new Map();
  const add = (b, e) => (out.get(b) || out.set(b, new Set()).get(b)).add(e);
  for (const [off, name] of dbs.ds2.bossFlags) if (world && u8(world, off)) add(name, "flag");
  const soulDb = dbs.ds2.bossSouls || {};
  for (const [name] of (ch.inv["bosssouls"] || [])) { const b = soulDb[name]; if (b) add(b, "soul"); }
  for (const bonfire of ch.bonfires || []) for (const boss of DS2_BOSS_GATE[bonfire] || []) add(boss, "gate");
  const held = new Set();
  for (const c in ch.inv) for (const [n] of ch.inv[c]) held.add(n);
  for (const [n] of ch.key_items || []) held.add(n);
  for (const item in DS2_ITEM_GATE) if (held.has(item)) for (const boss of DS2_ITEM_GATE[item]) add(boss, "gate");
  for (const boss of [...out.keys()]) for (const pre of DS2_BOSS_PREREQ[boss] || []) add(pre, "gate");
  if (out.size === 0) return null;
  return mapToSortedEvidence(out, true);
}
function ds2VisitedBonfires(world, bfDb) {
  if (!world || bfDb.size === 0) return null;
  let bestStart = -1, bestRun = 0, run = 0, runStart = 0, o = 0;
  while (o + 2 <= world.length) {
    if (bfDb.has(u16(world, o))) {
      runStart = run === 0 ? o : runStart;
      run += 1;
      if (run > bestRun) { bestRun = run; bestStart = runStart; }
    } else run = 0;
    o += 2;
  }
  if (bestRun < DS2_BONFIRE_MIN_RUN) return null;
  const ids = [];
  o = bestStart;
  while (o + 2 <= world.length && ids.length < DS2_BONFIRE_FLAG_DELTA / 2) {
    const v = u16(world, o);
    if (v === 0) break;
    ids.push(v); o += 2;
  }
  const flagBase = bestStart + DS2_BONFIRE_FLAG_DELTA;
  const visited = [];
  ids.forEach((bid, idx) => {
    if (u8(world, flagBase + idx)) visited.push(bfDb.get(bid) ?? `(bonfire 0x${bid.toString(16).padStart(4, "0")})`);
  });
  return visited;
}
function ds2Augment(ch, data, entries, i, dbs) {
  // Play time lives in the header title record (one per slot), not the character
  // block. Title index for block entry i is i - slots.start, and DS2 starts at 1.
  if (entries.length) {
    const hdr = decryptDs2(blobOf(data, entries[0]));
    if (hdr !== null) {
      const base = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - 1);
      ch.play_time = u32(hdr, base + DS2_TITLE_PLAYTIME_OFF);
    }
  }
  const w = i + DS2_WORLD_ENTRY_DELTA;
  if (w >= entries.length) return;
  const world = decryptDs2(blobOf(data, entries[w]));
  ch.bonfires = ds2VisitedBonfires(world, dbs.ds2.bonfires);
  ch.bosses = ds2InferBosses(world, ch, dbs);
}
function ds2ActiveSlots(data, entries, slots) {
  if (!entries.length) return null;
  const hdr = decryptDs2(blobOf(data, entries[0]));
  if (hdr === null) return null;
  const active = new Set();
  for (let i = slots[0]; i < slots[1]; i++) {
    const off = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - slots[0]);
    if (isValidName(readUtf16(hdr, off, 16))) active.add(i);
  }
  return active.size ? active : null;
}

// ── DS1 (DSR + PtDE) ─────────────────────────────────────────────────────
const DSR_MAGIC = hexToBytes("00FFFFFFFF000000000000000000000000FFFFFFFF");
const DSR_SOULS_D = -291, DSR_HP_D = -419, DSR_STAM_D = -391, DSR_LEVEL_D = -295,
  DSR_CLASS_D = -233, DSR_HUM_D = -307, DSR_NG_D = 0x1E3A7, DSR_NAME_D = -271;
const DSR_STAT_D = [["Vitality", -375], ["Attunement", -367], ["Endurance", -359],
  ["Strength", -351], ["Dexterity", -343], ["Resistance", -303], ["Intelligence", -335], ["Faith", -327]];
const DS1_CLASS = { 0: "Warrior", 1: "Knight", 2: "Wanderer", 3: "Thief", 4: "Bandit", 5: "Hunter", 6: "Sorcerer", 7: "Pyromancer", 8: "Cleric", 9: "Deprived" };
const DS1_CAT = { 0x00000000: "weapons", 0x10000000: "armors", 0x20000000: "rings", 0x40000000: "goods" };
const DS1_INV_START = 0x988, DS1_INV_ANCHOR = hexToBytes("0000000000000000A0BB0D00");
const DS1_INV_END = hexToBytes("00000000FFFFFFFFFFFFFFFF");
const DS1_INFUSION = { 1: "Crystal", 2: "Lightning", 3: "Raw", 4: "Magic", 5: "Enchanted", 6: "Divine", 7: "Occult", 8: "Fire", 9: "Chaos" };

function ds1Resolve(itemDb, cat, iid) {
  const table = itemDb[cat] || new Map();
  if (table.has(iid)) return table.get(iid);
  if (cat === "rings") return table.get(Math.floor(iid / 1000)) ?? null;
  if (cat !== "weapons" && cat !== "armors") return null;
  const base = iid - (iid % 1000), path = Math.floor((iid % 1000) / 100), level = iid % 100;
  const name = table.get(base);
  if (name == null) return null;
  const infusion = cat === "weapons" ? DS1_INFUSION[path] : null;
  const suffix = level ? ` +${level}` : "";
  return infusion ? `${name}${suffix} (${infusion})` : `${name}${suffix}`;
}
function statBlockValid(buf, m) {
  const lvl = u16(buf, m + DSR_LEVEL_D);
  if (lvl == null || lvl < 1 || lvl > 838) return false;
  for (const [, d] of DSR_STAT_D) {
    const v = u8(buf, m + d);
    if (v == null || v < 0 || v > 99) return false;
  }
  return true;
}
function dsrFindAnchor(buf) {
  let o = 0;
  for (;;) {
    const m = indexOf(buf, DSR_MAGIC, o);
    if (m === -1) return null;
    if (statBlockValid(buf, m)) return m;
    o = m + 1;
  }
}
function ptdeFindAnchor(buf) {
  const n = buf.length - 1;
  for (let o = 0; o < n; o++) {
    const name = readUtf16(buf, o, 13);
    if (name.length >= 2 && isValidName(name)) {
      const m = o - DSR_NAME_D;
      if (statBlockValid(buf, m)) return m;
    }
  }
  return null;
}
function ds1Inventory(buf, itemDb) {
  const buckets = {}; let unknown = 0;
  const push = (c, v) => (buckets[c] || (buckets[c] = [])).push(v);
  const start = indexOf(buf, DS1_INV_ANCHOR, DS1_INV_START);
  if (start === -1) return { buckets, unknown };
  let end = indexOf(buf, DS1_INV_END, start);
  if (end === -1) end = buf.length;
  let o = start;
  while (o + 28 <= end) {
    const stype = u32(buf, o + 4), iid = u32(buf, o + 8), qty = u32(buf, o + 12);
    o += 28;
    if (!iid) continue;
    const cat = stype != null ? DS1_CAT[stype & 0xF0000000] : null;
    const name = cat ? ds1Resolve(itemDb, cat, iid) : null;
    if (name == null) { unknown++; continue; }
    push(cat, [name, qty]);
  }
  return { buckets, unknown };
}
function ds1Character(buf, itemDb, m, game, ng, bossSouls) {
  const stats = {};
  for (const [k, d] of DSR_STAT_D) stats[k] = u8(buf, m + d);
  const { buckets, unknown } = ds1Inventory(buf, itemDb);
  const inv = {};
  for (const c in buckets) inv[c] = mergeQty(buckets[c]);
  const name = readUtf16(buf, m + DSR_NAME_D, 13);
  const goods = inv["goods"] || [];
  return {
    tier: "full", game, name: isValidName(name) ? name : "(unnamed slot)",
    klass: DS1_CLASS[u8(buf, m + DSR_CLASS_D)] ?? null,
    level: u16(buf, m + DSR_LEVEL_D), stats,
    souls: u32(buf, m + DSR_SOULS_D), soul_memory: null,
    humanity: u8(buf, m + DSR_HUM_D), stamina: u32(buf, m + DSR_STAM_D),
    hp: u32(buf, m + DSR_HP_D), ng_plus: ng,
    boss_souls: findBossSouls(goods), key_items: findKeyGoods(goods),
    inv, unknown_count: unknown,
  };
}
function dsrParse(buf, itemDb) {
  const m = dsrFindAnchor(buf);
  if (m === null) return null;
  return ds1Character(buf, itemDb, m, "dsr", u8(buf, m + DSR_NG_D) || 0);
}
function ptdeParse(buf, itemDb) {
  const m = ptdeFindAnchor(buf);
  if (m === null) return null;
  return ds1Character(buf, itemDb, m, "ptde", null);
}

// ── DS3 ─────────────────────────────────────────────────────────────────
const DS3_RECORD = 16, DS3_QTY_OFF = 4;
const DS3_STAT_D = [["Vigor", 0], ["Attunement", 4], ["Endurance", 8], ["Vitality", 12],
  ["Strength", 16], ["Dexterity", 20], ["Intelligence", 24], ["Faith", 28], ["Luck", 40]];
const DS3_HP_D = -40, DS3_STAM_D = -12, DS3_LEVEL_D = 44, DS3_SOULS_D = 48, DS3_LEVEL_BASE = 89;
const SCAN_MIN_RUN = 3;

function scanInventory(buf, iddb) {
  const positions = [];
  for (let o = 0; o < buf.length - 8; o++) if (iddb.has(u32(buf, o))) positions.push(o);
  const buckets = {}; const seen = new Set();
  const n = positions.length; let i = 0;
  while (i < n) {
    let j = i;
    while (j + 1 < n && positions[j + 1] - positions[j] === DS3_RECORD) j++;
    if (j - i + 1 >= SCAN_MIN_RUN) {
      for (let k = i; k <= j; k++) {
        const o = positions[k];
        if (seen.has(o)) continue;
        seen.add(o);
        const iid = u32(buf, o), qty = u32(buf, o + DS3_QTY_OFF) || 0;
        if (qty >= 1 && qty <= 9999) {
          const [name, cat] = iddb.get(iid);
          const b = buckets[cat] || (buckets[cat] = new Map());
          b.set(name, (b.get(name) || 0) + qty);
        }
      }
    }
    i = j + 1;
  }
  const inv = {};
  for (const c in buckets) inv[c] = [...buckets[c].entries()];
  return inv;
}
function ds3FindStats(buf) {
  const dists = DS3_STAT_D.map(([, d]) => d);
  const end = buf.length - DS3_SOULS_D - 4;
  for (let v = 0; v < end; v += 4) {
    const first = u32(buf, v);
    if (first != null && first >= 1 && first <= 99) {
      const vals = dists.map((d) => u32(buf, v + d));
      const lvl = u32(buf, v + DS3_LEVEL_D);
      if (vals.every((x) => x != null && x >= 1 && x <= 99) && lvl != null && lvl >= 1 && lvl <= 802 &&
          vals.reduce((a, b) => a + b, 0) - DS3_LEVEL_BASE === lvl) return v;
    }
  }
  return null;
}
function ds3Parse(buf, iddb, name) {
  const inv = scanInventory(buf, iddb);
  if (Object.keys(inv).length === 0) return null;
  const goods = inv["goods"] || [];
  const v = ds3FindStats(buf);
  const stats = {};
  if (v != null) for (const [k, d] of DS3_STAT_D) stats[k] = u32(buf, v + d);
  const has = v != null;
  return {
    tier: has ? "full" : "inventory", game: "ds3",
    name: name && isValidName(name) ? name : "(unnamed slot)",
    klass: null, stats, soul_memory: null, humanity: null, ng_plus: null,
    level: has ? u32(buf, v + DS3_LEVEL_D) : null,
    souls: has ? u32(buf, v + DS3_SOULS_D) : null,
    stamina: has ? u32(buf, v + DS3_STAM_D) : null,
    hp: has ? u32(buf, v + DS3_HP_D) : null,
    boss_souls: findBossSouls(goods), key_items: findKeyGoods(goods),
    inv, unknown_count: 0,
  };
}
const ROSTER_PARAMS_DS3 = { menu: 10, occ: 4244, desc: 4254, stride: 554, namelen: 16 };
function parseRosterDs3(menu) {
  const p = ROSTER_PARAMS_DS3, roster = new Map();
  for (let i = 0; i < 10; i++) {
    if (!u8(menu, p.occ + i)) continue;
    const name = readUtf16(menu, p.desc + p.stride * i, p.namelen);
    roster.set(i, name ? name : "(unnamed)");
  }
  return roster;
}

// ── Elden Ring ────────────────────────────────────────────────────────────
const ER_GAITEM_START = 0x20, ER_GAITEM_COUNT = 0x1400;
const ER_MENU_LEN_OFF = 352, ER_MENU_DATA_OFF = 356, ER_SLOT_COUNT = 10, ER_PROFILE_STRIDE = 588;
const ER_PROFILE_NAME_LEN = 16, ER_PROFILE_LEVEL_OFF = 34;
const ER_STAT_D = [["Vigor", 0], ["Mind", 4], ["Endurance", 8], ["Strength", 12],
  ["Dexterity", 16], ["Intelligence", 20], ["Faith", 24], ["Arcane", 28]];
const ER_HP_D = -40, ER_STAM_D = -12, ER_LEVEL_D = 44, ER_RUNES_D = 48, ER_LEVEL_BASE = 79;
const ER_CAT = { 0x0: "weapons", 0x1: "armors", 0x2: "talismans", 0x4: "goods", 0x8: "ashes" };
const ER_WEAPON_BASE_STEP = 10000;

function erRoster(menu) {
  const length = u32(menu, ER_MENU_LEN_OFF);
  if (length == null) return [];
  const activeBase = ER_MENU_DATA_OFF + length, pbase = activeBase + ER_SLOT_COUNT;
  const out = [];
  for (let i = 0; i < ER_SLOT_COUNT; i++) {
    const active = !!u8(menu, activeBase + i);
    const base = pbase + i * ER_PROFILE_STRIDE;
    out.push([active, readUtf16(menu, base, ER_PROFILE_NAME_LEN), u32(menu, base + ER_PROFILE_LEVEL_OFF)]);
  }
  return out;
}
function* erGaitems(buf) {
  let o = ER_GAITEM_START;
  for (let n = 0; n < ER_GAITEM_COUNT; n++) {
    if (o + 8 > buf.length) return;
    const iid = u32(buf, o + 4);
    o += 8;
    if (iid) {
      const cat = iid & 0xF0000000;
      if (cat === 0x00000000) o += 13;
      else if (cat === 0x10000000) o += 8;
      yield iid;
    }
  }
}
function erResolve(iid, db) {
  const cat = ER_CAT[(iid >>> 28) & 0xF];
  if (cat === undefined) return [null, null];
  const table = db[cat] || new Map();
  let name = table.get(iid);
  if (name == null && cat === "weapons") name = table.get(iid - (iid % ER_WEAPON_BASE_STEP));
  return [name ?? null, cat];
}
function erFindStats(buf) {
  const dists = ER_STAT_D.map(([, d]) => d);
  const end = buf.length - ER_RUNES_D - 4;
  for (let v = 0; v < end; v += 4) {
    const first = u32(buf, v);
    if (first != null && first >= 1 && first <= 99) {
      const vals = dists.map((d) => u32(buf, v + d));
      const lvl = u32(buf, v + ER_LEVEL_D);
      if (vals.every((x) => x != null && x >= 1 && x <= 99) && lvl != null && lvl >= 1 && lvl <= 713 &&
          vals.reduce((a, b) => a + b, 0) - ER_LEVEL_BASE === lvl) return v;
    }
  }
  return null;
}
function erParse(buf, iddb, name, level) {
  const buckets = {}; let unknown = 0;
  for (const iid of erGaitems(buf)) {
    const [nm, cat] = erResolve(iid, iddb);
    if (nm) (buckets[cat] || (buckets[cat] = new Set())).add(nm);
    else if (cat) unknown++;
  }
  if (!Object.values(buckets).some((s) => s.size)) return null;
  const inv = {};
  for (const c in buckets) inv[c] = [...buckets[c]].sort().map((n) => [n, null]);
  const remembrances = [];
  for (const c in buckets) for (const n of [...buckets[c]].sort()) if (n.includes("Remembrance")) remembrances.push([n, null]);
  const v = erFindStats(buf);
  const stats = {};
  if (v != null) for (const [k, d] of ER_STAT_D) stats[k] = u32(buf, v + d);
  const has = v != null;
  return {
    tier: has ? "full" : "inventory", game: "er",
    name: name && isValidName(name) ? name : "(unnamed slot)",
    klass: null, stats, soul_memory: null, humanity: null, ng_plus: null,
    level: has ? u32(buf, v + ER_LEVEL_D) : level,
    souls: has ? u32(buf, v + ER_RUNES_D) : null,
    stamina: has ? u32(buf, v + ER_STAM_D) : null,
    hp: has ? u32(buf, v + ER_HP_D) : null,
    boss_souls: remembrances, key_items: [], inv, unknown_count: unknown,
  };
}

// ── Game table + driver ──────────────────────────────────────────────────
export const GAMES = {
  ds2sotfs: { title: "Dark Souls II: Scholar of the First Sin", slots: [1, 11] },
  dsr: { title: "Dark Souls Remastered", slots: [0, 10] },
  ptde: { title: "Dark Souls: Prepare to Die Edition", slots: [0, 10] },
  ds3: { title: "Dark Souls III", slots: [0, 10] },
  er: { title: "Elden Ring", slots: [0, 10] },
};

/**
 * Parse a whole save into characters. `dbs` is the preloaded database bundle
 * (see db.js). Returns {game, title, characters:[{slot, ch}]}. Throws ParseError
 * on an unsupported/short save (message is user-facing).
 */
export function parseSave(data, dbs) {
  data = data instanceof Uint8Array ? data : new Uint8Array(data);
  const entries = parseBnd4(data);
  const game = detectGame(data, entries);
  const meta = GAMES[game];
  const characters = [];
  const label = (i) => i - meta.slots[0] + 1;

  if (game === "er") {
    const menu = blobOf(data, entries[10]);
    const roster = erRoster(menu);
    for (let i = meta.slots[0]; i < meta.slots[1]; i++) {
      if (i >= entries.length) continue;
      const [active, name, level] = i < roster.length ? roster[i] : [true, null, null];
      if (!active) continue;
      const slot = decryptNone(blobOf(data, entries[i]));
      const ch = erParse(slot, dbs.er.items, name, level);
      if (ch) { attachDefeatedBosses(ch, dbs); characters.push({ slot: label(i), ch }); }
    }
  } else if (game === "ds3") {
    const menu = decryptIvPrefixed(blobOf(data, entries[10]), DS3_KEY);
    const names = menu ? parseRosterDs3(menu) : new Map();
    for (let i = meta.slots[0]; i < meta.slots[1]; i++) {
      if (i >= entries.length) continue;
      const slot = decryptIvPrefixed(blobOf(data, entries[i]), DS3_KEY);
      if (slot === null) continue;
      const ch = ds3Parse(slot, dbs.ds3.items, names.get(i));
      if (ch) { attachDefeatedBosses(ch, dbs); characters.push({ slot: label(i), ch }); }
    }
  } else {
    // DS2 (full, encrypted + augment + active-filter) and DS1 (dsr/ptde).
    const decrypt = game === "ds2sotfs" ? decryptDs2 : game === "dsr" ? (b) => decryptIvPrefixed(b, DSR_KEY) : decryptNone;
    const parse = game === "ds2sotfs" ? ds2Parse : game === "dsr" ? dsrParse : ptdeParse;
    const itemDb = game === "ds2sotfs" ? dbs.ds2.items : dbs.ds1.items;
    const active = game === "ds2sotfs" ? ds2ActiveSlots(data, entries, meta.slots) : null;
    for (let i = meta.slots[0]; i < meta.slots[1]; i++) {
      if (i >= entries.length) continue;
      if (active !== null && !active.has(i)) continue;
      const slot = decrypt(blobOf(data, entries[i]));
      if (slot === null) continue;
      const ch = parse(slot, itemDb);
      if (ch) {
        if (game === "ds2sotfs") ds2Augment(ch, data, entries, i, dbs);
        attachDefeatedBosses(ch, dbs);
        characters.push({ slot: label(i), ch });
      }
    }
  }
  return { game, title: meta.title, characters };
}

export { ParseError };
