/**
 * Render the combined document to DOM.
 *
 * This is not a general Markdown parser and does not want to be — it handles exactly
 * the constructs sl2/combine.py emits, and everything else is shown as plain text.
 * That is the safety property, not a limitation: nothing here ever sets innerHTML, so
 * a character called `<img onerror=...>` is text, the same as any other name.
 *
 * Mermaid blocks come out as <pre class="mermaid"> for the vendored library to pick up.
 */

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

/** `**bold**`, `_italic_`, `` `code` `` and [[refs]], applied without innerHTML. */
function inline(target, text) {
  const re = /\*\*([^*]+)\*\*|_([^_]+)_|`([^`]+)`|\[\[([^\]]+)\]\]/g;
  let at = 0,
    mt;
  while ((mt = re.exec(text)) !== null) {
    if (mt.index > at) target.append(text.slice(at, mt.index));
    if (mt[1] != null) target.append(el("b", null, mt[1]));
    else if (mt[2] != null) target.append(el("i", null, mt[2]));
    else if (mt[3] != null) target.append(el("code", null, mt[3]));
    else target.append(el("span", "ref", mt[4]));
    at = mt.index + mt[0].length;
  }
  if (at < text.length) target.append(text.slice(at));
  return target;
}

const isTableRow = (l) => l.startsWith("|") && l.endsWith("|");
const cells = (l) =>
  l
    .slice(1, -1)
    .split("|")
    .map((c) => c.trim());
const isDivider = (l) => /^\|[\s|:-]+\|$/.test(l);

/**
 * @param {string} md the combined Markdown
 * @returns {DocumentFragment} ready to append; mermaid blocks are un-rendered
 */
export function renderMarkdown(md) {
  const frag = document.createDocumentFragment();
  const lines = md.split("\n");
  let i = 0;
  // The footer is a real <details>; while inside it, blocks go there instead.
  let sink = frag,
    detailsOpen = null;
  const push = (node) => sink.append(node);

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      // fenced block
      const lang = line.slice(3).trim();
      const body = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++;
      const pre = el("pre", lang === "mermaid" ? "mermaid" : "code", body.join("\n"));
      push(pre);
      continue;
    }

    if (line === "<details>") {
      detailsOpen = el("details", "md-details");
      push(detailsOpen);
      sink = detailsOpen;
      i++;
      continue;
    }
    if (line === "</details>") {
      sink = frag;
      detailsOpen = null;
      i++;
      continue;
    }
    if (line.startsWith("<summary>")) {
      const text = line.replace(/^<summary>/, "").replace(/<\/summary>$/, "");
      push(inline(el("summary"), text));
      i++;
      continue;
    }

    if (line === "---") {
      push(el("hr"));
      i++;
      continue;
    }

    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      // The document's own H1 is the page's H2: the site already has a heading.
      const level = Math.min(6, h[1].length + 1);
      push(inline(el(`h${level}`, "md-h"), h[2]));
      i++;
      continue;
    }

    if (isTableRow(line)) {
      const table = el("table", "md-table");
      const head = cells(line);
      i++;
      if (i < lines.length && isDivider(lines[i])) i++;
      const thead = el("thead"),
        tr = el("tr");
      for (const c of head) tr.append(inline(el("th"), c));
      thead.append(tr);
      table.append(thead);
      const tbody = el("tbody");
      while (i < lines.length && isTableRow(lines[i])) {
        const row = el("tr");
        for (const c of cells(lines[i])) row.append(inline(el("td"), c));
        tbody.append(row);
        i++;
      }
      table.append(tbody);
      const wrap = el("div", "md-scroll"); // wide tables scroll, the page does not
      wrap.append(table);
      push(wrap);
      continue;
    }

    if (line.startsWith("- ")) {
      const ul = el("ul", "md-list");
      while (i < lines.length && lines[i].startsWith("- ")) {
        ul.append(inline(el("li"), lines[i].slice(2)));
        i++;
      }
      push(ul);
      continue;
    }

    if (line.trim() === "") {
      i++;
      continue;
    }

    // Anything left is a paragraph: gather until the next blank line.
    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("- ") &&
      !lines[i].startsWith("#") &&
      !lines[i].startsWith("```") &&
      !isTableRow(lines[i]) &&
      lines[i] !== "---" &&
      !lines[i].startsWith("<")
    ) {
      para.push(lines[i++]);
    }
    if (para.length) push(inline(el("p", "md-p"), para.join(" ")));
    else i++; // a stray tag we do not handle
  }
  return frag;
}
