// Save validation, ported from the Python `validators/` package and held to it by
// scratch/validator_harness.mjs. Read that package's __init__.py first: this is a
// SEPARATE PASS over an already-parsed character, it never changes what was parsed,
// and it reports contradictions rather than verdicts. No score, no "modded", no intent.
//
// Off by default in both front ends. The CLI has --validate; here it is a toggle.

/** The game cannot produce this state at all. */
export const IMPOSSIBLE = "impossible";
/** Two fields the game keeps in lockstep disagree. */
export const INCONSISTENT = "inconsistent";
/** Odd but reachable, and always carrying the legitimate cause in `note`. */
export const SUSPICIOUS = "suspicious";
/** Worst first — the order findings are sorted into. */
export const TIER_ORDER = [IMPOSSIBLE, INCONSISTENT, SUSPICIOUS];

/** Game key to the db_ folder holding its classes.json. Null: no table exists. */
export const CLASS_DB = {
  ptde: "db_ds1",
  dsr: "db_ds1",
  ds2vanilla: "db_ds2",
  ds2sotfs: "db_ds2",
  ds3: "db_ds3",
  er: "db_er",
  sdt: null,
  nr: null,
};

const finding = (rule_id, tier, title, expected, found, note = "") => {
  const f = { rule_id, tier, title, expected, found };
  if (note) f.note = note;
  return f;
};

/**
 * Derive the constants from a shipped classes.json: K per class (`sum(base) - level`,
 * the game's own level formula rearranged), and the lowest each stat can start at.
 * Computed rather than stored, exactly as validators/data.py does it, so a corrected
 * class row moves the rules with it.
 */
export function gameData(table) {
  if (!table) return null;
  const classes = table.starting_classes || {};
  const ks = new Set();
  const floors = {};
  for (const row of Object.values(classes)) {
    let total = 0;
    for (const [stat, v] of Object.entries(row.stats)) {
      total += v;
      floors[stat] = floors[stat] === undefined ? v : Math.min(floors[stat], v);
    }
    ks.add(total - row.level);
  }
  const kValues = ks.size ? [...ks].sort((a, b) => a - b) : [...(table.k_values || [])];
  return { ...table, k_values: kValues, floors, classes };
}

const statTotal = (stats) => Object.values(stats).reduce((a, b) => a + b, 0);

/** Level against stat total. Set membership, for the reasons in common.py. */
function levelVsStats(ch, gd) {
  const stats = ch.stats || {};
  const level = ch.level;
  const ks = (gd && gd.k_values) || [];
  if (!Object.keys(stats).length || level == null || !ks.length) return null;
  const total = statTotal(stats);
  if (ks.includes(total - level)) return [];
  const row = (gd.classes || {})[ch.klass] || null;
  let expected;
  if (row) {
    const k = statTotal(row.stats) - row.level;
    expected = `level ${total - k} for a stat total of ${total} (a ${ch.klass})`;
  } else if (ks.length === 1) {
    expected = `level ${total - ks[0]} for a stat total of ${total}`;
  } else {
    const levels = ks.map((k) => total - k).join(", ");
    expected = `level ${levels} for a stat total of ${total}, one per starting class`;
  }
  return [
    finding("level-vs-stats", INCONSISTENT, "Level vs stat total", expected, `level ${level}`),
  ];
}

/** Any attribute past the game's hard cap, one finding per stat. */
function statAboveCap(ch, gd) {
  const stats = ch.stats || {};
  const cap = gd && gd.stat_cap;
  if (!Object.keys(stats).length || cap == null) return null;
  return Object.keys(stats)
    .sort()
    .filter((s) => stats[s] > cap)
    .map((s) =>
      finding(
        "stat-above-cap",
        IMPOSSIBLE,
        "Stat above cap",
        `<= ${cap}`,
        `${s.toLowerCase()} ${stats[s]}`,
      ),
    );
}

/** Any attribute below the lowest value it can start at. See common.py on the floor. */
function statBelowFloor(ch, gd) {
  const stats = ch.stats || {};
  const floors = (gd && gd.floors) || {};
  if (!Object.keys(stats).length || !Object.keys(floors).length) return null;
  const row = (gd.classes || {})[ch.klass] || null;
  const base = row ? row.stats : floors;
  const where = row ? `a ${ch.klass}'s starting` : "the lowest starting";
  const out = [];
  for (const stat of Object.keys(stats).sort()) {
    const floor = base[stat];
    if (floor !== undefined && stats[stat] < floor)
      out.push(
        finding(
          "stat-below-floor",
          IMPOSSIBLE,
          "Stat below its starting value",
          `>= ${floor} (${where} ${stat.toLowerCase()})`,
          `${stat.toLowerCase()} ${stats[stat]}`,
          "A respec lowers stats but never below the class base, so this is a floor no legitimate character can be under.",
        ),
      );
  }
  return out;
}

// Python renders these with {:,}; Intl in en-US is the same grouping.
const commas = (n) => n.toLocaleString("en-US");

/** Souls, runes or soul memory past the currency cap. */
function soulsAboveCap(ch, gd) {
  const cap = gd && gd.souls_cap;
  if (cap == null) return null;
  const out = [];
  for (const [field, label] of [
    ["souls", "held"],
    ["soul_memory", "soul memory"],
  ]) {
    const v = ch[field];
    if (v != null && v > cap)
      out.push(
        finding(
          "souls-above-cap",
          IMPOSSIBLE,
          "Currency above cap",
          `<= ${commas(cap)}`,
          `${label} ${commas(v)}`,
        ),
      );
  }
  return out;
}

/** DS2 only: soul memory never goes down, so held souls cannot exceed it. */
function soulsVsSoulMemory(ch) {
  const { souls, soul_memory: memory } = ch;
  if (souls == null || !memory) return null;
  if (souls <= memory) return [];
  return [
    finding(
      "souls-vs-soul-memory",
      INCONSISTENT,
      "Souls held vs soul memory",
      `held <= soul memory ${commas(memory)}`,
      `held ${commas(souls)}`,
    ),
  ];
}

const SHARED = [levelVsStats, statAboveCap, statBelowFloor, soulsAboveCap];

/** Which rules run per game, and what each game has no data for. Mirrors rules/. */
export const REGISTRY = {
  ptde: { rules: SHARED, unimplemented: null },
  dsr: { rules: SHARED, unimplemented: null },
  ds2vanilla: { rules: [...SHARED, soulsVsSoulMemory], unimplemented: null },
  ds2sotfs: { rules: [...SHARED, soulsVsSoulMemory], unimplemented: null },
  ds3: { rules: SHARED, unimplemented: null },
  er: { rules: SHARED, unimplemented: null },
  sdt: { rules: [], unimplemented: null },
  nr: { rules: [], unimplemented: null },
};

// Kept as data rather than in each entry above so the two ports read the same way.
const UNIMPLEMENTED = {
  ds1: [
    "humanity and the soft/hard humanity caps (no verified bound for the counter)",
    "item stack caps (no stack-size column in db_ds1)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
  ],
  ds2: [
    "per-stat floors (db_ds2/classes.json ships no starting-class rows: 53 is measured from the corpus, the individual class bases are not)",
    "item stack caps (no stack-size column in db_ds2)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
  ],
  ds3: [
    "item stack caps (no stack-size column in db_ds3)",
    "weapon upgrade caps and infusion legality (no reinforceParamWeapon data)",
    "unrecognised item ids (the tables are known to be incomplete, so an unknown id is a gap in db_ds3 as often as it is an edit)",
  ],
  er: [
    "item stack caps and quantities (ER quantities are not read at all)",
    "weapon upgrade caps, ash-of-war legality (no reinforce data)",
    "anything flag-based (ER's flag region is unsolved, so no boss, grace or pickup state exists to check against)",
  ],
  sdt: [
    "everything the other games check: Sekiro stores no attributes, no level and no starting class, so the level identity has nothing to test",
    "Attack Power / Vitality bounds (no verified maximum for either counter)",
    "item stack caps (no stack-size column in db_sdt)",
  ],
  nr: [
    "all of it: Nightreign is read at roster tier (no stats, no level, no inventory), and its progression is relic- and Nightfarer-based, so no Souls rule applies",
  ],
};
const UNIMPL_KEY = { ptde: "ds1", dsr: "ds1", ds2vanilla: "ds2", ds2sotfs: "ds2" };

/**
 * Run every rule registered for a game against one parsed character.
 * @param {object} ch parsed character
 * @param {string} game game key
 * @param {object|null} table that game's classes.json, or null where none exists
 * @returns {{game: string, rules_run: number, unimplemented: string[], findings: object[]}}
 */
export function runValidation(ch, game, table) {
  const entry = REGISTRY[game];
  if (!entry)
    return {
      game,
      rules_run: 0,
      unimplemented: ["no rules module for this game key"],
      findings: [],
    };
  const gd = gameData(table);
  const findings = [];
  for (const rule of entry.rules) {
    const out = rule(ch, gd);
    if (out && out.length) findings.push(...out);
  }
  findings.sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));
  return {
    game,
    rules_run: entry.rules.length,
    unimplemented: [...(UNIMPLEMENTED[UNIMPL_KEY[game] || game] || [])],
    findings,
  };
}

/** The summary line, identical wording to validators/text.py. */
export function summaryLine(report) {
  const n = report.findings.length;
  const parts = [`${n} finding${n === 1 ? "" : "s"}.`, `Rules run: ${report.rules_run}.`];
  if (report.unimplemented.length)
    parts.push(`Not implemented for this game: ${report.unimplemented.join("; ")}.`);
  return parts.join(" ");
}
