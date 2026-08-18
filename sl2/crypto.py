"""Per-game entry decryption. Each returns the plaintext game data for one entry,
or None on a bad read.
"""

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .keys import DS2_KEY, NR_KEY
from .reader import u32


##
# @brief AES-128-CBC decrypt, truncated to a whole number of blocks.
# @param key The 16-byte key.
# @param iv  The 16-byte initialisation vector.
# @param ct  The ciphertext.
# @return The decrypted bytes.
def _aes_cbc(key, iv, ct):
    ct = ct[: len(ct) // 16 * 16]
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
    return pt[4 : 4 + dlen]


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
    return None if dlen is None else dec[20 : 20 + dlen]


##
# @brief "Decrypt" an unencrypted entry (PtDE, Elden Ring). Only the MD5+IV
#        header is stripped; the rest is already plaintext.
# @param blob The raw entry bytes.
# @return The game data.
def decrypt_none(blob):
    return blob[16:]


##
# @brief Decrypt an Elden Ring Nightreign entry: [16B IV][ciphertext].
# @details Close to DS3's layout and NOT the same, which is the trap. DS3 and DSR put
# a 16-byte checksum FIRST and the IV second, so their reader takes `blob[16:32]` as
# the IV; Nightreign leads with the IV and keeps its MD5 at the *end* of the
# plaintext, 28 bytes back. Reading it the DS3 way decrypts to noise that still looks
# like a buffer.
#
# There is no length prefix either, so nothing here truncates: the whole plaintext is
# the payload. Use @ref nr_checksum_ok to tell a good decrypt from a bad one.
# @param blob The raw entry bytes.
# @param key  @ref NR_KEY.
# @return The plaintext, or None if the entry is too short to hold an IV.
def decrypt_nr(blob, key=NR_KEY):
    if len(blob) <= 16:
        return None
    return _aes_cbc(key, blob[:16], blob[16:])


## @brief Where the MD5 sits, counting back from the end of a Nightreign plaintext,
#  and how much of the plaintext it covers. The hash runs from offset 4 to the start
#  of the digest, so the first four bytes and the twelve trailing ones are outside it.
NR_MD5_FROM_END, NR_MD5_SKIP = 28, 4


##
# @brief Does a decrypted Nightreign entry hash to the digest it carries?
# @details This is the game's own integrity check, and it doubles as the key check —
# which is why the key above is stated as measured rather than trusted.
# @param pt The decrypted entry.
# @return True if the stored MD5 matches the data it covers.
def nr_checksum_ok(pt):
    if pt is None or len(pt) <= NR_MD5_FROM_END + NR_MD5_SKIP:
        return False
    end = len(pt) - NR_MD5_FROM_END
    return (
        hashlib.md5(pt[NR_MD5_SKIP:end], usedforsecurity=False).digest()
        == pt[end : end + 16]
    )
