import hashlib
import json

import reedsolo

MANIFEST_VERSION = 1

SERVER_TAG = "blooms-shard-v1"


MAX_SERVERS = 20


def calc_k_m(num_servers: int) -> tuple[int, int]:
    if num_servers <= 1:
        return 1, 0
    if num_servers > MAX_SERVERS:
        num_servers = MAX_SERVERS
    k = num_servers
    m = max(1, num_servers // 2)
    if m > 128:
        m = 128
    return k, m


def shard_encode(data: bytes, k: int, m: int) -> list[bytes]:
    if k == 1 and m == 0:
        return [data]

    chunk_size = (len(data) + k - 1) // k
    padded = data.ljust(chunk_size * k, b"\x00")

    data_chunks = [padded[i * chunk_size : (i + 1) * chunk_size] for i in range(k)]

    rs = reedsolo.RSCodec(m)
    parity_chunks: list[bytearray] = [bytearray(chunk_size) for _ in range(m)]

    for i in range(chunk_size):
        dbytes = bytes(data_chunks[j][i] for j in range(k))
        encoded = rs.encode(dbytes)
        for j in range(m):
            parity_chunks[j][i] = encoded[k + j]

    return [bytes(dc) for dc in data_chunks] + [bytes(pc) for pc in parity_chunks]


def shard_decode(chunks: list[bytes | None], k: int, m: int, original_size: int) -> bytes:
    if k == 1 and m == 0:
        assert chunks[0] is not None
        return chunks[0][:original_size]

    non_none = [c for c in chunks if c is not None]
    if not non_none:
        raise RuntimeError("All shards are missing")
    chunk_size = len(non_none[0])

    rs = reedsolo.RSCodec(m)
    result = bytearray(chunk_size * k)
    n = k + m

    for i in range(chunk_size):
        erase_pos = [j for j in range(n) if chunks[j] is None]
        dlist: list[int] = []
        for j in range(n):
            c = chunks[j]
            dlist.append(c[i] if c is not None else 0)
        dbytes = bytes(dlist)
        if erase_pos:
            repaired, _, _ = rs.decode(dbytes, erase_pos=erase_pos, only_erasures=True)
        else:
            repaired, _, _ = rs.decode(dbytes)
        for j in range(k):
            result[j * chunk_size + i] = repaired[j]

    return bytes(result[:original_size])


def build_manifest(
    original_sha256: str,
    k: int,
    m: int,
    original_size: int,
    original_type: str,
    chunk_hashes: list[str],
    chunk_sizes: list[int],
    server_assignments: list[int],
) -> bytes:
    manifest = {
        "v": MANIFEST_VERSION,
        "k": k,
        "m": m,
        "os": original_size,
        "oh": original_sha256,
        "ot": original_type,
        "ch": chunk_hashes,
        "cs": chunk_sizes,
        "sa": server_assignments,
    }
    return json.dumps(manifest, separators=(",", ":")).encode()


def parse_manifest(data: bytes) -> dict:
    return json.loads(data.decode())


def shard_and_upload(
    ciphertext: bytes,
    original_type: str,
    servers: list[str],
    upload_fn: callable,
) -> tuple[str, bytes, list[str]]:
    k, m = calc_k_m(len(servers))
    all_chunks = shard_encode(ciphertext, k, m)
    n = k + m

    chunk_hashes: list[str] = []
    chunk_sizes: list[int] = []
    server_assignments: list[int] = []

    upload_results: list[str] = []

    for i, chunk in enumerate(all_chunks):
        server_idx = i % len(servers)
        server_assignments.append(server_idx)

        sha = hashlib.sha256(chunk).hexdigest()
        chunk_hashes.append(sha)
        chunk_sizes.append(len(chunk))

        try:
            upload_fn(servers[server_idx], chunk)
            upload_results.append(sha)
        except Exception:
            pass

    original_sha256 = hashlib.sha256(ciphertext).hexdigest()

    manifest_bytes = build_manifest(
        original_sha256=original_sha256,
        k=k,
        m=m,
        original_size=len(ciphertext),
        original_type=original_type,
        chunk_hashes=chunk_hashes,
        chunk_sizes=chunk_sizes,
        server_assignments=server_assignments,
    )

    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    for url in servers:
        try:
            upload_fn(url, manifest_bytes)
        except Exception:
            pass

    return manifest_sha256, manifest_bytes, upload_results


def fetch_and_reconstruct(
    manifest_data: bytes,
    download_fn: callable,
) -> bytes:
    manifest = parse_manifest(manifest_data)
    k = manifest["k"]
    m = manifest["m"]
    original_size = manifest["os"]
    chunk_hashes: list[str] = manifest["ch"]
    server_assignments: list[int] = manifest["sa"]
    n = k + m

    from concurrent.futures import ThreadPoolExecutor, as_completed

    chunks: dict[int, bytes] = {}

    def _get(idx: int, server_idx: int, sha: str) -> tuple[int, bytes | None]:
        try:
            data = download_fn(server_idx, sha)
            if hashlib.sha256(data).hexdigest() == sha:
                return idx, data
        except Exception:
            pass
        return idx, None

    with ThreadPoolExecutor(max_workers=n) as pool:
        fut_map = {
            pool.submit(_get, i, server_assignments[i], chunk_hashes[i]): i
            for i in range(n)
        }
        for fut in as_completed(fut_map):
            idx, data = fut.result()
            if data is not None:
                chunks[idx] = data

    missing = [i for i in range(n) if chunks.get(i) is None]

    if k == 1 and m == 0:
        return chunks[0][:original_size]

    if missing:
        if len(missing) > m:
            raise RuntimeError(
                f"Cannot reconstruct: {len(missing)} shards missing, "
                f"parity can recover at most {m}"
            )
        needed_k = [chunks[j] for j in range(k) if chunks[j] is not None]
        needed_missing = [j for j in range(k) if chunks[j] is None]
        while len(needed_k) < k and chunks.get(k + len(needed_k)) is not None:
            parity_idx = k + len(needed_k)
            if parity_idx < len(chunks) and chunks[parity_idx] is not None:
                needed_k.append(chunks[parity_idx])

    ordered = [chunks[i] for i in range(n)]
    present = [c for c in ordered if c is not None]

    if len(present) < k:
        raise RuntimeError(
            f"Only {len(present)}/{k} shards available for reconstruction"
        )

    return shard_decode(ordered, k, m, original_size)
