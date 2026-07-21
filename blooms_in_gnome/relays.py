import json
import time

from . import config as cfg

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]

DEFAULT_SERVERS = [
    "https://cdn.satellite.earth",
    "https://blossom.nostr.wine",
]


def fetch_server_list(pubkey_hex: str, relay_urls: list[str]) -> list[str]:
    servers: set[str] = set()
    for url in relay_urls:
        try:
            result = _query_relay(url, pubkey_hex)
            servers.update(result)
        except Exception:
            pass
    return sorted(servers)


def _query_relay(url: str, pubkey_hex: str) -> list[str]:
    import websocket

    ws = websocket.create_connection(url, timeout=10)

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
            for tag in event.get("tags", []):
                if len(tag) >= 2 and tag[0] == "server":
                    servers.append(tag[1])
            # Keep receiving until EOSE
        elif msg_type == "EOSE":
            break

    ws.send(json.dumps(["CLOSE", sub_id]))
    ws.close()
    return servers
