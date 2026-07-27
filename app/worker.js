// Parsing worker. Decrypting and scanning a save is ~0.1-1 s of solid CPU, which
// on the main thread means a tab that cannot paint or scroll for that long. All of
// it runs here instead; only the finished character objects cross back.
//
// Everything parseSave returns is plain objects, arrays, numbers and strings — the
// Maps and Sets it uses internally are converted before they land on a character —
// so the result structured-clones without any serialisation step of its own.

import { parseSave, detectSaveGame, ParseError } from "./parser.js";
import { loadDbsFor, DB_FAMILY } from "./db.js";

// A worker's relative fetches resolve against the WORKER's url (…/app/), not the
// page's, so "db_ds2/x.json" would ask for "app/db_ds2/x.json". Resolve db paths
// against the site root explicitly.
const ROOT = new URL("../", import.meta.url);
const getJSON = async (p) => {
  const r = await fetch(new URL(p, ROOT));
  if (!r.ok) throw new Error(`fetch ${p}: ${r.status}`);
  return r.json();
};

// One save per game per session is the common case, but a second DS3 file should
// not refetch 11 tables. Keyed by family, holding the promise so two saves dropped
// at once share a single load.
const families = new Map();
function dbsFor(family) {
  if (!families.has(family)) families.set(family, loadDbsFor(getJSON, [family]));
  return families.get(family);
}

self.addEventListener("message", async ({ data }) => {
  const { id, buf } = data;
  try {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    // Detect first: it reads only the BND4 header, so the tables we fetch next are
    // the one game's, not all four.
    const game = detectSaveGame(bytes);
    const dbs = await dbsFor(DB_FAMILY[game]);
    self.postMessage({ id, ok: true, result: parseSave(bytes, dbs) });
  } catch (e) {
    // Error subclasses do not survive structured clone, so the "is this a
    // user-facing message or an internal crash" bit is sent alongside it.
    self.postMessage({ id, ok: false, error: e && e.message ? e.message : String(e),
                       parseError: e instanceof ParseError });
  }
});
