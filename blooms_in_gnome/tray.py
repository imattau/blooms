import io
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .i18n import _

if TYPE_CHECKING:
    from PIL import Image

SVG_CONNECTED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs><radialGradient id="g" cx="50%" cy="50%" r="50%">
    <stop offset="0%" stop-color="#f48fb1"/>
    <stop offset="100%" stop-color="#e91e63"/>
  </radialGradient></defs>
  <circle cx="32" cy="32" r="30" fill="url(#g)"/>
  <path d="M32 8 Q40 22 32 32 Q24 22 32 8Z" fill="#fff" opacity=".9"/>
  <path d="M32 56 Q40 42 32 32 Q24 42 32 56Z" fill="#fff" opacity=".9"/>
  <path d="M8 32 Q22 24 32 32 Q22 40 8 32Z" fill="#fff" opacity=".9"/>
  <path d="M56 32 Q42 24 32 32 Q42 40 56 32Z" fill="#fff" opacity=".9"/>
  <circle cx="32" cy="32" r="8" fill="#c2185b"/>
</svg>"""

SVG_DISCONNECTED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="30" fill="#888" opacity=".3"/>
  <path d="M32 8 Q40 22 32 32 Q24 22 32 8Z" fill="#888" opacity=".6"/>
  <path d="M32 56 Q40 42 32 32 Q24 42 32 56Z" fill="#888" opacity=".6"/>
  <path d="M8 32 Q22 24 32 32 Q22 40 8 32Z" fill="#888" opacity=".6"/>
  <path d="M56 32 Q42 24 32 32 Q42 40 56 32Z" fill="#888" opacity=".6"/>
  <circle cx="32" cy="32" r="8" fill="#888" opacity=".6"/>
</svg>"""

try:
    import cairosvg
    _HAS_CAIRO = True
except Exception:
    _HAS_CAIRO = False


def _svg_to_pil(svg: str, size: int = 64):
    from PIL import Image
    if _HAS_CAIRO:
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
        return Image.open(io.BytesIO(png))
    return _fallback_icon(size)


def _fallback_icon(size: int = 64):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = size // 2 - 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(233, 30, 99, 200))
    sr = r // 3
    for dx, dy in [(0, -r), (0, r), (-r, 0), (r, 0)]:
        draw.ellipse([cx + dx - sr, cy + dy - sr, cx + dx + sr, cy + dy + sr],
                     fill=(255, 255, 255, 230))
    draw.ellipse([cx - sr, cy - sr, cx + sr, cy + sr], fill=(194, 24, 91))
    return img


def _icons(size: int = 48):
    return (
        _svg_to_pil(SVG_CONNECTED, size),
        _svg_to_pil(SVG_DISCONNECTED, size),
    )


class BloomsTray:
    def __init__(self):
        self._icon = None
        self._running = True
        self._connected = False
        self._blob_count = 0
        self._server_ok = 0
        self._server_total = 0
        self._last_upload = 0.0
        self._pulse_state = 0
        self._status_label = _("Starting\u2026")

        self._connected_icon, self._disconnected_icon = _icons()
        self._current_icon = self._disconnected_icon
        self._fuse_thread: threading.Thread | None = None

    def start_fuse(self):
        from .fuse_fs import mount
        self._fuse_thread = threading.Thread(target=mount, args=(True,), daemon=True)
        self._fuse_thread.start()

    def _update_status(self):
        from . import config as cfg
        from .client import BlossomClient

        c = cfg.load()
        servers = c.get("servers", [])

        if not servers or not c.get("npub"):
            self._connected = False
            self._blob_count = 0
            self._server_ok = 0
            self._server_total = 0
            self._status_label = _("Not configured")
            return

        healthy = 0
        blobs_merged: set[str] = set()
        nsec = c.get("nsec") or None
        npub = c["npub"]

        for url in servers:
            try:
                client = BlossomClient(url, nsec)
                result = client.list_blobs(npub)
                healthy += 1
                for b in result:
                    blobs_merged.add(b["sha256"])
            except Exception:
                pass

        self._server_ok = healthy
        self._server_total = len(servers)
        self._blob_count = len(blobs_merged)
        self._connected = healthy > 0

        if self._connected:
            self._status_label = _("{ok}/{total} servers healthy \u2014 {count} blobs").format(
                ok=healthy, total=len(servers), count=len(blobs_merged))
        else:
            self._status_label = _("Disconnected")

    def _build_menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem(_("Open Folder"), self._on_open, default=True),
            pystray.MenuItem(_("Upload File\u2026"), self._on_upload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._status_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_("Config"), self._on_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_("Quit"), self._on_quit),
        )

    def _on_open(self):
        mount = os.environ.get("BLOOMS_MOUNT", str(Path.home() / "Blossom"))
        subprocess.Popen(
            ["xdg-open", mount],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _on_upload(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        dialog = Gtk.FileChooserDialog(
            title=_("Select file to upload to Blossom"),
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Upload"), Gtk.ResponseType.ACCEPT)

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_file().get_path()
            dialog.destroy()
            threading.Thread(target=self._do_upload, args=(path,), daemon=True).start()
        else:
            dialog.destroy()

    def _do_upload(self, file_path: str):
        try:
            from . import config as cfg
            from .client import BlossomClient
            from .crypto import get_conversation_key, encrypt

            c = cfg.load()
            servers = c.get("servers", [])
            nsec = c.get("nsec")
            npub = c.get("npub")

            if not servers or not nsec or not npub:
                self._send_notify("Blooms", _("Configure keys and servers first"))
                return

            data = Path(file_path).read_bytes()
            conv = get_conversation_key(nsec, npub)
            encrypted = encrypt(data, conv)
            client = BlossomClient(servers[0], nsec)

            if len(servers) > 1:
                manifest_sha, k, m, errors = client.upload_sharded(servers, encrypted)
                self._last_upload = time.time()
                if errors:
                    self._send_notify("Blooms",
                        _("Uploaded: {hash}\u2026 (shard errors: {e})").format(
                            hash=manifest_sha[:16], e=", ".join(errors)[:60]))
                else:
                    self._send_notify("Blooms",
                        _("Uploaded: {hash}\u2026 (sharded {k}+{m})").format(
                            hash=manifest_sha[:16], k=k, m=m))
            else:
                results, errors = client.upload_all(servers, encrypted)
                if not results:
                    self._send_notify("Blooms", _("Upload failed: all servers unreachable"))
                    return
                first_url = next(iter(results))
                sha256 = results[first_url]["sha256"]
                self._last_upload = time.time()
                ok = len(results)
                total = len(servers)
                if errors:
                    self._send_notify("Blooms",
                        _("Uploaded: {hash}\u2026 ({ok}/{total} servers, errors: {failed})").format(
                            hash=sha256[:16], ok=ok, total=total, failed=", ".join(errors)))
                else:
                    self._send_notify("Blooms",
                        _("Uploaded: {hash}\u2026 ({ok}/{total} servers)").format(
                            hash=sha256[:16], ok=ok, total=total))
        except Exception as e:
            self._send_notify("Blooms", _("Upload failed: {error}").format(error=e))

    def _send_notify(self, title: str, msg: str):
        subprocess.Popen(
            ["notify-send", title, msg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _on_config(self):
        subprocess.Popen(
            ["blooms-mount", "--config"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _on_quit(self):
        self._running = False
        if self._fuse_thread and self._fuse_thread.is_alive():
            try:
                from fuse import fuse_exit
                fuse_exit()
            except Exception:
                pass
            self._fuse_thread.join(timeout=5)
        if self._icon:
            self._icon.stop()

    def _tick(self):
        if not self._running or not self._icon:
            return

        self._update_status()

        now = time.time()
        pulsing = (now - self._last_upload) < 3.0

        if pulsing:
            self._pulse_state ^= 1
            icon_img = self._connected_icon if self._pulse_state else self._disconnected_icon
        elif self._connected:
            icon_img = self._connected_icon
        else:
            icon_img = self._disconnected_icon

        self._icon.icon = icon_img
        self._icon.menu = self._build_menu()

        interval = 0.5 if pulsing else 5.0
        threading.Timer(interval, self._tick).start()

    def run(self):
        import pystray

        self._update_status()
        self._icon = pystray.Icon(
            "blooms",
            icon=self._connected_icon if self._connected else self._disconnected_icon,
            title=_("Blooms in Gnome"),
            menu=self._build_menu(),
        )
        self._tick()
        self._icon.run()
