import os
import hmac as hmac_lib
import coincurve
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

VERSION = b"\x02"
NONCE_LEN = 32
SALT = b"nip44-v2"


def get_conversation_key(private_key_hex: str, public_key_hex: str) -> bytes:
    pub_bytes = bytes.fromhex(public_key_hex)
    sk = coincurve.PrivateKey.from_hex(private_key_hex)
    compressed_pub = b"\x02" + pub_bytes
    pk = coincurve.PublicKey(compressed_pub)

    shared_x = sk.ecdh(pk.format())
    return hmac_lib.digest(SALT, shared_x, "sha256")


def get_message_keys(conversation_key: bytes, nonce: bytes):
    expander = HKDFExpand(
        algorithm=hashes.SHA256(),
        length=76,
        info=nonce,
    )
    keys = expander.derive(conversation_key)
    chacha_key = keys[0:32]
    chacha_nonce = keys[32:44]
    hmac_key = keys[44:76]
    return chacha_key, chacha_nonce, hmac_key


def encrypt(plaintext: bytes, conversation_key: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)

    chacha_key, chacha_nonce, _ = get_message_keys(conversation_key, nonce)

    aead = ChaCha20Poly1305(chacha_key)
    ciphertext = aead.encrypt(chacha_nonce, plaintext, None)

    return VERSION + nonce + ciphertext


def decrypt(payload: bytes, conversation_key: bytes) -> bytes:
    if payload[0:1] != VERSION:
        raise ValueError(f"Unknown encryption version: {payload[0]}")

    nonce = payload[1:33]
    ciphertext = payload[33:]

    chacha_key, chacha_nonce, _ = get_message_keys(conversation_key, nonce)

    aead = ChaCha20Poly1305(chacha_key)
    return aead.decrypt(chacha_nonce, ciphertext, None)
