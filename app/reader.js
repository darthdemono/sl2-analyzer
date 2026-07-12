// Bounds-checked buffer reads — the JS mirror of the Python defensive helpers.
// Every parse read goes through these: an out-of-range access returns null (or "")
// instead of throwing or reading past the buffer, so a malformed/short save
// degrades to "unknown" rather than crashing. Buffers are Uint8Array throughout.

/** Little-endian unsigned int, or null if the read runs past the end. */
export function readUint(buf, off, size) {
  if (off == null || off < 0 || off + size > buf.length) return null;
  let v = 0;
  for (let i = size - 1; i >= 0; i--) v = v * 256 + buf[off + i];
  return v;
}

export const u8 = (buf, off) => readUint(buf, off, 1);
export const u16 = (buf, off) => readUint(buf, off, 2);
export const u32 = (buf, off) => readUint(buf, off, 4);
export const u64 = (buf, off) => readUint(buf, off, 8);

const UTF16 = new TextDecoder("utf-16le", { fatal: false });

/**
 * Decode a UTF-16LE string ending at the first null pair. Mirrors the Python
 * `read_utf16`, including its quirk: the null pair is found at ANY byte index
 * (not only even), then the slice is kept byte-pair aligned via `end + (end & 1)`.
 */
export function readUtf16(buf, off, maxChar) {
  if (off == null || off < 0 || off >= buf.length) return "";
  const raw = buf.subarray(off, Math.min(off + maxChar * 2, buf.length));
  let end = -1;
  for (let i = 0; i + 1 < raw.length; i++) {
    if (raw[i] === 0 && raw[i + 1] === 0) { end = i; break; }
  }
  const slice = end !== -1 ? raw.subarray(0, end + (end & 1)) : raw;
  return UTF16.decode(slice).replace(/\u0000+$/, "");
}

const NAME_OK = new Set(
  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_'".split("")
);

/** Is a decoded string a plausible character name (non-empty, allowed chars only)? */
export function isValidName(name) {
  if (!name) return false;
  for (const c of name) if (!NAME_OK.has(c)) return false;
  return true;
}

/** First index of `pattern` (Uint8Array) in `buf` at or after `start`, or -1. */
export function indexOf(buf, pattern, start = 0) {
  const n = buf.length, m = pattern.length;
  if (m === 0) return start;
  for (let i = Math.max(0, start); i + m <= n; i++) {
    let ok = true;
    for (let j = 0; j < m; j++) {
      if (buf[i + j] !== pattern[j]) { ok = false; break; }
    }
    if (ok) return i;
  }
  return -1;
}
