import hashlib
import json
import os
import ssl
import time

import coincurve

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]

DEFAULT_SERVERS = [
    "https://cdn.satellite.earth",
    "https://blossom.nostr.wine",
]


def _verify_event(event: dict, expected_pubkey: str) -> bool:
    required = ("pubkey", "created_at", "kind", "tags", "content", "id", "sig")
    if not all(k in event for k in required):
        return False
    if event["pubkey"] != expected_pubkey:
        return False

    computed_id = hashlib.sha256(
        json.dumps(
            [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    if computed_id != event.get("id"):
        return False

    try:
        sig_bytes = bytes.fromhex(event["sig"])
        id_bytes = bytes.fromhex(event["id"])
        pubkey_bytes = bytes.fromhex(event["pubkey"])
        pk = coincurve.PublicKeyXOnly(pubkey_bytes)
        return pk.verify(sig_bytes, id_bytes)
    except Exception:
        return False


def _query_relay(url: str, pubkey_hex: str) -> list[str]:
    import websocket

    sslopt = None
    if url.startswith("wss://"):
        sslopt = {
            "cert_reqs": ssl.CERT_REQUIRED,
            "check_hostname": True,
        }
    elif url.startswith("ws://"):
        pass

    ws = websocket.create_connection(url, timeout=10, sslopt=sslopt)

    sub_id = "blooms"
    req = json.dumps(["REQ", sub_id, {
        "kinds": [10063],
        "authors": [pubkey_hex],
        "limit": 1,
    }])
    ws.send(req)

    servers: list[str] = []
    deadline = time.time() + 8

    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception:
            break

        if not raw:
            break

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if not isinstance(msg, list) or len(msg) < 2:
            continue

        msg_type = msg[0]

        if msg_type == "EVENT":
            event = msg[2]
            if not _verify_event(event, pubkey_hex):
                continue
            for tag in event.get("tags", []):
                if len(tag) >= 2 and tag[0] == "server":
                    servers.append(tag[1])
        elif msg_type == "EOSE":
            break

    ws.send(json.dumps(["CLOSE", sub_id]))
    ws.close()
    return servers


def fetch_server_list(pubkey_hex: str, relay_urls: list[str]) -> list[str]:
    servers: set[str] = set()
    for url in relay_urls:
        try:
            result = _query_relay(url, pubkey_hex)
            servers.update(result)
        except Exception:
            pass
    return sorted(servers)
