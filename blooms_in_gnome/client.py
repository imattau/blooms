import hashlib
import json
import time
import base64

import coincurve
import requests


def _create_auth_token(
    private_key_hex: str | None, action: str, sha256: str | None = None, expiry: int = 3600
) -> str | None:
    if not private_key_hex:
        return None
    sk = coincurve.PrivateKey.from_hex(private_key_hex)
    pubkey_hex = sk.public_key.format()[1:].hex()
    created_at = int(time.time())
    expires_at = created_at + expiry

    tags = [
        ["t", action],
        ["expiration", str(expires_at)],
    ]
    if sha256:
        tags.append(["x", sha256])

    serialized = json.dumps(
        [0, pubkey_hex, created_at, 24242, tags, ""], separators=(",", ":")
    )
    event_id = hashlib.sha256(serialized.encode()).hexdigest()

    sig = sk.sign_schnorr(bytes.fromhex(event_id))

    event = {
        "id": event_id,
        "kind": 24242,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "tags": tags,
        "content": "",
        "sig": sig.hex(),
    }

    token = base64.urlsafe_b64encode(json.dumps(event).encode()).rstrip(b"=").decode()
    return token


class BlossomClient:
    def __init__(self, server_url: str, private_key_hex: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.private_key_hex = private_key_hex

    def upload(self, file_bytes: bytes, content_type: str = "application/octet-stream") -> dict:
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        token = _create_auth_token(self.private_key_hex, "upload", sha256=sha256)
        if not token:
            raise ValueError("Private key required for upload")

        headers = {
            "Authorization": f"Nostr {token}",
            "Content-Type": content_type,
            "Content-Length": str(len(file_bytes)),
            "X-SHA-256": sha256,
        }

        resp = requests.put(f"{self.server_url}/upload", data=file_bytes, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def download(self, sha256: str) -> bytes:
        resp = requests.get(f"{self.server_url}/{sha256}")
        resp.raise_for_status()
        return resp.content

    def delete(self, sha256: str) -> bool:
        token = _create_auth_token(self.private_key_hex, "delete", sha256=sha256)
        if not token:
            raise ValueError("Private key required for delete")
        resp = requests.delete(
            f"{self.server_url}/{sha256}",
            headers={"Authorization": f"Nostr {token}"},
        )
        return resp.status_code == 200

    def list_blobs(self, pubkey_hex: str | None = None) -> list:
        if self.private_key_hex:
            sk = coincurve.PrivateKey.from_hex(self.private_key_hex)
            pk = pubkey_hex or sk.public_key.format()[1:].hex()
        else:
            pk = pubkey_hex or ""

        token = _create_auth_token(self.private_key_hex, "list")
        headers = {}
        if token:
            headers["Authorization"] = f"Nostr {token}"
        resp = requests.get(
            f"{self.server_url}/list/{pk}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()
