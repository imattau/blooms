# Blooms in Gnome

Mount your Nostr Blossom servers as a FUSE directory with a system tray icon.
Works in **any** file manager (GNOME Files, COSMIC Files, Dolphin, Thunar, etc.).

## Features

- **FUSE mount** — Browse, read, write, and delete Blossom blobs like local files
- **System tray icon** — Status, upload, config, and quick folder access
- **NIP-44 encryption** — ECDH key derivation + ChaCha20-Poly1305 via your Nostr key
- **Erasure sharding** — Files split across servers with Reed-Solomon parity for resilience
- **Fastest-read** — Downloads fetch from all servers in parallel, first response wins
- **Auto-discovery** — Fetches your `kind:10063` User Server List from Nostr relays
- **16 languages** — Arabic, Bengali, Chinese (Simplified/Traditional), French, German, Hindi, Italian, Japanese, Korean, Polish, Portuguese, Russian, Spanish, Turkish, Vietnamese
- **Cross-desktop keyring** — nsec stored via libsecret (GNOME/KDE/macOS)
- **Autostart** — Desktop file installed to `~/.config/autostart/`, tray starts on login

## Quickstart

```bash
# Install the package
pip install --break-system-packages .

# Set your Nostr keys
blooms-mount --set-nsec nsec1...
blooms-mount --set-npub <hex>

# Start the tray icon (auto-mounts + sits in panel)
blooms-tray
```

Files appear at `~/Blossom/`.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  File Manager (Nautilus / COSMIC / Dolphin)     │
└──────────────────┬──────────────────────────────┘
                   │ ~/Blossom/
┌──────────────────▼──────────────────────────────┐
│  FUSE (fusepy)              BloomsFS            │
│  - readdir / getattr / open / read / write      │
│  - _upload (sharded + encrypted)                │
│  - open (fastest-read + decrypt)                │
└──────┬──────────────────────┬───────────────────┘
       │                      │
┌──────▼──────────┐  ┌───────▼───────────────────┐
│  Crypto (NIP-44) │  │  BlossomClient            │
│  - ECDH HKDF     │  │  - upload_sharded         │
│  - ChaCha20      │  │  - download_fastest       │
│  - Poly1305      │  │  - upload_all / delete_all│
└──────────────────┘  └───────┬───────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Server 0         Server 1         Server 2
      ┌──────────┐   ┌──────────┐    ┌──────────┐
      │ chunk_0  │   │ chunk_1  │    │ chunk_2  │
      │ chunk_3  │   │ manifest │    │ parity_3 │
      └──────────┘   └──────────┘    └──────────┘
```

### Sharding (k=3 servers, m=1 parity)

```
plaintext → encrypt(NIP-44) → ciphertext
ciphertext → shard_encode(k=3, m=1) → [chunk₀, chunk₁, chunk₂, parity₃]
chunk₀ → server₀   chunk₁ → server₁   chunk₂ → server₂   parity₃ → server₀
manifest → server₀, server₁, server₂  (replicated)
```

Read: fetch manifest from fastest server → fetch all 4 chunks in parallel →
if any missing, reconstruct via Reed-Solomon → reassemble → decrypt.

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

| State | Visual | Status text |
|---|---|---|
| Connected | Pink blossom (filled) | `3/3 servers healthy — 12 blobs` |
| Disconnected | Grey blossom | `Disconnected` |
| Uploading | Pulsing (500ms toggle) | `Uploading…` |
| Not configured | Grey blossom | `Not configured` |

Status refreshes every 5 seconds. Uploads pulse for 3 seconds after completion.

## Dependencies

| Package | Purpose |
|---|---|
| `PyGObject` | GTK file chooser, libsecret keyring |
| `requests` | HTTP client |
| `cryptography` | ChaCha20-Poly1305, HKDF |
| `coincurve` | secp256k1 ECDH, Schnorr signing (BUD-11 auth) |
| `fusepy` | FUSE filesystem bindings |
| `pystray` | System tray icon (StatusNotifierItem) |
| `cairosvg` | SVG → PNG icon rendering |
| `Pillow` | Fallback icon generation |
| `keyring` | Cross-desktop keyring storage |
| `websocket-client` | Nostr relay queries (kind:10063) |
| `reedsolo` | Reed-Solomon erasure coding |

## Config

`~/.config/blooms/config.json` — stores npub, relays, and servers.
nsec stored in desktop keyring only (via `keyring` / Secret Service).

### Default Blossom servers

- `https://cdn.satellite.earth`
- `https://blossom.nostr.wine`

### Default Nostr relays

- `wss://relay.damus.io`
- `wss://nos.lol`
- `wss://relay.nostr.band`

On save, queries relays for your `kind:10063` event and merges discovered servers.

## Internationalization

User-facing strings are wrapped with `gettext` via `blooms_in_gnome/i18n.py`.
Locale determined by `BLOOMS_LANG` env var (falls back to `LANG`).

**Available languages (16):** Arabic, Bengali, Chinese (Simplified), Chinese (Traditional), French, German, Hindi, Italian, Japanese, Korean, Polish, Portuguese (Brazil), Russian, Spanish, Turkish, Vietnamese.

```bash
make init LANG=de     # create de.po from template
# edit locale/de/LC_MESSAGES/blooms-in-gnome.po
make compile           # .po → .mo
make install-locale    # copy to ~/.local/share/locale/
BLOOMS_LANG=de blooms-tray
```

## Building packages

GitHub Actions builds `.deb`, `.rpm`, and `.flatpak` on tag pushes (`v*`):

```bash
git tag v0.1.0
git push origin v0.1.0
```

Artifacts are uploaded to the Actions run summary.

### Manual deb build

```bash
sudo apt install build-essential debhelper python3-all python3-setuptools
dpkg-buildpackage -us -uc -b
```

### Manual rpm build

```bash
dnf install rpm-build python3-devel
rpmbuild -ba blooms.spec
```

### Manual flatpak build

```bash
flatpak-builder --force-clean build-dir flatpak/io.github.anomalyco.blooms.yml
flatpak build-export repo build-dir
flatpak build-bundle repo blooms-in-gnome.flatpak io.github.anomalyco.blooms
```

## Project structure

```
blooms/
├── blooms_in_gnome/
│   ├── __main__.py      CLI entry point (blooms-mount, blooms-tray)
│   ├── client.py         Blossom HTTP client + sharded upload/download
│   ├── config.py         JSON config + keyring backend
│   ├── crypto.py         NIP-44 encrypt/decrypt
│   ├── fuse_fs.py        FUSE filesystem (BlossomFS)
│   ├── i18n.py           gettext setup
│   ├── relays.py         Kind:10063 relay fetcher
│   ├── shard.py          Reed-Solomon erasure coding
│   └── tray.py           pystray system tray icon
├── locale/               Translations (16 languages)
├── flatpak/              Flatpak manifest
├── debian/               Debian packaging
├── .github/workflows/    CI pipeline (deb + rpm + flatpak)
├── blooms.spec           RPM spec
├── blooms.service        systemd user unit
├── blooms-in-gnome.desktop  Autostart entry
├── Makefile              i18n helpers
├── setup.py              Python package
└── install.sh            Manual install script
```

## How it works

1. **Mount**: `blooms-tray` starts FUSE at `~/Blossom/`
2. **Listing**: `GET /list/<pubkey>` from all configured servers, merged
3. **Read**: Download manifest → fetch shards in parallel → reconstruct → decrypt
4. **Write**: Encrypt → Reed-Solomon shard → upload chunks to assigned servers → replicate manifest
5. **Delete**: Delete all shards + manifest from every server
6. **Discovery**: On config save, queries Nostr relays for `kind:10063` to find your servers
7. **Auth**: BUD-11 signed `kind:24242` tokens for every upload/delete/list operation

## Security

- nsec stored in desktop keyring (GNOME Keyring / KDE KWallet / macOS Keychain)
- Encryption key derived from Nostr keypair via NIP-44 ECDH
- No plaintext data touches the server
- BUD-11 tokens are short-lived (1 hour) and scoped to specific operations

## License

Unlicense — public domain.
