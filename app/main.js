// Browser entry: parse a dropped/picked .sl2 entirely client-side and render it.
// The save file never leaves the page.
//
// Parsing runs in a Web Worker so a big save cannot freeze the tab (a DS3 save is
// ~0.9 s of solid CPU). If module workers are unavailable the same code runs inline
// — the worker is a responsiveness win, never a requirement.

import { renderSave } from "./render.js";
import { buildCombined } from "./combine.js";
import { renderMarkdown } from "./mdview.js";

const $ = (id) => document.getElementById(id);
const out = $("out");
const status = $("status");

function setStatus(msg) { status.textContent = msg; }

function showError(msg) {
  out.replaceChildren();
  const box = document.createElement("div");
  box.className = "error";
  box.setAttribute("role", "alert");
  box.textContent = msg;
  out.append(box);
}

// ── Parsing backend: a worker when we can have one, inline otherwise ──────────

let worker = null, workerJobs = new Map(), nextJob = 1;

function startWorker() {
  if (worker !== null || typeof Worker === "undefined") return worker;
  try {
    worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
    worker.addEventListener("message", ({ data }) => {
      const job = workerJobs.get(data.id);
      if (!job) return;
      workerJobs.delete(data.id);
      if (data.ok) { job.resolve(data.result); return; }
      const err = new Error(data.error);
      err.parseError = data.parseError;   // ParseError does not survive the clone
      job.reject(err);
    });
    // A worker that fails to boot (no module-worker support) must not kill the page:
    // drop it and let every later parse take the inline path.
    worker.addEventListener("error", () => {
      for (const job of workerJobs.values()) job.reject(new Error("worker failed"));
      workerJobs.clear();
      worker.terminate();
      worker = false;
    });
  } catch { worker = false; }
  return worker;
}

/** Inline fallback: the exact same pipeline, just on the main thread. */
async function parseInline(buf) {
  const [{ parseSave, detectSaveGame }, { loadDbsFor, DB_FAMILY }] =
    await Promise.all([import("./parser.js"), import("./db.js")]);
  const getJSON = async (p) => {
    const r = await fetch(p);
    if (!r.ok) throw new Error(`fetch ${p}: ${r.status}`);
    return r.json();
  };
  const game = detectSaveGame(buf);
  const dbs = await loadDbsFor(getJSON, [DB_FAMILY[game]]);
  return parseSave(buf, dbs);
}

function parseInWorker(buf) {
  const w = startWorker();
  if (!w) return parseInline(buf);
  return new Promise((resolve, reject) => {
    const id = nextJob++;
    workerJobs.set(id, { resolve, reject });
    // Transfer the buffer instead of copying it — saves ~9-28 MB per save.
    w.postMessage({ id, buf }, [buf.buffer]);
  }).catch((e) => {
    // The worker died mid-job (see the error handler above). The buffer was
    // transferred away, so there is nothing left to retry with — say so plainly.
    if (e.message === "worker failed") throw new Error("The background parser stopped. Reload the page and try again.");
    throw e;
  });
}

// ── File handling ────────────────────────────────────────────────────────────

async function handleFile(file) {
  setStatus(`Reading ${file.name}…`);
  out.replaceChildren();
  try {
    const buf = new Uint8Array(await file.arrayBuffer());
    setStatus(`Parsing ${file.name}…`);
    const result = await parseInWorker(buf);
    out.replaceChildren(renderSave(result, file.name));
    setStatus(`Parsed ${file.name} — ${result.title}`);
  } catch (e) {
    setStatus("");
    // A ParseError is a message written for the user ("not a supported Souls
    // save"). Anything else is a bug or a broken file, so it gets a wrapper.
    const userFacing = e && (e.parseError || e.name === "ParseError");
    showError(userFacing ? e.message : `Could not read this file: ${e && e.message ? e.message : e}`);
  }
}

// ── Combined mode ────────────────────────────────────────────────────────────

let combined = false;

/** Mermaid is 3.4 MB, so it is fetched the first time a chart actually needs it,
 *  never on a plain single-save visit. Cached by the service worker afterwards. */
let mermaidReady = null;
function ensureMermaid() {
  if (mermaidReady) return mermaidReady;
  mermaidReady = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "vendor/mermaid.min.js";
    s.onload = () => resolve(window.mermaid);
    s.onerror = () => reject(new Error("chart library did not load"));
    document.head.append(s);
  }).then((mermaid) => {
    // Themed off the page's own CSS variables rather than one of mermaid's presets:
    // the site is dark by design (it does not follow the OS), so a preset picked from
    // prefers-color-scheme draws white boxes on a black page.
    const css = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);
    const ink = v("--ink", "#cbb98d");
    const accent = v("--accent", "#c7a85c");
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: "'EB Garamond', Georgia, serif",
      themeVariables: {
        background: v("--bg", "#08080a"),
        primaryColor: v("--bg2", "#0d0c0a"),
        primaryTextColor: ink,
        primaryBorderColor: accent,
        secondaryColor: v("--bg2", "#0d0c0a"),
        tertiaryColor: v("--bg", "#08080a"),
        lineColor: accent,
        textColor: ink,
        mainBkg: v("--bg2", "#0d0c0a"),
        nodeBorder: accent,
        clusterBkg: v("--bg", "#08080a"),
        edgeLabelBackground: v("--bg", "#08080a"),
      },
    });
    return mermaid;
  });
  return mermaidReady;
}

/** A drop can carry folders; the file input can carry a directory. Walk either into
 *  a flat list of .sl2 files, keeping the relative path so references can name them. */
async function filesFromDrop(dt) {
  const items = dt.items ? [...dt.items] : [];
  const entries = items.map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) return [...dt.files];
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      if (file.name.toLowerCase().endsWith(".sl2")) {
        out.push({ file, path: prefix + file.name });
      }
      return;
    }
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
      if (!batch.length) break;
      for (const e of batch) await walk(e, prefix + entry.name + "/");
    }
  };
  for (const e of entries) await walk(e, "");
  return out;
}

/** Normalise whatever the browser handed us to {file, path} pairs. */
const asPairs = (list) => [...list].map((f) => (f.file
  ? f : { file: f, path: f.webkitRelativePath || f.name }));

async function handleMany(list) {
  const pairs = asPairs(list).filter(({ file }) => file.name.toLowerCase().endsWith(".sl2"))
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  if (!pairs.length) { showError("No .sl2 files in that drop."); return; }
  out.replaceChildren();

  const entries = [];
  let done = 0;
  for (const { file, path } of pairs) {
    setStatus(`Reading ${++done} of ${pairs.length} — ${file.name}…`);
    let result = null;
    try {
      result = await parseInWorker(new Uint8Array(await file.arrayBuffer()));
    } catch {
      result = null;                 // a folder of backups will hold a dud eventually
    }
    entries.push({ result, file: { path, file: file.name, size: file.size,
      mtime: Math.trunc(file.lastModified / 1000) } });
  }

  const readable = entries.filter((e) => e.result).length;
  if (!readable) { setStatus(""); showError("None of those files could be read as a supported save."); return; }

  setStatus("Building the timeline…");
  const md = buildCombined(entries, null);
  const doc = document.createElement("div");
  doc.className = "result t-ds1 combined";
  doc.append(renderMarkdown(md));
  out.replaceChildren(toolbar(md), doc);
  setStatus(`Read ${readable} of ${pairs.length} files`);

  try {
    const mermaid = await ensureMermaid();
    await mermaid.run({ nodes: doc.querySelectorAll("pre.mermaid") });
  } catch {
    setStatus(`Read ${readable} of ${pairs.length} files — charts unavailable offline`);
  }
}

/** Copy / download for the combined document. */
function toolbar(md) {
  const bar = document.createElement("div");
  bar.className = "combined-actions";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "btn btn-ghost";
  copy.textContent = "Copy Markdown";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(md); copy.textContent = "Copied"; }
    catch { copy.textContent = "Copy failed"; }
    setTimeout(() => { copy.textContent = "Copy Markdown"; }, 1500);
  });
  const dl = document.createElement("button");
  dl.type = "button";
  dl.className = "btn btn-ghost";
  dl.textContent = "Download .md";
  dl.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "combined-playthrough.md";
    a.click();
    URL.revokeObjectURL(url);
  });
  bar.append(copy, dl);
  return bar;
}

function setMode(on) {
  combined = on;
  $("mode-single").classList.toggle("on", !on);
  $("mode-combined").classList.toggle("on", on);
  $("mode-single").setAttribute("aria-pressed", String(!on));
  $("mode-combined").setAttribute("aria-pressed", String(on));
  $("mode-note").textContent = on
    ? "Any number of saves, from any games — dropped together or a whole folder."
    : "One save, read in full.";
  $("drop-big").textContent = on
    ? "Drop .sl2 saves or a folder here, or click to choose"
    : "Drop a .sl2 save here, or click to choose";
  // Two inputs, because ONE cannot do both jobs: an input carrying webkitdirectory
  // refuses individual files entirely. So #file picks saves, #folder picks a folder,
  // and the folder button only exists in combined mode.
  $("file").multiple = on;
  $("pick-folder").hidden = !on;
}

function wire() {
  const drop = $("drop");
  const input = $("file");
  input.addEventListener("change", () => {
    const picked = [...input.files];
    // Clearing the value is what lets you pick the SAME file again — otherwise the
    // second selection is not a change and the event never fires.
    input.value = "";
    if (!picked.length) return;
    if (combined) handleMany(picked);
    else handleFile(picked[0]);
  });
  $("mode-single").addEventListener("click", () => setMode(false));
  $("mode-combined").addEventListener("click", () => setMode(true));
  const folder = $("folder");
  $("pick-folder").addEventListener("click", () => folder.click());
  folder.addEventListener("change", () => {
    const picked = [...folder.files];
    folder.value = "";
    if (picked.length) handleMany(picked);
  });
  // #drop is a real <button>, so click/Enter/Space all come through natively.
  drop.addEventListener("click", () => input.click());
  ["dragover", "dragenter"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", async (e) => {
    // A folder or several files means the combined document, whatever the toggle
    // says — there is no single save to summarise.
    const many = combined || e.dataTransfer.files.length > 1
      || [...(e.dataTransfer.items || [])].some((it) =>
        it.webkitGetAsEntry && (it.webkitGetAsEntry() || {}).isDirectory);
    if (many) {
      if (!combined) setMode(true);
      handleMany(await filesFromDrop(e.dataTransfer));
      return;
    }
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  });
  // A dropped file anywhere else would otherwise navigate away from the page.
  ["dragover", "drop"].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault()));

  startWorker();

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
else wire();
