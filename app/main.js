// Browser entry: parse a dropped/picked .sl2 entirely client-side and render it.
// The save file never leaves the page.
//
// Parsing runs in a Web Worker so a big save cannot freeze the tab (a DS3 save is
// ~0.9 s of solid CPU). If module workers are unavailable the same code runs inline
// — the worker is a responsiveness win, never a requirement.

import { renderSave } from "./render.js";

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

function wire() {
  const drop = $("drop");
  const input = $("file");
  input.addEventListener("change", () => {
    const f = input.files[0];
    // Clearing the value is what lets you pick the SAME file again — otherwise the
    // second selection is not a change and the event never fires.
    input.value = "";
    if (f) handleFile(f);
  });
  // #drop is a real <button>, so click/Enter/Space all come through natively.
  drop.addEventListener("click", () => input.click());
  ["dragover", "dragenter"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) handleFile(f); });
  // A dropped file anywhere else would otherwise navigate away from the page.
  ["dragover", "drop"].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault()));

  startWorker();

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
else wire();
