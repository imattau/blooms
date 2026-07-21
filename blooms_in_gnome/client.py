import hashlib
import json
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

import coincurve
import requests

from .shard import calc_k_m, shard_encode, shard_decode, build_manifest, parse_manifest


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


def _put_blob(server_url: str, data: bytes, private_key_hex: str | None) -> dict:
    sha256 = hashlib.sha256(data).hexdigest()
    token = _create_auth_token(private_key_hex, "upload", sha256=sha256)
    headers = {
        "Authorization": f"Nostr {token}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(data)),
        "X-SHA-256": sha256,
    }
    r = requests.put(f"{server_url}/upload", data=data, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_blob(server_url: str, sha256: str) -> bytes:
    r = requests.get(f"{server_url}/{sha256}", timeout=30)
    r.raise_for_status()
    return r.content


class BlossomClient:
    def __init__(self, server_url: str | None = None, private_key_hex: str | None = None):
        self.server_url = server_url.rstrip("/") if server_url else ""
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

    def upload_all(self, servers: list[str], file_bytes: bytes,
                   content_type: str = "application/octet-stream"
                   ) -> tuple[dict[str, dict], dict[str, Exception]]:
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        results: dict[str, dict] = {}
        errors: dict[str, Exception] = {}

        def _do(url: str) -> tuple[str, dict]:
            token = _create_auth_token(self.private_key_hex, "upload", sha256=sha256)
            headers = {
                "Authorization": f"Nostr {token}",
                "Content-Type": content_type,
                "Content-Length": str(len(file_bytes)),
                "X-SHA-256": sha256,
            }
            r = requests.put(f"{url}/upload", data=file_bytes, headers=headers, timeout=30)
            r.raise_for_status()
            return url, r.json()

        with ThreadPoolExecutor(max_workers=len(servers)) as pool:
            fut_map = {pool.submit(_do, s): s for s in servers}
            for fut in as_completed(fut_map):
                url = fut_map[fut]
                try:
                    u, desc = fut.result()
                    results[u] = desc
                except Exception as e:
                    errors[url] = e

        return results, errors

    def upload_sharded(self, servers: list[str], data: bytes,
                       content_type: str = "application/octet-stream"
                       ) -> tuple[str, int, int, dict[str, Exception]]:
        if not servers:
            return "", 0, 0, {"general": Exception("no servers")}
        k, m = calc_k_m(len(servers))
        all_chunks = shard_encode(data, k, m)
        n = k + m

        chunk_hashes: list[str] = []
        chunk_sizes: list[int] = []
        chunk_servers: list[int] = []
        upload_errors: dict[str, Exception] = {}

        def _upload_chunk(args: tuple[int, bytes, str]) -> tuple[int, str]:
            idx, chunk, url = args
            try:
                _put_blob(url, chunk, self.private_key_hex)
                return idx, hashlib.sha256(chunk).hexdigest()
            except Exception as e:
                upload_errors[f"chunk_{idx}@{url}"] = e
                return idx, ""

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = []
            for i, chunk in enumerate(all_chunks):
                url = servers[i % len(servers)]
                chunk_servers.append(i % len(servers))
                chunk_sizes.append(len(chunk))
                futures.append(pool.submit(_upload_chunk, (i, chunk, url)))

            for fut in as_completed(futures):
                idx, sha = fut.result()
                chunk_hashes.append(sha) if sha else chunk_hashes.append("")

        original_sha256 = hashlib.sha256(data).hexdigest()

        manifest_bytes = build_manifest(
            original_sha256=original_sha256,
            k=k, m=m,
            original_size=len(data),
            original_type=content_type,
            chunk_hashes=chunk_hashes,
            chunk_sizes=chunk_sizes,
            server_assignments=chunk_servers,
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        def _put_manifest(url: str) -> tuple[str, bool]:
            try:
                _put_blob(url, manifest_bytes, self.private_key_hex)
                return url, True
            except Exception as e:
                upload_errors[f"manifest@{url}"] = e
                return url, False

        with ThreadPoolExecutor(max_workers=len(servers)) as pool:
            mfuts = {pool.submit(_put_manifest, s): s for s in servers}
            for fut in as_completed(mfuts):
                fut.result()

        return manifest_sha256, k, m, upload_errors

    def download_sharded(self, servers: list[str], manifest_sha256: str) -> bytes:
        if not servers:
            raise RuntimeError("no servers configured")
        manifest_raw = _get_blob(servers[0], manifest_sha256)
        manifest = parse_manifest(manifest_raw)
        k = manifest["k"]
        m = manifest["m"]
        original_size = manifest["os"]
        chunk_hashes: list[str] = manifest["ch"]
        server_assignments: list[int] = manifest["sa"]
        n = k + m
        len_present = len(chunk_hashes)

        chunks: dict[int, bytes] = {}

        def _get(idx: int) -> tuple[int, bytes | None]:
            si = server_assignments[idx] if idx < len(server_assignments) else idx % len(servers)
            url = servers[si] if si < len(servers) else servers[0]
            sha = chunk_hashes[idx] if idx < len(chunk_hashes) else ""
            if not sha:
                return idx, None
            try:
                data = _get_blob(url, sha)
                if hashlib.sha256(data).hexdigest() == sha:
                    return idx, data
            except Exception:
                pass
            return idx, None

        with ThreadPoolExecutor(max_workers=n) as pool:
            fut_map = {pool.submit(_get, i): i for i in range(n)}
            for fut in as_completed(fut_map):
                idx, data = fut.result()
                if data is not None:
                    chunks[idx] = data

        ordered: list[bytes | None] = [chunks.get(i) for i in range(n)]
        present = [c for c in ordered if c is not None]

        if len(present) < k:
            msg = f"Cannot reconstruct: {len(present)}/{k} shards available"
            raise RuntimeError(msg)

        return shard_decode(ordered, k, m, original_size)

    def download(self, sha256: str) -> bytes:
        resp = requests.get(f"{self.server_url}/{sha256}")
        resp.raise_for_status()
        return resp.content

    def download_fastest(self, servers: list[str], sha256: str) -> bytes:
        def _do(url: str) -> bytes:
            r = requests.get(f"{url}/{sha256}", timeout=30)
            r.raise_for_status()
            return r.content

        with ThreadPoolExecutor(max_workers=len(servers)) as pool:
            fut_map = {pool.submit(_do, s): s for s in servers}
            for fut in as_completed(fut_map):
                try:
                    return fut.result()
                except Exception:
                    continue

        raise RuntimeError(f"All {len(servers)} servers failed for {sha256}")

    def delete(self, sha256: str) -> bool:
        token = _create_auth_token(self.private_key_hex, "delete", sha256=sha256)
        if not token:
            raise ValueError("Private key required for delete")
        resp = requests.delete(
            f"{self.server_url}/{sha256}",
            headers={"Authorization": f"Nostr {token}"},
        )
        return resp.status_code == 200

    def delete_all(self, servers: list[str], sha256: str) -> tuple[list[str], list[str]]:
        success: list[str] = []
        failed: list[str] = []

        def _do(url: str) -> bool:
            token = _create_auth_token(self.private_key_hex, "delete", sha256=sha256)
            if not token:
                return False
            r = requests.delete(f"{url}/{sha256}",
                                headers={"Authorization": f"Nostr {token}"},
                                timeout=30)
            return r.status_code == 200

        with ThreadPoolExecutor(max_workers=len(servers)) as pool:
            fut_map = {pool.submit(_do, s): s for s in servers}
            for fut in as_completed(fut_map):
                url = fut_map[fut]
                try:
                    if fut.result():
                        success.append(url)
                    else:
                        failed.append(url)
                except Exception:
                    failed.append(url)

        return success, failed

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
