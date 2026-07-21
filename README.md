# Blooms in Gnome

Mount your Nostr Blossom server as a FUSE directory with a system tray icon.
Works in **any** file manager (GNOME Files, COSMIC Files, Dolphin, Thunar, etc.).

Encryption uses NIP-44 key derivation (ECDH + HKDF) + ChaCha20-Poly1305.
Auth uses BUD-11 signed tokens. nsec stored in desktop keyring (GNOME, KDE, macOS, etc.).

## Quickstart

```bash
pip install --break-system-packages .
mkdir -p ~/.local/bin
cp blooms_in_gnome/mount.sh ~/.local/bin/blooms-mount
chmod +x ~/.local/bin/blooms-mount

# Set your keys
blooms-mount --set-nsec nsec1...
blooms-mount --set-npub <hex>

# Start tray icon (auto-mounts + sits in panel)
blooms-tray
```

Files appear at `~/Blossom/`.

## Commands

| Command | Description |
|---|---|
| `blooms-tray` | Start tray icon with FUSE mount |
| `blooms-mount --foreground &` | FUSE mount only (no tray) |
| `blooms-mount --config` | Show configuration |
| `blooms-mount --set-nsec <nsec>` | Store nsec in desktop keyring |
| `blooms-mount --set-npub <hex>` | Set public key |
| `blooms-mount --add-server <url>` | Add a Blossom server |
| `blooms-mount --add-relay <wss://...>` | Add a Nostr relay |

## Tray icon

- **Connected**: Pink blossom (filled)
- **Disconnected**: Grey blossom
- **Uploading**: Pulsing animation for 3s after upload
- **Menu**: Open Folder, Upload File, Status, Config, Quit

Status refreshes every 5 seconds (blob count + connection).

## Autostart

Installed to `~/.config/autostart/blooms-in-gnome.desktop`.
The tray icon starts automatically on next login.

## Defaults

**Blossom servers** (auto-fetched from relays + fallback):
- `https://cdn.satellite.earth`
- `https://blossom.nostr.wine`

**Nostr relays** (for discovering your kind:10063 server list):
- `wss://relay.damus.io`
- `wss://nos.lol`
- `wss://relay.nostr.band`

On save, queries relays for your kind:10063 event and merges discovered servers.

## Config

`~/.config/blooms/config.json` — stores npub, relays, and servers.
nsec stored in desktop keyring only.

## Internationalization

User-facing strings are wrapped with `gettext` via `blooms_in_gnome/i18n.py`.
The locale is determined by `BLOOMS_LANG` env var (falls back to `LANG`).

**Translations** live in `locale/<lang>/LC_MESSAGES/blooms-in-gnome.po`.

**Available languages**: Arabic, Bengali, Chinese (Simplified), Chinese (Traditional), French, German, Hindi, Italian, Japanese, Korean, Polish, Portuguese (Brazil), Russian, Spanish, Turkish, Vietnamese.

Add or update a language:
```bash
make init LANG=de   # create de.po from template
# edit locale/de/LC_MESSAGES/blooms-in-gnome.po
make compile         # compile all .po → .mo
make install-locale  # copy to ~/.local/share/locale/
```

Set language:
```bash
BLOOMS_LANG=de blooms-tray
```

## How it works

- **Mount**: FUSE filesystem at `~/Blossom/`
- **Listing**: `GET /list/<pubkey>` from your configured server
- **Read**: `GET /<sha256>` → decrypt on the fly via NIP-44
- **Write**: Encrypt → `PUT /upload` → file appears by friendly name
- **Discovery**: Queries Nostr relays for kind:10063 to auto-find servers
