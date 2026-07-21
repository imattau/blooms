import argparse
import os
import sys

from . import config as cfg
from .fuse_fs import mount
from .i18n import _


def _cmd_config():
    c = cfg.load()
    print(_("Current config:"))
    print(f"  npub:     {c.get('npub', '') or _('(not set)')}")
    print(f"  relays:   {c.get('relays', []) or _('(defaults)')}")
    print(f"  servers:  {c.get('servers', []) or _('(defaults)')}")
    print(f"  nsec:     {_('(stored in keyring)') if c.get('nsec') else _('(not set)')}")
    print()
    print(_("Config file:"))
    print(f"  {cfg.CONFIG_PATH}")
    print()
    print(_("CLI:"))
    print("  blooms-mount --set-nsec <nsec>")
    print("  blooms-mount --set-nsec-stdin    (read from stdin, no echo)")
    print("  blooms-mount --set-npub <hex>")
    print("  blooms-mount --add-server <url>")
    print("  blooms-mount --add-relay <wss://...>")


def _cmd_set_nsec(nsec: str):
    c = cfg.load()
    c["nsec"] = nsec
    cfg.save(c)
    print(_("nsec saved to keyring"))


def _cmd_set_npub(npub: str):
    c = cfg.load()
    c["npub"] = npub
    cfg.save(c)
    print(_("npub set to {npub}").format(npub=npub))


def _cmd_add_server(url: str):
    c = cfg.load()
    if url not in c.get("servers", []):
        c.setdefault("servers", []).append(url)
        cfg.save(c)
    print(_("server added: {url}").format(url=url))


def _cmd_add_relay(url: str):
    c = cfg.load()
    if url not in c.get("relays", []):
        c.setdefault("relays", []).append(url)
        cfg.save(c)
    print(_("relay added: {url}").format(url=url))


def main():
    parser = argparse.ArgumentParser(
        description=_("Blooms in Gnome \u2014 Blossom FUSE mount"),
    )
    parser.add_argument(
        "mount_point", nargs="?", default=None,
        help=_("Mount point (default: ~/Blossom)"),
    )
    parser.add_argument(
        "--config", action="store_true",
        help=_("Show current configuration"),
    )
    parser.add_argument(
        "--foreground", action="store_true",
        help=_("Run FUSE mount in foreground"),
    )
    parser.add_argument(
        "--tray", action="store_true",
        help=_("Start tray icon (starts FUSE mount automatically)"),
    )
    parser.add_argument("--set-nsec", metavar="NSEC", help=_("Store nsec in keyring"))
    parser.add_argument("--set-nsec-stdin", action="store_true",
                        help=_("Read nsec from stdin (no echo, safer than --set-nsec)"))
    parser.add_argument("--set-npub", metavar="HEX", help=_("Set public key"))
    parser.add_argument("--add-server", metavar="URL", help=_("Add a Blossom server"))
    parser.add_argument("--add-relay", metavar="URL", help=_("Add a Nostr relay"))

    args = parser.parse_args()

    if args.config:
        _cmd_config()
        return
    if args.set_nsec:
        _cmd_set_nsec(args.set_nsec)
        return
    if args.set_nsec_stdin:
        nsec = sys.stdin.readline().strip()
        _cmd_set_nsec(nsec)
        return
    if args.set_npub:
        _cmd_set_npub(args.set_npub)
        return
    if args.add_server:
        _cmd_add_server(args.add_server)
        return
    if args.add_relay:
        _cmd_add_relay(args.add_relay)
        return

    if args.tray:
        from .tray import BloomsTray
        tray = BloomsTray()
        tray.start_fuse()
        tray.run()
        return

    if args.mount_point:
        os.environ["BLOOMS_MOUNT"] = args.mount_point
    mount(foreground=args.foreground)


def tray_main():
    sys.argv = [sys.argv[0], "--tray"] + sys.argv[1:]
    main()
