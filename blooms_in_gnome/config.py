import json
import os
import sys
from pathlib import Path

try:
    import keyring as _kr
    _HAS_KEYRING = True
except ImportError:
    _HAS_KEYRING = False
    print("warning: keyring not installed; nsec will not persist across restarts", file=sys.stderr)

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
        val = _kr.get_password(KEYRING_SERVICE, "nsec")
        return val or ""
    except Exception:
        return ""


def _save_nsec(nsec: str):
    if not _HAS_KEYRING:
        return
    try:
        if nsec:
            _kr.set_password(KEYRING_SERVICE, "nsec", nsec)
        else:
            try:
                _kr.delete_password(KEYRING_SERVICE, "nsec")
            except Exception:
                pass
    except Exception:
        pass


def _read_config_raw() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        fd = os.open(str(CONFIG_PATH), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_config_raw(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(CONFIG_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)


def load() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["nsec"] = _load_nsec()

    data = _read_config_raw()
    if not data:
        return cfg

    cfg["npub"] = data.get("npub") or ""
    cfg["relays"] = data.get("relays") or list(DEFAULT_RELAYS)
    cfg["servers"] = data.get("servers") or list(DEFAULT_SERVERS)

    old_nsec = data.get("nsec", "")
    if old_nsec and not cfg["nsec"]:
        _save_nsec(old_nsec)
        cfg["nsec"] = old_nsec
        data.pop("nsec", None)
        _write_config_raw(data)

    return cfg


def save(config: dict):
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

    _write_config_raw(config)


def _migrate_remove_nsec():
    data = _read_config_raw()
    if data and "nsec" in data:
        data.pop("nsec", None)
        _write_config_raw(data)
