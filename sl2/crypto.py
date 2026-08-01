"""Per-game entry decryption. Each returns the plaintext game data for one entry,
or None on a bad read.
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .reader import u32
from .keys import DS2_KEY


##
# @brief AES-128-CBC decrypt, truncated to a whole number of blocks.
# @param key The 16-byte key.
# @param iv  The 16-byte initialisation vector.
# @param ct  The ciphertext.
# @return The decrypted bytes.
def _aes_cbc(key, iv, ct):
    ct = ct[:len(ct) // 16 * 16]
    return Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor().update(ct)


##
# @brief Decrypt a DS2 entry: [16B MD5][16B IV][ciphertext], plaintext prefixed
#        by a uint32 length.
# @param blob The raw entry bytes.
# @param key  DS2_KEY (Scholar) or DS2_VANILLA_KEY (the DX9 original). The two
#             variants share this layout exactly; only the key differs.
# @return The game data, or None if the length prefix is unreadable.
def decrypt_ds2(blob, key=DS2_KEY):
    pt = _aes_cbc(key, blob[16:32], blob[32:])
    dlen = u32(pt, 0)
    # The length must fit the block. A wrong key decrypts to noise whose "length" is
    # a random uint32, so this doubles as a key check: rejecting it here means a
    # mismatched key yields None (feature off) instead of a buffer of noise that the
    # world-block readers would happily mistake for set event flags.
    if dlen is None or not 0 < dlen <= len(pt) - 4:
        return None
    return pt[4:4 + dlen]


##
# @brief Decrypt a DSR or DS3 entry. The IV doubles as the first ciphertext
#        block, so the first 16 decrypted bytes are discarded; the length sits at
#        offset 16 and the data starts at 20.
# @param blob The raw entry bytes.
# @param key  DSR or DS3 key.
# @return The game data, or None if the length is unreadable.
def decrypt_iv_prefixed(blob, key):
    dec = _aes_cbc(key, blob[16:32], blob[16:])
    dlen = u32(dec, 16)
    return None if dlen is None else dec[20:20 + dlen]


##
# @brief "Decrypt" an unencrypted entry (PtDE, Elden Ring). Only the MD5+IV
#        header is stripped; the rest is already plaintext.
# @param blob The raw entry bytes.
# @return The game data.
def decrypt_none(blob):
    return blob[16:]
