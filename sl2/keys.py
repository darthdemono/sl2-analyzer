"""Encryption keys. All of these ship inside the games; none is a secret."""

## @brief AES-128 key for Dark Souls II: Scholar of the First Sin.
DS2_KEY = bytes.fromhex("599F9B699640A55236EE2D70835EC744")


## @brief AES-128 key for VANILLA Dark Souls II (the DX9 original, DARKSII0000.sl2),
#  which is a different key from Scholar of the First Sin above. From TKGP's
#  SoulsFormats `SFUtil.GetDS2SaveKey()`. Verified on a real DARKSII0000.sl2: the
#  character block decrypts to entropy 2.8 (the SOTFS key gives 7.99 noise), the name
#  reads out, and every SOTFS field offset lands — see DS2_VANILLA_LAYOUT below.
DS2_VANILLA_KEY = bytes.fromhex("B7FD463E4A9C1102DF1739E5F3B2A50F")


## @brief AES-128 key for Dark Souls Remastered.
DSR_KEY = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")


## @brief AES-128 key for Dark Souls III.
DS3_KEY = bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")


##
# @brief AES-128 key for Elden Ring Nightreign.
# @details From `alfizari/Elden-Ring-Nightreign-Save-Editor` (MIT), where it is
# misleadingly named `DS2_KEY` — it is not Dark Souls II's, which is `DS2_KEY` above
# and a different sixteen bytes. It does not need to be taken on trust: every
# Nightreign entry stores an MD5 of its own plaintext, and with this key all fourteen
# entries of the test save hash to the value they carry. A wrong key cannot do that.
NR_KEY = bytes.fromhex("18F6326605BD178A5524523AC0A0C609")
