import json
from pathlib import Path

try:
    import keyring
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False

CONFIG_DIR = Path.home() / ".config" / "blooms"
CONFIG_PATH = CONFIG_DIR / "config.json"
KEYRING_SERVICE = "blooms-in-gnome"

from .relays import DEFAULT_RELAYS, DEFAULT_SERVERS, fetch_server_list

DEFAULT_CONFIG = {
    "npub": "",
    "relays": list(DEFAULT_RELAYS),
    "servers": list(DEFAULT_SERVERS),
}


def _load_nsec() -> str:
    if not _HAS_KEYRING:
        return ""
    try:
        val = keyring.get_password(KEYRING_SERVICE, "nsec")
        return val or ""
    except Exception:
        return ""


def _save_nsec(nsec: str):
    if not _HAS_KEYRING:
        return
    try:
        if nsec:
            keyring.set_password(KEYRING_SERVICE, "nsec", nsec)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, "nsec")
            except Exception:
                pass
    except Exception:
        pass


def load() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["nsec"] = _load_nsec()

    if not CONFIG_PATH.exists():
        return cfg

    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        cfg["npub"] = data.get("npub") or ""
        cfg["relays"] = data.get("relays") or list(DEFAULT_RELAYS)
        cfg["servers"] = data.get("servers") or list(DEFAULT_SERVERS)

        old_nsec = data.get("nsec", "")
        if old_nsec and not cfg["nsec"]:
            _save_nsec(old_nsec)
            cfg["nsec"] = old_nsec
            _migrate_remove_nsec()
    except (json.JSONDecodeError, OSError):
        pass

    return cfg


def save(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    nsec = config.pop("nsec", "")
    _save_nsec(nsec)

    npub = config.get("npub", "")
    relays = config.get("relays", list(DEFAULT_RELAYS))
    servers = config.get("servers", list(DEFAULT_SERVERS))

    if npub and relays:
        try:
            fetched = fetch_server_list(npub, relays)
            merged = list(dict.fromkeys(fetched + servers))
            config["servers"] = merged
        except Exception:
            pass

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def _migrate_remove_nsec():
    try:
        if not CONFIG_PATH.exists():
            return
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        data.pop("nsec", None)
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
