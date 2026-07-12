// AES-128-CBC decrypt, no padding — the one crypto primitive Souls saves need.
// WebCrypto can't do this (its AES-CBC forces PKCS#7 and throws on raw Souls
// ciphertext), so this is a small self-contained implementation. S-boxes are
// generated from GF(2^8) arithmetic rather than pasted, so there is no 256-entry
// table to mistype; correctness is gated by the Node parity harness against the
// Python tool's decrypted output.

/** GF(2^8) multiply (the AES field). */
function gmul(a, b) {
  let p = 0;
  for (let i = 0; i < 8; i++) {
    if (b & 1) p ^= a;
    const hi = a & 0x80;
    a = (a << 1) & 0xff;
    if (hi) a ^= 0x1b;
    b >>= 1;
  }
  return p;
}

// Build the forward/inverse S-boxes: multiplicative inverse then the AES affine map.
const SBOX = new Uint8Array(256);
const INV_SBOX = new Uint8Array(256);
(function buildSboxes() {
  const inv = new Uint8Array(256);
  for (let i = 1; i < 256; i++) {
    for (let j = 1; j < 256; j++) {
      if (gmul(i, j) === 1) { inv[i] = j; break; }
    }
  }
  for (let i = 0; i < 256; i++) {
    let x = inv[i];
    let s = x;
    for (let c = 0; c < 4; c++) { x = ((x << 1) | (x >> 7)) & 0xff; s ^= x; }
    s ^= 0x63;
    SBOX[i] = s;
    INV_SBOX[s] = i;
  }
})();

/** Expand a 16-byte key to the 176-byte AES-128 round-key schedule. */
function keyExpansion(key) {
  const w = new Uint8Array(176);
  w.set(key, 0);
  let rcon = 1;
  for (let i = 16; i < 176; i += 4) {
    let t0 = w[i - 4], t1 = w[i - 3], t2 = w[i - 2], t3 = w[i - 1];
    if (i % 16 === 0) {
      const r0 = SBOX[t1] ^ rcon, r1 = SBOX[t2], r2 = SBOX[t3], r3 = SBOX[t0];
      t0 = r0; t1 = r1; t2 = r2; t3 = r3;
      rcon = gmul(rcon, 2);
    }
    w[i] = w[i - 16] ^ t0;
    w[i + 1] = w[i - 15] ^ t1;
    w[i + 2] = w[i - 14] ^ t2;
    w[i + 3] = w[i - 13] ^ t3;
  }
  return w;
}

function addRoundKey(s, w, round) {
  const base = 16 * round;
  for (let i = 0; i < 16; i++) s[i] ^= w[base + i];
}

function invSubBytes(s) {
  for (let i = 0; i < 16; i++) s[i] = INV_SBOX[s[i]];
}

// Rows are stored as s[r + 4c]; InvShiftRows rotates row r right by r.
function invShiftRows(s) {
  for (let r = 1; r < 4; r++) {
    const row = [s[r], s[r + 4], s[r + 8], s[r + 12]];
    for (let c = 0; c < 4; c++) s[r + 4 * ((c + r) % 4)] = row[c];
  }
}

function invMixColumns(s) {
  for (let c = 0; c < 4; c++) {
    const a0 = s[4 * c], a1 = s[4 * c + 1], a2 = s[4 * c + 2], a3 = s[4 * c + 3];
    s[4 * c]     = gmul(a0, 14) ^ gmul(a1, 11) ^ gmul(a2, 13) ^ gmul(a3, 9);
    s[4 * c + 1] = gmul(a0, 9)  ^ gmul(a1, 14) ^ gmul(a2, 11) ^ gmul(a3, 13);
    s[4 * c + 2] = gmul(a0, 13) ^ gmul(a1, 9)  ^ gmul(a2, 14) ^ gmul(a3, 11);
    s[4 * c + 3] = gmul(a0, 11) ^ gmul(a1, 13) ^ gmul(a2, 9)  ^ gmul(a3, 14);
  }
}

/** Decrypt one 16-byte block (AES-128 inverse cipher). */
function invCipher(block, w) {
  const s = block.slice(0, 16);
  addRoundKey(s, w, 10);
  for (let round = 9; round >= 1; round--) {
    invShiftRows(s);
    invSubBytes(s);
    addRoundKey(s, w, round);
    invMixColumns(s);
  }
  invShiftRows(s);
  invSubBytes(s);
  addRoundKey(s, w, 0);
  return s;
}

/**
 * AES-128-CBC decrypt, truncated to whole blocks (matches Python `_aes_cbc`).
 * @param {Uint8Array} key 16 bytes
 * @param {Uint8Array} iv  16 bytes
 * @param {Uint8Array} ct  ciphertext
 * @returns {Uint8Array} plaintext (length = floor(ct.length/16)*16)
 */
export function aesCbcDecrypt(key, iv, ct) {
  const w = keyExpansion(key);
  const n = Math.floor(ct.length / 16) * 16;
  const out = new Uint8Array(n);
  let prev = iv;
  for (let o = 0; o < n; o += 16) {
    const block = ct.subarray(o, o + 16);
    const dec = invCipher(block, w);
    for (let k = 0; k < 16; k++) out[o + k] = dec[k] ^ prev[k];
    prev = block.slice(0, 16);
  }
  return out;
}

/** Hex string to Uint8Array. */
export function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
