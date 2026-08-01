// The browser's JSON export: the same document the Python CLI writes with -o out.json,
// against the same published schema. Held byte-for-byte by scratch/json_harness.mjs, the
// way markdown.js is held by md_harness.mjs.
//
// Faithful to sl2/jsonout.py. If you change a key, a value shape, or the order they are
// written in, change it there too — a consumer validating against schema.json should not
// be able to tell which front end produced the file.

import { REPO_URL } from "./markdown.js";

/** Where the schema is published. Static file at the site root. */
export const SCHEMA_URL = "https://darthdemono.github.io/sl2-analyzer/schema.json";

/** Semver for the document format. MINOR adds an optional field, MAJOR breaks a reader. */
export const SCHEMA_VERSION = "1.0.0";

/**
 * ISO-8601 UTC to the second, which is what the Python writes. `toISOString` includes
 * milliseconds and those would be the only difference between the two exports.
 */
function stampUtc(now = new Date()) {
  return now.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * True for the values the Python skips: None, an empty list, an empty dict. Everything
 * else is written, including 0 and false, which are real readings rather than gaps.
 * @param {*} v
 */
function isEmpty(v) {
  if (v === null || v === undefined) return true;
  if (Array.isArray(v)) return v.length === 0;
  if (v instanceof Map || v instanceof Set) return v.size === 0;
  return typeof v === "object" && Object.keys(v).length === 0;
}

/**
 * Make a parsed value safe for JSON.stringify without changing what it says. The parser
 * hands back plain arrays and objects already; a Map or Set can only appear if a future
 * reader introduces one, and this keeps that from silently serialising as `{}`.
 * @param {*} v
 */
function jsonable(v) {
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [k, jsonable(x)]));
  if (v instanceof Set) return [...v].sort();
  if (Array.isArray(v)) return v.map(jsonable);
  if (v && typeof v === "object") {
    const out = {};
    for (const [k, x] of Object.entries(v)) out[k] = jsonable(x);
    return out;
  }
  return v;
}

/**
 * One character: its slot number, then every field the parse actually set. Absent stays
 * absent — that is the contract the schema documents, so a consumer can tell "this game
 * does not store it" from "it is zero".
 * @param {number} slotNo 1-based slot number
 * @param {object} ch the character object
 */
function characterJson(slotNo, ch) {
  const out = { slot: slotNo };
  for (const [key, value] of Object.entries(ch)) {
    if (isEmpty(value)) continue;
    out[key] = jsonable(value);
  }
  return out;
}

/**
 * Build the whole JSON document for a parsed save.
 * @param {object} result what parseSave returned
 * @param {string} filename the source filename, recorded so an export can be traced back
 * @param {object} [meta] caller-supplied environment, or null. The page has no way to know
 *        any of it, so it is only ever present when something passed it in.
 * @returns {object} ready for JSON.stringify
 */
export function buildJson(result, filename, meta = null) {
  const source = {
    filename: (filename || "").split(/[/\\]/).pop(),
    game: result.game,
    game_title: result.title,
    support_tier: result.tier || "full",
  };
  // Both are properties of the FILE, not of any character, and both are often absent —
  // DS2 has no version word and only Elden Ring carries a regulation version.
  if (result.saveVersion != null) source.save_format_version = result.saveVersion;
  if (result.gamePatch != null) source.game_patch = result.gamePatch;

  const doc = {
    $schema: SCHEMA_URL,
    schema_version: SCHEMA_VERSION,
    generated: stampUtc(),
    tool: { name: "sl2-analyzer", url: REPO_URL },
    source,
  };
  if (meta && Object.keys(meta).length) doc.environment = { ...meta };
  doc.characters = result.characters.map(({ slot, ch }) => characterJson(slot, ch));
  return doc;
}

/** The document as the text that gets written to a file — 2-space indent, like the CLI. */
export function buildJsonText(result, filename, meta = null) {
  return `${JSON.stringify(buildJson(result, filename, meta), null, 2)}\n`;
}
