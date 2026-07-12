// Browser entry: load databases once, then parse a dropped/picked .sl2 entirely
// client-side and render it. The save file never leaves the page.
import { parseSave, ParseError } from "./parser.js";
import { loadAllDbs } from "./db.js";
import { renderSave } from "./render.js";

const getJSON = async (p) => {
  const r = await fetch(p);
  if (!r.ok) throw new Error(`fetch ${p}: ${r.status}`);
  return r.json();
};

const $ = (id) => document.getElementById(id);
const out = $("out");
const status = $("status");

let dbsPromise = null;
function dbs() { return (dbsPromise ||= loadAllDbs(getJSON)); }

function showError(msg) {
  out.replaceChildren();
  const box = document.createElement("div");
  box.className = "error";
  box.textContent = msg;
  out.append(box);
}

async function handleFile(file) {
  status.textContent = `Reading ${file.name}…`;
  try {
    const buf = new Uint8Array(await file.arrayBuffer());
    const database = await dbs();
    const result = parseSave(buf, database);
    out.replaceChildren(renderSave(result, file.name));
    status.textContent = `Parsed ${file.name} — ${result.title}`;
  } catch (e) {
    status.textContent = "";
    showError(e instanceof ParseError ? e.message : `Could not read this file: ${e.message}`);
  }
}

function wire() {
  const drop = $("drop");
  const input = $("file");
  drop.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { if (input.files[0]) handleFile(input.files[0]); });
  ["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) handleFile(f); });
  // Warm the database cache in the background so the first parse is instant.
  dbs().catch(() => {});
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
else wire();
