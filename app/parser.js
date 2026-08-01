// Port of sl2_to_md.py's parsing pipeline to the browser: parse_bnd4 → detect_game
// → per-game parse/augment → unified `ch` objects. Byte-for-byte faithful to the
// Python tool (gated by scratch/harness.mjs, which diffs this against the Python
// reference dumps). Render lives in render.js; this module produces data only.

import { u8, u16, u32, u64, readUtf16, isValidName, indexOf } from "./reader.js";
import { aesCbcDecrypt, hexToBytes } from "./aes.js";

const DS2_KEY = hexToBytes("599F9B699640A55236EE2D70835EC744");
// Vanilla DS2 (the DX9 original, DARKSII0000.sl2) uses a different key from Scholar's
// but the identical save layout. From TKGP's SoulsFormats SFUtil.GetDS2SaveKey().
const DS2_VANILLA_KEY = hexToBytes("B7FD463E4A9C1102DF1739E5F3B2A50F");
const DS2_GAMES = new Set(["ds2sotfs", "ds2vanilla"]);
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
function decryptDs2(blob, key = DS2_KEY) {
  const pt = aesCbc(key, blob.subarray(16, 32), blob.subarray(32));
  const dlen = u32(pt, 0);
  // The length must fit the block. A wrong key decrypts to noise whose "length" is a
  // random uint32, so rejecting it here doubles as a key check: a mismatched key
  // yields null (feature off) rather than noise the world-block readers would treat
  // as set event flags. See sl2_to_md.py decrypt_ds2.
  if (dlen == null || dlen <= 0 || dlen > pt.length - 4) return null;
  return pt.subarray(4, 4 + dlen);
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
    // Both DS2 releases share the signature, so they are told apart by which key
    // decrypts: the length prefix at plaintext +0 must fit the block.
    const blob = blobOf(data, entries[1]);
    for (const [key, id] of [[DS2_KEY, "ds2sotfs"], [DS2_VANILLA_KEY, "ds2vanilla"]]) {
      const pt = aesCbc(key, blob.subarray(16, 32), blob.subarray(32));
      const dlen = u32(pt, 0);
      if (dlen != null && dlen > 0 && dlen <= pt.length - 4) return id;
    }
    throw new ParseError("Dark Souls II save found, but neither the Scholar nor the vanilla key decrypts it.");
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
const DS1_PROGRESSION = new Set(["Lordvessel", "Peculiar Doll", "Broken Pendant", "Rite of Kindling",
  "Crest of Artorias"]);
const BOSS_SOUL_EXTRA = new Set(["Core of an Iron Golem", "Guardian Soul"]);

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

// Bosses that can't be skipped to finish the game, so reaching NG+ proves them dead
// (tag `clear`). Mirrors Python MANDATORY_BOSSES — endgame-safe; DS2 seeds its own
// Nashandra in ds2InferBosses because its mid-game is skippable.
const MANDATORY_BOSSES = {
  dsr: ["Bell Gargoyles", "Chaos Witch Quelaag", "Iron Golem",
    "Dragon Slayer Ornstein", "Executioner Smough", "Great Grey Wolf Sif",
    "The Four Kings", "Seath the Scaleless", "Gravelord Nito", "Bed of Chaos",
    "Gwyn, Lord of Cinder"],
};
MANDATORY_BOSSES.ptde = MANDATORY_BOSSES.dsr;
MANDATORY_BOSSES.ds3 = ["Iudex Gundyr", "Vordt of the Boreal Valley",
  "Dancer of the Boreal Valley", "Abyss Watchers", "Pontiff Sulyvahn",
  "Aldrich, Devourer of Gods", "Yhorm the Giant", "Dragonslayer Armour",
  "Lothric, Younger Prince", "Soul of Cinder"];

function attachDefeatedBosses(ch, dbs) {
  const family = BOSS_SOUL_DB_DIR[ch.game];
  if (!family || ch.bosses) return;
  const soulDb = dbs[family].bossSouls || {};
  const bosses = new Map();
  const add = (b, e) => (bosses.get(b) || bosses.set(b, new Set()).get(b)).add(e);
  for (const [name] of ch.boss_souls || []) {
    const boss = soulDb[name];
    if (boss) add(boss, "soul");
  }
  if ((ch.ng_plus || 0) > 0) for (const boss of MANDATORY_BOSSES[ch.game] || []) add(boss, "clear");
  const prereq = BOSS_PREREQ[ch.game] || {};
  for (const boss of [...bosses.keys()]) {
    for (const pre of prereq[boss] || []) {
      (bosses.get(pre) || bosses.set(pre, new Set()).get(pre)).add("gate");
    }
  }
  if (bosses.size) ch.bosses = mapToSortedEvidence(bosses, false);
}

// Every boss / covenant the tool can name for a game — the denominators behind
// "Bosses Defeated (8 of 26)" and "Covenants Found (4 of 9)". Assembled from the
// game's own tables, so a boss no table knows cannot inflate the denominator.
// See boss_roster / covenant_roster in sl2_to_md.py.
function bossRoster(game, dbs) {
  if (DS2_GAMES.has(game)) {
    return new Set([...dbs.ds2.bossFlags.values(), ...Object.values(dbs.ds2.bossSouls || {})]);
  }
  const family = BOSS_SOUL_DB_DIR[game];
  const names = new Set(family ? Object.values(dbs[family].bossSouls || {}) : []);
  for (const b of MANDATORY_BOSSES[game] || []) names.add(b);
  if (game === "ds3") {
    for (const b of Object.keys(dbs.ds3.bossFlags || {})) names.add(b);
    for (const b of Object.keys(dbs.ds3.bossVictory || {})) names.add(b);
  }
  if (game === "dsr" || game === "ptde") {
    for (const b of Object.keys(dbs.ds1.bossFlags || {})) names.add(b);
  }
  return names;
}
function covenantRoster(game, dbs) {
  if (DS2_GAMES.has(game)) return new Set(Object.values(DS2_COVENANT));
  if (game === "ds3") return new Set([...DS3_COVENANT.values(), ...Object.keys(dbs.ds3.covenants || {})]);
  return new Set();
}

// The four Lords of Cinder (boss name → throne name) and the item that sits in the
// inventory between the kill and the offering. A closed set, so "N of 4" is a real
// denominator. See DS3_LORDS in sl2_to_md.py.
const DS3_LORDS = [["Abyss Watchers", "Abyss Watchers"], ["Yhorm the Giant", "Yhorm the Giant"],
  ["Aldrich, Devourer of Gods", "Aldrich"], ["Lothric, Younger Prince", "Twin Princes"]];
const DS3_CINDER_ITEM = "Cinders of a Lord";

// Denominators + what is still missing. The Lords count is arithmetic on two reads
// that are already verified (lords defeated − cinders still held), not a new offset,
// and is skipped on NG+ where the thrones reset but the defeat flags do not.
function attachProgressTotals(ch, dbs) {
  const game = ch.game;
  const roster = bossRoster(game, dbs);
  if (roster.size && ch.bosses && Object.keys(ch.bosses).length) {
    ch.boss_total = new Set([...roster, ...Object.keys(ch.bosses)]).size;
    ch.bosses_missing = [...roster].filter((n) => !(n in ch.bosses)).sort();
  }
  const covs = covenantRoster(game, dbs);
  if (covs.size && ch.covenants && Object.keys(ch.covenants).length) {
    ch.covenant_total = new Set([...covs, ...Object.keys(ch.covenants)]).size;
    ch.covenants_missing = [...covs].filter((n) => !(n in ch.covenants)).sort();
  }
  if (game !== "ds3") return;
  const chBosses = ch.bosses || {};
  // Which of the missing bosses you could walk to right now: every hard predecessor
  // dead, and a bonfire lit in its gate area (so a DLC boss cannot be "available"
  // before you enter the DLC). Route structure only — nothing read from the save.
  const reached = new Set((ch.bonfire_areas || []).filter(([, c]) => c).map(([a]) => a));
  if (reached.size) {
    const avail = Object.entries(dbs.ds3.bossRoute || {})
      .filter(([b, [area, after]]) => !(b in chBosses) && reached.has(area)
        && after.every((p) => p in chBosses))
      .map(([b]) => b);
    if (avail.length) ch.bosses_available = avail;
  }
  const dead = DS3_LORDS.filter(([boss]) => chBosses[boss]).map(([, lord]) => lord);
  let held = 0;
  for (const [n, q] of ch.key_items || []) if (n === DS3_CINDER_ITEM) held += q;
  const named = ch.cinders || [];
  if (dead.length || named.length) {
    ch.lords = { total: DS3_LORDS.length, named, dead: dead.length, held,
      placed: (ch.ng_plus || 0) === 0 ? Math.max(dead.length - held, named.length) : null };
  }
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
// Per-covenant discovered flag (+2) and rank (+12), dense runs in covenant-id order
// past the current-covenant byte. See sl2_to_md.py DS2_COV_DISC_D / DS2_COV_RANK_D.
const DS2_COV_DISC_D = 2, DS2_COV_RANK_D = 12, DS2_COV_MAX_RANK = 3;
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
// Every DS2 covenant discovered, with rank. Both runs are validated as a whole
// (flag 0/1, rank 0..3, no rank without discovery) and the feature turns itself off
// on any violation rather than printing a wrong rank. See sl2_to_md.py ds2_covenants.
function ds2Covenants(buf) {
  const out = {};
  let any = false;
  for (const cid of Object.keys(DS2_COVENANT).map(Number).sort((a, b) => a - b)) {
    const disc = u8(buf, DS2_COVENANT_OFF + DS2_COV_DISC_D + cid - 1);
    const rank = u8(buf, DS2_COVENANT_OFF + DS2_COV_RANK_D + cid - 1);
    if (disc == null || rank == null || disc > 1 || rank > DS2_COV_MAX_RANK) return null;
    if (rank && !disc) return null;
    if (disc) { out[DS2_COVENANT[cid]] = [rank ? `rank ${rank} of ${DS2_COV_MAX_RANK}` : "discovered"]; any = true; }
  }
  return any ? out : null;
}
function ds2Parse(buf, itemDb, game = "ds2sotfs") {
  if (ds2Name(buf) === null) return null;
  const stats = {};
  for (const [k, o] of DS2_STAT_OFF) stats[k] = u16(buf, o) || 0;
  const level = stats["Level"]; delete stats["Level"];
  const { buckets, unknown } = ds2Inventory(buf, itemDb);
  const inv = {};
  for (const c in buckets) inv[c] = mergeQty(buckets[c]);
  const keyItems = inv["keys"] || []; delete inv["keys"];
  return {
    tier: "full", game, name: ds2Name(buf),
    klass: DS2_CLASS[u8(buf, DS2_CLASS_OFF)] ?? null,
    covenant: DS2_COVENANT[u8(buf, DS2_COVENANT_OFF)] ?? null,
    covenants: ds2Covenants(buf),
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
// Item ⇒ boss it sits behind. Each has one documented source, past that boss's fog gate.
// The two DLC gank bosses drop no soul, so this is the only route to them.
const DS2_ITEM_GATE = {
  "King's Ring": ["Velstadt, the Royal Aegis"],
  "Pharros Mask": ["Blue Smelter Demon"],
  "Flower Skirt": ["Graverobber, Varg, and Cerah"],
};
// Strip a trailing " +N" so an upgraded piece still matches the plain db name.
const ds2BaseName = (n) => n.replace(/ \+\d+$/, "");
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
  for (const c in ch.inv) for (const [n] of ch.inv[c]) held.add(ds2BaseName(n));
  for (const [n] of ch.key_items || []) held.add(n);
  for (const item in DS2_ITEM_GATE) if (held.has(item)) for (const boss of DS2_ITEM_GATE[item]) add(boss, "gate");
  if ((ch.ng_plus || 0) > 0) add("Nashandra", "clear"); // NG+ ⇒ final boss dead; closure fills the endgame chain
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
    if (u8(world, flagBase + idx)) visited.push([bid, bfDb.get(bid) ?? `(bonfire 0x${bid.toString(16).padStart(4, "0")})`]);
  });
  return visited;
}
// Group discovered bonfires by area, in the (area, count, names) shape DS1 and DS3
// already emit, so all three render through one section. See sl2_to_md.py
// ds2_bonfire_areas.
function ds2BonfireAreas(visited, areaDb, bfDb) {
  if (!visited || !visited.length || !areaDb || areaDb.size === 0) return null;
  const seen = new Set(visited.map(([bid]) => bid));
  const areas = new Map();
  for (const [bid] of visited) {
    const area = areaDb.get(bid);
    if (area != null && !areas.has(area)) areas.set(area, [[], []]);
  }
  // Walk the whole area table, not just what was visited, so an area the character
  // has not reached still prints as 0/N rather than vanishing. Sorted by id: the
  // json is ascending, but JS reorders an object's digit-only keys ("3944") ahead of
  // the rest, so a plain walk of the Map would not match the Python order.
  for (const [bid, area] of [...areaDb].sort((a, b) => a[0] - b[0])) {
    if (!areas.has(area)) areas.set(area, [[], []]);
    const name = bfDb.get(bid);
    if (name == null) continue;
    areas.get(area)[seen.has(bid) ? 0 : 1].push(name);
  }
  const out = [...areas].map(([a, [got, miss]]) => [a, got.length, got, got.length + miss.length, miss]);
  return out.some(([, c]) => c) ? out : null;
}
function ds2Augment(ch, data, entries, i, dbs, dec = decryptDs2) {
  // Play time lives in the header title record (one per slot), not the character
  // block. Title index for block entry i is i - slots.start, and DS2 starts at 1.
  if (entries.length) {
    const hdr = dec(blobOf(data, entries[0]));
    if (hdr !== null) {
      const base = DS2_TITLE_NAME_OFF + DS2_TITLE_STRIDE * (i - 1);
      ch.play_time = u32(hdr, base + DS2_TITLE_PLAYTIME_OFF);
    }
  }
  const w = i + DS2_WORLD_ENTRY_DELTA;
  if (w >= entries.length) return;
  const world = dec(blobOf(data, entries[w]));
  const visited = ds2VisitedBonfires(world, dbs.ds2.bonfires);
  // The flat name list stays: DS2_BOSS_GATE is keyed by bonfire name, so the boss
  // inference below reads it. The grouped view is what gets rendered.
  ch.bonfires = visited ? visited.map(([, name]) => name) : visited;
  const areas = ds2BonfireAreas(visited, dbs.ds2.bonfireAreas, dbs.ds2.bonfires);
  if (areas) ch.bonfire_areas = areas;
  ch.bosses = ds2InferBosses(world, ch, dbs);
}
function ds2ActiveSlots(data, entries, slots, dec = decryptDs2) {
  if (!entries.length) return null;
  const hdr = dec(blobOf(data, entries[0]));
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
// DS1 gender: two independent sources agree (alfizari's DSR editor at magic-237, and
// tarvitz/dsfp's boolean `male` 34 bytes past the name, which is the same byte). Both
// call 1 Male, so the polarity is inverted against DS2. See sl2_to_md.py DSR_GENDER_D.
const DSR_GENDER_D = -237;
const DS1_GENDER = { 0: "Female", 1: "Male" };
// Deaths sit in a fixed struct near the event-flag region, not in the moving character
// block, so the offset is slot-absolute per release; DSR shifts it by the same 448
// bytes its flag region moves. Guarded by the 0xFFFFFFFF sentinel that follows the
// counter in both releases. See sl2_to_md.py DS1_DEATHS_OFF.
const DS1_DEATHS_OFF = { ptde: 0x1F118, dsr: 0x1F2D8 };
const DS1_DEATHS_SENTINEL = 0xFFFFFFFF, DS1_DEATHS_SENTINEL_D = 4;
// DS1's load-screen roster (BND4 entry 10): name at +0, soul level at +36, play time
// as a uint32 of SECONDS at +40. Located by the character's own name and accepted only
// when the level beside it matches. See sl2_to_md.py DS1_MENU_ENTRY.
const DS1_MENU_ENTRY = 10, DS1_MENU_LEVEL_D = 36, DS1_MENU_PLAYTIME_D = 40;

function ds1Deaths(buf, game) {
  const off = DS1_DEATHS_OFF[game];
  if (off == null) return null;
  if (u32(buf, off + DS1_DEATHS_SENTINEL_D) !== DS1_DEATHS_SENTINEL) return null;
  return u32(buf, off);
}
function ds1AttachPlaytime(ch, menu) {
  if (!menu || !ch.name || ch.level == null) return;
  const want = new Uint8Array(ch.name.length * 2);
  for (let i = 0; i < ch.name.length; i++) {
    const c = ch.name.charCodeAt(i);
    want[i * 2] = c & 0xFF; want[i * 2 + 1] = (c >> 8) & 0xFF;
  }
  let pos = indexOf(menu, want, 0);
  while (pos !== -1) {
    if (u32(menu, pos + DS1_MENU_LEVEL_D) === ch.level) {
      ch.play_time = u32(menu, pos + DS1_MENU_PLAYTIME_D);
      return;
    }
    pos = indexOf(menu, want, pos + 2);
  }
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
    gender: DS1_GENDER[u8(buf, m + DSR_GENDER_D)] ?? null,
    deaths: ds1Deaths(buf, game),
    level: u16(buf, m + DSR_LEVEL_D), stats,
    souls: u32(buf, m + DSR_SOULS_D), soul_memory: null,
    humanity: u8(buf, m + DSR_HUM_D), stamina: u32(buf, m + DSR_STAM_D),
    hp: u32(buf, m + DSR_HP_D), ng_plus: ng,
    boss_souls: findBossSouls(goods), key_items: findKeyGoods(goods),
    inv, unknown_count: unknown,
  };
}
// DS1 bonfires. Unlike DS2/DS3 these are NOT event flags: DS1 keeps a NetBonfireDb
// list of 20-byte {id, state} records. The list moves between saves, so it is located
// by content — the longest run of consecutive records with a real id, a valid state and
// no repeat. See sl2_to_md.py ds1_bonfires.
const DS1_BONFIRE_REC = 20, DS1_BONFIRE_STATE_D = 4, DS1_BONFIRE_MIN_RUN = 5;
const DS1_BONFIRE_STATE = { 0: "discovered", 10: "lit", 20: "kindled +1", 30: "kindled +2", 40: "kindled +3" };
function ds1Bonfires(buf, db) {
  if (!db || !Object.keys(db).length) return null;
  let best = [];
  let o = 0;
  while (o + DS1_BONFIRE_REC <= buf.length) {
    if (db[u32(buf, o)]) {
      const run = [];
      const seen = new Set();
      let p = o;
      while (p + DS1_BONFIRE_REC <= buf.length) {
        const bid = u32(buf, p), state = u32(buf, p + DS1_BONFIRE_STATE_D);
        if (!db[bid] || DS1_BONFIRE_STATE[state] === undefined || seen.has(bid)) break;
        seen.add(bid); run.push([bid, state]); p += DS1_BONFIRE_REC;
      }
      if (run.length > best.length) best = run;
      o = Math.max(p, o + 1);
    } else o += 1;
  }
  if (best.length < DS1_BONFIRE_MIN_RUN) return null;
  const found = new Map(best);
  const areas = new Map();
  for (const [bid, [name, area]] of Object.entries(db).map(([k, v]) => [Number(k), v])) {
    if (!areas.has(area)) areas.set(area, [[], []]);
    const [got, miss] = areas.get(area);
    if (found.has(bid)) got.push(`${name} (${DS1_BONFIRE_STATE[found.get(bid)]})`);
    else miss.push(name);
  }
  return [...areas].map(([a, [got, miss]]) => [a, got.length, got, got.length + miss.length, miss]);
}
// DS1 boss-defeat flags. The published DS1 flag addressing gives offsets inside the
// event-flag region; the region's own start is not published and was searched for —
// in the DSR mule exactly one offset in the whole slot has all 12 boss flags and both
// bells set, and both PtDE saves agree on their own value. See sl2_to_md.py
// DS1_FLAG_BASE. The density gate is the guard: a real flag region is ~0.6% set bits
// against ~32% for ordinary save data, so a moved region turns the feature off.
const DS1_FLAG_BASE = { dsr: 127721, ptde: 127273 };
const DS1_FLAG_MAX_DENSITY = 0.05, DS1_FLAG_SPAN = 23156;
function ds1AttachFlags(ch, buf, table, game) {
  const base = DS1_FLAG_BASE[game];
  if (base == null || !table || !Object.keys(table).length) return;
  if (base + DS1_FLAG_SPAN > buf.length) return;
  let bits = 0;
  for (let i = base; i < base + DS1_FLAG_SPAN; i++) {
    let x = buf[i];
    while (x) { bits += x & 1; x >>= 1; }
  }
  if (bits > DS1_FLAG_SPAN * 8 * DS1_FLAG_MAX_DENSITY) return;
  const bosses = new Map();
  for (const [b, s] of Object.entries(ch.bosses || {})) bosses.set(b, new Set(s));
  for (const [name, [off, mask]] of Object.entries(table)) {
    const v = u32(buf, base + off);
    if (v != null && (v & mask) >>> 0) {
      if (!bosses.has(name)) bosses.set(name, new Set());
      bosses.get(name).add("flag");
    }
  }
  if (bosses.size) ch.bosses = mapToSortedEvidence(bosses, false);
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
// Storage order != display order: Vitality lives alone at +40 after a two-field
// gap; Str/Dex/Int/Fth/Luck are the contiguous +12..+28. See sl2_to_md.py.
const DS3_STAT_D = [["Vigor", 0], ["Attunement", 4], ["Endurance", 8], ["Vitality", 40],
  ["Strength", 12], ["Dexterity", 16], ["Intelligence", 20], ["Faith", 24], ["Luck", 28]];
const DS3_HP_D = -40, DS3_FP_D = -28, DS3_STAM_D = -12, DS3_LEVEL_D = 44, DS3_SOULS_D = 48, DS3_LEVEL_BASE = 89;
// Embered flag: uint8 at +188 in the stat-mirror struct behind the anchor; 1 = embered
// (Max HP carries the +30% bonus), 0 = hollow. See sl2_to_md.py DS3_EMBER_D for the calibration.
const DS3_EMBER_D = 188;
// Covenant: uint32 equip HANDLE at +3944 from the anchor (DS3 wears the covenant like
// an accessory), covenant item id = low 28 bits. See sl2_to_md.py DS3_COVENANT_D.
const DS3_COVENANT_D = 3944;
const DS3_COVENANT = new Map([[10000, "Blade of the Darkmoon"], [10020, "Watchdogs of Farron"],
  [10030, "Aldrich Faithful"], [10040, "Warrior of Sunlight"], [10050, "Mound-makers"],
  [10060, "Way of Blue"], [10070, "Blue Sentinels"], [10080, "Rosaria's Fingers"],
  [10090, "Spears of the Church"]]);
const SCAN_MIN_RUN = 3;
// Bridge holes left by untabled items: two known records can sit 32/48 bytes apart
// on the 16-byte grid. See sl2_to_md.py DS3_MAX_RUN_GAP.
const DS3_MAX_RUN_GAP = 48;

function scanInventory(buf, iddb) {
  const positions = [];
  for (let o = 0; o < buf.length - 8; o++) if (iddb.has(u32(buf, o))) positions.push(o);
  const buckets = {}; const seen = new Set();
  const n = positions.length; let i = 0;
  while (i < n) {
    let j = i;
    while (j + 1 < n) {
      const d = positions[j + 1] - positions[j];
      if (d % DS3_RECORD === 0 && d <= DS3_MAX_RUN_GAP) j++;
      else break;
    }
    if (j - i + 1 >= SCAN_MIN_RUN) {
      // Walk the run's whole record grid, not just the table hits: the holes are
      // real records too, and a reinforced weapon always sits in one (the held
      // inventory stores the exact base+infusion*100+level id, so only a +0 weapon
      // is a direct hit). Runs are still built from direct hits, so this only adds.
      for (let o = positions[i]; o <= positions[j]; o += DS3_RECORD) {
        if (seen.has(o)) continue;
        seen.add(o);
        const iid = u32(buf, o), qty = u32(buf, o + DS3_QTY_OFF) || 0;
        if (!(qty >= 1 && qty <= 9999)) continue;
        let entry = iddb.get(iid);
        if (entry === undefined) {
          const reinf = ds3ResolveWeapon(iddb, iid);
          const estus = reinf ? null : ds3ResolveEstus(iid);
          if (reinf == null && estus == null) continue;
          entry = reinf ? [reinf, "weapons"] : [estus, "consumables"];
        }
        const [name, cat] = entry;
        const b = buckets[cat] || (buckets[cat] = new Map());
        b.set(name, (b.get(name) || 0) + qty);
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
  // Boss souls stay in the inventory (their own category, as in DS2) but are also
  // handed to the kill inference; key items follow DS2 and move out of the
  // inventory entirely, since the Key Items section already prints them.
  const goods = (inv["bosssouls"] || []).concat(inv["goods"] || []);
  const keyItems = inv["keys"] || [];
  delete inv["keys"];
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
    fp: has ? u32(buf, v + DS3_FP_D) : null,
    embered: ds3Embered(buf, v),
    covenant: ds3Covenant(buf, v),
    equipped_weapons: ds3EquippedWeapons(buf, iddb, v),
    equipped_armor: ds3EquippedArmor(buf, iddb, v),
    equipped_rings: ds3EquippedRings(buf, iddb, v),
    equipped_ammo: ds3EquippedAmmo(buf, iddb, v),
    boss_souls: findBossSouls(goods), key_items: keyItems,
    inv, unknown_count: 0,
  };
}
// DS3 embered state: 1 -> true, 0 -> false, anything else (or no anchor) -> null.
function ds3Embered(buf, v) {
  if (v == null) return null;
  const e = u8(buf, v + DS3_EMBER_D);
  return e === 1 ? true : e === 0 ? false : null;
}
// DS3 covenant name, or null. Only ids in the table are named, so 0 (no covenant) and
// a cheated slot's junk handle both fall through to null rather than being guessed.
function ds3Covenant(buf, v) {
  if (v == null) return null;
  const h = u32(buf, v + DS3_COVENANT_D);
  return h ? (DS3_COVENANT.get(h & 0x0FFFFFFF) ?? null) : null;
}
// EquipGameData sits a fixed 664 bytes past the stat anchor; armour handles at
// +0x20..+0x2C, head-to-toe. See sl2_to_md.py DS3_EQUIP_D / DS3_ARMOR_SLOTS.
const DS3_EQUIP_D = 664;
const DS3_ARMOR_SLOTS = [["Head", 0x20], ["Chest", 0x24], ["Hands", 0x28], ["Legs", 0x2C]];
// Ring slots +0x34..+0x40; a ring's handle encodes its id (type nibble 0xA -> 0x2).
// See sl2_to_md.py DS3_RING_SLOTS / ds3_equipped_rings.
const DS3_RING_SLOTS = [0x34, 0x38, 0x3C, 0x40];
const DS3_RING_ID_MASK = 0x0FFFFFFF, DS3_RING_ID_TYPE = 0x20000000;
// Ammo (arrow/bolt) slots +0x08..+0x14, GaItem handles resolving to the bolts category.
const DS3_AMMO_SLOTS = [0x08, 0x0C, 0x10, 0x14];
// Weapon slots: the struct interleaves the hands (LH1,RH1,LH2,RH2,LH3,RH3) starting
// 0x10 before the armour base, so right = -0xC/-0x4/+0x4, left = -0x10/-0x8/+0x0.
// Pinned by a weapon-swap differential; the id carries the infusion, not the +N.
// See sl2_to_md.py DS3_WEAPON_SLOTS / ds3_equipped_weapons.
const DS3_WEAPON_SLOTS = [["Right Hand", -0x0C], ["Right Hand 2", -0x04], ["Right Hand 3", 0x04],
  ["Left Hand", -0x10], ["Left Hand 2", -0x08], ["Left Hand 3", 0x00]];
// Bare-fist id: an empty weapon slot reads this, not a null handle, so skip it.
const DS3_FISTS = 110000;
// Reinforcement is baked into the equipped weapon id as base+infusion*100+level
// (Deep Battle Axe +0/+1 = 7010900/7010901); DS3's db keys each infusion by name,
// so only the level (units, 1..10) is peeled off as a " +N" suffix. See Python.
const DS3_REINF_MAX = 10;
function ds3ResolveWeapon(iddb, iid) {
  const entry = iddb.get(iid);
  if (entry && entry[1] === "weapons") return entry[0];
  const level = iid % 100;
  if (level < 1 || level > DS3_REINF_MAX) return null;
  const base = iddb.get(iid - level);
  return base && base[1] === "weapons" ? `${base[0]} +${level}` : null;
}
// Estus takes TWO consecutive goods ids per level (150/151 = +0 … 170/171 = +10;
// 190/191 = Ashen +0 … 210/211 = +10), which a name-keyed db cannot express, so it is
// resolved arithmetically. Only consulted after the table misses. See Python.
const DS3_GOODS_TYPE = 0x40000000, DS3_ESTUS_MAX = 10;
const DS3_ESTUS = [[150, "Estus Flask"], [190, "Ashen Estus Flask"]];
function ds3ResolveEstus(iid) {
  const raw = iid - DS3_GOODS_TYPE;
  for (const [base, name] of DS3_ESTUS) {
    const level = Math.floor((raw - base) / 2);
    if (raw >= base && level >= 0 && level <= DS3_ESTUS_MAX) {
      return level === 0 ? name : `${name} +${level}`;
    }
  }
  return null;
}
// GaItem handle -> item id (same walk as the event-flag base). Keep in sync with Python.
function ds3GaitemMap(buf) {
  const map = new Map();
  let off = DS3_GAITEM_START;
  for (let n = 0; n < DS3_GAITEM_SLOTS; n++) {
    const handle = u32(buf, off);
    if (handle == null) break;
    const iid = u32(buf, off + 4);
    if (handle && iid) map.set(handle, iid);
    const big = handle && DS3_GAITEM_TYPES_BIG.includes((handle & 0xF0000000) >>> 0);
    off += big ? DS3_GAITEM_BIG : 8;
  }
  return map;
}
// Equipped weapons (up to three per hand), resolved through the GaItem map; kept
// only where the handle lands on a real weapons item that is not the bare Fists
// (an empty hand reads Fists). Right/left verified by a weapon-swap differential.
// See sl2_to_md.py ds3_equipped_weapons.
function ds3EquippedWeapons(buf, iddb, v) {
  if (v == null) return {};
  const hmap = ds3GaitemMap(buf), base = v + DS3_EQUIP_D, out = {};
  for (const [slot, d] of DS3_WEAPON_SLOTS) {
    const handle = u32(buf, base + d);
    const iid = handle ? hmap.get(handle) : null;
    if (!iid || iid === DS3_FISTS) continue;
    const name = ds3ResolveWeapon(iddb, iid);
    if (name) out[slot] = name;
  }
  return out;
}
// Equipped armour (four protection slots), resolved through the GaItem map and
// kept only where the handle lands on a real armour item (self-consistency gate).
// Rings/covenant not read — their save layout differs from the runtime tables.
// See sl2_to_md.py ds3_equipped_armor.
function ds3EquippedArmor(buf, iddb, v) {
  if (v == null) return {};
  const hmap = ds3GaitemMap(buf), base = v + DS3_EQUIP_D, out = {};
  for (const [slot, d] of DS3_ARMOR_SLOTS) {
    const handle = u32(buf, base + d);
    const iid = handle ? hmap.get(handle) : null;
    const entry = iid != null ? iddb.get(iid) : null;
    if (entry && entry[1] === "armors") out[slot] = entry[0];
  }
  return out;
}
// Equipped rings (up to four): the handle encodes the id (nibble 0xA -> 0x2), kept
// only where it lands on a real rings item. Rings aren't in the GaItem array. See Python.
function ds3EquippedRings(buf, iddb, v) {
  if (v == null) return [];
  const base = v + DS3_EQUIP_D, out = [];
  for (const d of DS3_RING_SLOTS) {
    const handle = u32(buf, base + d);
    if (!handle) continue;
    const iid = ((handle & DS3_RING_ID_MASK) | DS3_RING_ID_TYPE) >>> 0;
    const entry = iddb.get(iid);
    if (entry && entry[1] === "rings") out.push(entry[0]);
  }
  return out;
}
// Equipped ammo (arrow/bolt quiver slots), resolved via the GaItem map; kept only
// where the handle lands on a bolts item. Weapons proper not read. See Python.
function ds3EquippedAmmo(buf, iddb, v) {
  if (v == null) return [];
  const hmap = ds3GaitemMap(buf), base = v + DS3_EQUIP_D, out = [];
  for (const d of DS3_AMMO_SLOTS) {
    const handle = u32(buf, base + d);
    const iid = handle ? hmap.get(handle) : null;
    const entry = iid != null ? iddb.get(iid) : null;
    if (entry && entry[1] === "bolts") out.push(entry[0]);
  }
  return out;
}
const ROSTER_PARAMS_DS3 = { menu: 10, occ: 4244, desc: 4254, stride: 554, namelen: 16 };
// Play time (u32 seconds) sits in the roster descriptor, +38 past the name. See sl2_to_md.py.
const DS3_ROSTER_PLAYTIME_OFF = 38;
function ds3Playtime(menu, i) {
  const p = ROSTER_PARAMS_DS3;
  return u32(menu, p.desc + p.stride * i + DS3_ROSTER_PLAYTIME_OFF);
}

// DS3 event flags (bonfires + boss defeats). Region located by walking the blocks
// before it; our decrypt drops alfizari's 4-byte length prefix, so the GaItem walk
// starts at 0x6C (their 0x70). Constants/tables mirror sl2_to_md.py — verified on a
// real save (Iudex + Cemetery/High Wall, zero false positives). Keep in sync.
const DS3_GAITEM_START = 0x6C, DS3_GAITEM_SLOTS = 6144, DS3_GAITEM_BIG = 60;
const DS3_GAITEM_TYPES_BIG = [0x80000000, 0x90000000];
const DS3_FLAG_MAX_DENSITY = 0.01, DS3_FLAG_SAMPLE = 0x8000;
// Bonfires + boss flags both come from db_ds3/*.json (bonfires: area -> [[dist,bit,name]];
// boss_flags: name -> [dist,bit]), generated from the DS3 flag-id list via the flag-id->bit
// formula. See sl2_to_md.py load_ds3_bonfires / load_ds3_boss_flags.
function ds3EventFlagBase(buf) {
  let off = DS3_GAITEM_START;
  for (let n = 0; n < DS3_GAITEM_SLOTS; n++) {
    const handle = u32(buf, off);
    if (handle == null) return null;
    // `& 0xF0000000` yields a signed int32 in JS — >>>0 back to unsigned so the
    // weapon/armour top-nibble compare matches (handles are >= 0x80000000).
    const big = handle && DS3_GAITEM_TYPES_BIG.includes((handle & 0xF0000000) >>> 0);
    off += big ? DS3_GAITEM_BIG : 8;
  }
  const aboveCounter = off + 0x13F + 0x1DD + 0x8808 + 0x11C;
  const aboveSize = u32(buf, aboveCounter);
  if (aboveSize == null) return null;
  const gestureEnd = aboveCounter + 4 + aboveSize * 8 + 0x18C + 0x4 + 0x8800 + 0xC + 0xA4;
  const table2Size = u32(buf, gestureEnd);
  if (table2Size == null) return null;
  const base = gestureEnd + 4 + table2Size * 4 + 0x92 + 0xBCC - 0x12;
  if (!(base >= 0 && base < buf.length)) return null;
  // Event flags are sparse (a 100% NG+ slot measures 0.0022 set bits); ordinary save
  // data is far denser, so a base that walks off the region gives itself away and is
  // rejected rather than read as progress. See sl2_to_md.py DS3_FLAG_MAX_DENSITY.
  const sample = buf.subarray(base, base + DS3_FLAG_SAMPLE);
  if (!sample.length) return null;
  let bits = 0;
  for (let i = 0; i < sample.length; i++) bits += popcount(sample[i]);
  return bits / (sample.length * 8) <= DS3_FLAG_MAX_DENSITY ? base : null;
}
function popcount(x) { let c = 0; while (x) { c += x & 1; x >>>= 1; } return c; }
function ds3AttachFlags(ch, buf, base, bonfireDb, bossFlagDb, questlineDb, covenantDb,
                        bossVictoryDb, lordCinderDb, pickupDb) {
  if (base == null) return;
  const areas = [];
  let anyLit = false;
  for (const [area, bonfires] of Object.entries(bonfireDb || {})) {
    const named = [], missing = [];
    for (const [dist, bit, name] of bonfires) {
      const val = u8(buf, base + dist);
      (val != null && (val & (1 << bit)) ? named : missing).push(name);
    }
    anyLit = anyLit || named.length > 0;
    areas.push([area, named.length, named, bonfires.length, missing]);
  }
  // Every area is kept, lit or not — an area reading 0/5 is the useful half of the
  // report. Only a slot with nothing lit anywhere gets no section at all.
  if (anyLit) ch.bonfire_areas = areas;
  const bosses = {};
  for (const [b, s] of Object.entries(ch.bosses || {})) bosses[b] = new Set(s);
  for (const table of [bossFlagDb || {}, bossVictoryDb || {}]) {
    for (const [name, [dist, bit]] of Object.entries(table)) {
      const val = u8(buf, base + dist);
      if (val != null && (val & (1 << bit))) (bosses[name] || (bosses[name] = new Set())).add("flag");
    }
  }
  const keys = Object.keys(bosses);
  if (keys.length) {
    ch.bosses = {};
    for (const b of keys) ch.bosses[b] = [...bosses[b]].sort();
  }
  const cinders = [];
  for (const [lord, [dist, bit]] of Object.entries(lordCinderDb || {})) {
    const val = u8(buf, base + dist);
    if (val != null && (val & (1 << bit))) cinders.push(lord);
  }
  if (cinders.length) ch.cinders = cinders;
  const quests = {};
  for (const [src, rewards] of Object.entries(questlineDb || {})) {
    const got = [];
    for (const [dist, bit, rw] of rewards) {
      const val = u8(buf, base + dist);
      if (val != null && (val & (1 << bit))) got.push(rw);
    }
    if (got.length) quests[src] = got;
  }
  if (Object.keys(quests).length) ch.questlines = quests;
  // World pickups: only the areas whose flag group has a derived base are in the
  // table at all, so an area missing here means "not tracked", never "nothing found".
  const picks = [];
  let anyFound = false;
  for (const [area, items] of Object.entries(pickupDb || {})) {
    const got = [], missing = [];
    for (const [dist, bit, item] of items) {
      const val = u8(buf, base + dist);
      (val != null && (val & (1 << bit)) ? got : missing).push(item);
    }
    anyFound = anyFound || got.length > 0;
    picks.push([area, got.length, items.length, missing]);
  }
  if (anyFound) ch.pickups = picks;
  const covs = {};
  for (const [cov, marks] of Object.entries(covenantDb || {})) {
    const got = [];
    for (const [dist, bit, what] of marks) {
      const val = u8(buf, base + dist);
      if (val != null && (val & (1 << bit))) got.push(what);
    }
    if (got.length) covs[cov] = got;
  }
  if (Object.keys(covs).length) ch.covenants = covs;
}
// DS3 NG+ cycle: uint16 just before the event-flag region; guarded to a sane range
// (a cheated mule reads 0xFFFF). See sl2_to_md.py.
const DS3_NG_MAX = 99;
function ds3Journey(buf, base) {
  if (base == null) return null;
  const ng = u16(buf, base + 0x12 - 0xBCC);
  return ng != null && ng >= 0 && ng <= DS3_NG_MAX ? ng : null;
}
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
  ds2sotfs: { title: "Dark Souls II: Scholar of the First Sin", tier: "full", slots: [1, 11] },
  ds2vanilla: { title: "Dark Souls II", tier: "full", slots: [1, 11] },
  dsr: { title: "Dark Souls Remastered", tier: "full", slots: [0, 10] },
  ptde: { title: "Dark Souls: Prepare to Die Edition", tier: "full", slots: [0, 10] },
  ds3: { title: "Dark Souls III", tier: "full", slots: [0, 10] },
  er: { title: "Elden Ring", tier: "full", slots: [0, 10] },
};

/**
 * Which game a save is, without parsing a single character. Detection reads only
 * the BND4 header (plus, for DS2, a trial decrypt of one block), so the caller can
 * find out which game it is holding BEFORE fetching any item table — which is what
 * lets the page load one game's databases instead of all four.
 * @param {Uint8Array} data the whole file
 * @returns {string} a GAMES key. Throws ParseError on an unsupported save.
 */
export function detectSaveGame(data) {
  data = data instanceof Uint8Array ? data : new Uint8Array(data);
  return detectGame(data, parseBnd4(data));
}

// Games that stamp a save-format version as a uint32 at slot +0: DSR reads 71, DS3 98,
// ER 220 or 251. It is NOT the patch (two ER saves here differ while their regulation
// version matches). DS2 is absent on purpose — it reads a constant 0x6F there on
// vanilla, Scholar and every mule alike, so that word is structure, not a version — and
// PtDE's first word is its slot size. See save_format_version in sl2_to_md.py.
const SAVE_VERSION_GAMES = new Set(["dsr", "ds3", "er"]);
const SAVE_VERSION_MAX = 4095;

/** The save-format version this file was written with, or null. */
function saveFormatVersion(data, entries, game, slots) {
  if (!SAVE_VERSION_GAMES.has(game)) return null;
  const dec = game === "dsr" ? (b) => decryptIvPrefixed(b, DSR_KEY)
    : game === "ds3" ? (b) => decryptIvPrefixed(b, DS3_KEY) : decryptNone;
  for (let i = slots[0]; i < slots[1]; i++) {
    if (i >= entries.length) continue;
    const buf = dec(blobOf(data, entries[i]));   // an unused slot is all zeros
    if (buf === null) continue;
    const v = u32(buf, 0);
    if (v != null && v > 0 && v <= SAVE_VERSION_MAX) return v;
  }
  return null;
}

// Elden Ring ships its regulation inside the save, in BND4 entry 11 behind a " GER"
// magic, and that block is versioned: a uint32 laid out M-mm-p-bbbb. See er_game_patch.
const ER_REG_ENTRY = 11;
const ER_REG_VER_OFF = 8;

/** Elden Ring's game patch, decoded from its regulation version, or null. */
function erGamePatch(data, entries) {
  if (entries.length <= ER_REG_ENTRY) return null;
  const buf = decryptNone(blobOf(data, entries[ER_REG_ENTRY]));
  if (buf.length < 4 || buf[0] !== 0x20 || buf[1] !== 0x47 || buf[2] !== 0x45 || buf[3] !== 0x52) return null;
  const v = u32(buf, ER_REG_VER_OFF);
  if (v == null || v < 10000000 || v > 19999999) return null;
  const minor = Math.floor(v / 100000) % 100;
  return `${Math.floor(v / 10000000)}.${String(minor).padStart(2, "0")}.${Math.floor(v / 10000) % 10}`;
}

/**
 * Parse a whole save into characters. `dbs` is the preloaded database bundle
 * (see db.js). Returns {game, title, characters:[{slot, ch}], bonfireTotal}.
 * Throws ParseError on an unsupported/short save (message is user-facing).
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
      if (ch) {
        attachDefeatedBosses(ch, dbs);
        attachProgressTotals(ch, dbs);
        characters.push({ slot: label(i), ch });
      }
    }
  } else if (game === "ds3") {
    const menu = decryptIvPrefixed(blobOf(data, entries[10]), DS3_KEY);
    const names = menu ? parseRosterDs3(menu) : new Map();
    for (let i = meta.slots[0]; i < meta.slots[1]; i++) {
      if (i >= entries.length) continue;
      const slot = decryptIvPrefixed(blobOf(data, entries[i]), DS3_KEY);
      if (slot === null) continue;
      const ch = ds3Parse(slot, dbs.ds3.items, names.get(i));
      if (ch) {
        if (menu) ch.play_time = ds3Playtime(menu, i);
        const flagBase = ds3EventFlagBase(slot); // walk the block chain once
        ch.ng_plus = ds3Journey(slot, flagBase);
        attachDefeatedBosses(ch, dbs);
        ds3AttachFlags(ch, slot, flagBase, dbs.ds3.bonfires, dbs.ds3.bossFlags, dbs.ds3.questlines,
          dbs.ds3.covenants, dbs.ds3.bossVictory, dbs.ds3.lordCinders, dbs.ds3.pickups);
        attachProgressTotals(ch, dbs);
        characters.push({ slot: label(i), ch });
      }
    }
  } else {
    // DS2 (full, encrypted + augment + active-filter) and DS1 (dsr/ptde).
    // The header and world blocks use the same key as the slot, so the vanilla key
    // has to reach ds2ActiveSlots/ds2Augment too — reading them with the Scholar key
    // yields noise, not an empty result.
    const isDs2 = DS2_GAMES.has(game);
    const ds2Key = game === "ds2vanilla" ? DS2_VANILLA_KEY : DS2_KEY;
    const ds2Dec = (b) => decryptDs2(b, ds2Key);
    const decrypt = isDs2 ? ds2Dec : game === "dsr" ? (b) => decryptIvPrefixed(b, DSR_KEY) : decryptNone;
    const parse = isDs2 ? (b, d) => ds2Parse(b, d, game) : game === "dsr" ? dsrParse : ptdeParse;
    const itemDb = isDs2 ? dbs.ds2.items : dbs.ds1.items;
    const active = isDs2 ? ds2ActiveSlots(data, entries, meta.slots, ds2Dec) : null;
    for (let i = meta.slots[0]; i < meta.slots[1]; i++) {
      if (i >= entries.length) continue;
      if (active !== null && !active.has(i)) continue;
      const slot = decrypt(blobOf(data, entries[i]));
      if (slot === null) continue;
      const ch = parse(slot, itemDb);
      if (ch) {
        if (isDs2) ds2Augment(ch, data, entries, i, dbs, ds2Dec);
        else {
          ds1AttachPlaytime(ch, decrypt(blobOf(data, entries[DS1_MENU_ENTRY])));
          const areas = ds1Bonfires(slot, dbs.ds1.bonfires);
          if (areas) ch.bonfire_areas = areas;
        }
        // Soul/NG+ floor first: attachDefeatedBosses refuses to run once `bosses`
        // exists, so the flags must be merged on top of it, not before it.
        attachDefeatedBosses(ch, dbs);
        if (!isDs2) ds1AttachFlags(ch, slot, dbs.ds1.bossFlags, game);
        attachProgressTotals(ch, dbs);
        characters.push({ slot: label(i), ch });
      }
    }
  }
  // DS2 carries a name→image-filename map (fextralife thumbnails) for the renderer.
  const images = DS2_GAMES.has(game) ? dbs.ds2.images : null;
  // How many bonfires the game HAS, so the renderer can say "22 of 77" instead of
  // a bare count. Taken from the table rather than hardcoded, and only honest
  // because these three tables are complete (DS3 77/77, DS2 77/77, DS1 43/43).
  // Deliberately not done for bosses: those tables are a mapped subset, so a
  // denominator there would imply a roster the db does not represent.
  const fam = DS2_GAMES.has(game) ? "ds2" : game === "dsr" || game === "ptde" ? "ds1" : game;
  const bonfireTotal = (dbs[fam] && dbs[fam].bonfireTotal) || 0;
  const saveVersion = saveFormatVersion(data, entries, game, meta.slots);
  const gamePatch = game === "er" ? erGamePatch(data, entries) : null;
  return { game, title: meta.title, tier: meta.tier, characters, images, bonfireTotal, saveVersion, gamePatch };
}

export { ParseError };
