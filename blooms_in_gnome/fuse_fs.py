import errno
import json
import os
import stat
import threading
import time
from pathlib import Path

from fuse import FUSE, FuseOSError, Operations

from . import config as cfg
from .client import BlossomClient
from .crypto import get_conversation_key, encrypt, decrypt
from .i18n import _

NAMES_PATH = cfg.CONFIG_DIR / "names.json"
MOUNT_ROOT = Path.home() / "Blossom"


def _load_names() -> dict:
    if NAMES_PATH.exists():
        try:
            return json.loads(NAMES_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_names(names: dict):
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(NAMES_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(names, f, indent=2)


class BlossomFS(Operations):
    def __init__(self):
        self.config = cfg.load()
        self._lock = threading.Lock()
        self._next_fd = 1

        self.servers = self.config.get("servers", [])
        self.nsec = self.config.get("nsec") or None
        self.npub = self.config.get("npub") or ""

        self.conversation_key = None
        if self.nsec and self.npub:
            self.conversation_key = get_conversation_key(self.nsec, self.npub)
            self.nsec = None

        self._server_health: dict[str, bool] = {}

        self.client = BlossomClient(self.servers[0] if self.servers else "", None)

        self.names = _load_names()
        self.blobs: dict[str, dict] = {}
        self._fetch_blobs()

        self.read_buffers: dict[int, bytes] = {}
        self.write_buffers: dict[int, bytearray] = {}
        self.write_paths: dict[int, str] = {}

    def _fetch_blobs(self):
        if not self.servers or not self.npub:
            return
        self._server_health = {}
        merged: dict[str, dict] = {}
        for url in self.servers:
            try:
                cl = BlossomClient(url, None)
                result = cl.list_blobs(self.npub)
                self._server_health[url] = True
                for b in result:
                    merged.setdefault(b["sha256"], b)
            except Exception:
                self._server_health[url] = False
        self.blobs = merged

    # -- helpers --

    def _sha256_to_name(self, sha256: str) -> str:
        blob = self.blobs.get(sha256, {})
        ext = Path(blob.get("url", "")).suffix
        return f"{sha256[:24]}{ext}"

    def _lookup(self, name: str) -> dict | None:
        if name in self.names:
            return self.names[name]
        for sha256, blob in self.blobs.items():
            if name == self._sha256_to_name(sha256):
                return blob
        return None

    def _all_entries(self) -> list[str]:
        entries = {".", "..", ".info"}
        for name in self.names:
            entries.add(name)
        named_sha256s = {v["sha256"] for v in self.names.values()}
        for sha256 in self.blobs:
            if sha256 not in named_sha256s:
                entries.add(self._sha256_to_name(sha256))
        return sorted(entries)

    def _server_health_summary(self) -> tuple[int, int]:
        total = len(self.servers)
        ok = sum(1 for v in self._server_health.values() if v)
        return ok, total

    def _make_attr(self, mode: int, size: int = 0, mtime: float = 0) -> dict:
        now = time.time()
        return {
            "st_mode": mode,
            "st_size": size,
            "st_ctime": mtime or now,
            "st_mtime": mtime or now,
            "st_atime": now,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
        }

    # -- FUSE operations --

    def access(self, path, amode):
        if path == "/" or path == "/.info":
            return
        blob = self._lookup(path.removeprefix("/"))
        if not blob:
            raise FuseOSError(errno.ENOENT)

    def getattr(self, path, fh=None):
        if path == "/":
            return self._make_attr(stat.S_IFDIR | 0o755, 4096)
        if path == "/.info":
            return self._make_attr(stat.S_IFREG | 0o444, 4096)

        name = path.removeprefix("/")
        blob = self._lookup(name)
        if blob:
            size = blob.get("size", 0)
            uploaded = blob.get("uploaded", 0)
            return self._make_attr(stat.S_IFREG | 0o644, size, uploaded)

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        return self._all_entries()

    def open(self, path, flags):
        name = path.removeprefix("/")
        blob = self._lookup(name)
        if not blob:
            raise FuseOSError(errno.ENOENT)

        if not self.conversation_key:
            raise FuseOSError(errno.EACCES)

        try:
            if blob.get("sharded"):
                encrypted = self.client.download_sharded(self.servers, blob["sha256"])
            else:
                encrypted = self.client.download_fastest(self.servers, blob["sha256"])

            decrypted = decrypt(encrypted, self.conversation_key)
            with self._lock:
                fd = self._next_fd
                self._next_fd += 1
                self.read_buffers[fd] = decrypted
            return fd
        except Exception:
            raise FuseOSError(errno.EIO)

    def read(self, path, size, offset, fh):
        with self._lock:
            buf = self.read_buffers.get(fh, self.write_buffers.get(fh))
        if buf is None:
            if path == "/.info":
                ok, total = self._server_health_summary()
                lines = []
                for url in self.servers:
                    status = _("healthy") if self._server_health.get(url) else _("unreachable")
                    lines.append(_("server: {url}    {status}").format(url=url, status=status))
                lines.append(_("pubkey: {key}").format(key=self.npub))
                lines.append(_("blobs: {count}").format(count=len(self.blobs)))
                lines.append(_("named: {count}").format(count=len(self.names)))
                lines.append(_("servers: {ok}/{total} healthy").format(ok=ok, total=total))
                info = "\n".join(lines) + "\n"
                return info.encode()[offset : offset + size]
            return b""
        return buf[offset : offset + size]

    def release(self, path, fh):
        with self._lock:
            self.read_buffers.pop(fh, None)
            buf = self.write_buffers.pop(fh, None)
            name = self.write_paths.pop(fh, None)
        if buf is not None and name:
            self._upload(name, bytes(buf))

    def create(self, path, mode, fi=None):
        name = path.removeprefix("/")
        with self._lock:
            fd = self._next_fd
            self._next_fd += 1
            self.write_buffers[fd] = bytearray()
            self.write_paths[fd] = name
        return fd

    def write(self, path, data, offset, fh):
        with self._lock:
            buf = self.write_buffers.get(fh)
            if buf is None:
                raise FuseOSError(errno.EBADF)
            end = offset + len(data)
            if end > len(buf):
                buf.extend(b"\x00" * (end - len(buf)))
            buf[offset:end] = data
        return len(data)

    def truncate(self, path, length, fh=None):
        with self._lock:
            if fh is not None and fh in self.write_buffers:
                buf = self.write_buffers[fh]
                if len(buf) > length:
                    buf[:] = buf[:length]
                elif len(buf) < length:
                    buf.extend(b"\x00" * (length - len(buf)))

    def unlink(self, path):
        name = path.removeprefix("/")
        blob = self._lookup(name)
        if not blob:
            raise FuseOSError(errno.ENOENT)
        sha256 = blob["sha256"]
        try:
            success, failed = self.client.delete_all(self.servers, sha256)
            if not success:
                raise FuseOSError(errno.EIO)
        except Exception:
            raise FuseOSError(errno.EIO)
        with self._lock:
            self.names.pop(name, None)
            self.blobs.pop(sha256, None)
            _save_names(self.names)

    def rename(self, old, new):
        old_name = old.removeprefix("/")
        new_name = new.removeprefix("/")
        with self._lock:
            if old_name in self.names:
                if new_name in self.names:
                    self.names.pop(new_name)
                self.names[new_name] = self.names.pop(old_name)
                _save_names(self.names)

    def statfs(self, path):
        return {
            "f_bsize": 4096,
            "f_frsize": 4096,
            "f_blocks": 0,
            "f_bfree": 0,
            "f_bavail": 0,
            "f_files": len(self.blobs) + 1000,
            "f_ffree": 1000,
        }

    # -- internals --

    def _upload(self, name: str, data: bytes):
        try:
            if not self.servers:
                return

            if self.conversation_key:
                encrypted = encrypt(data, self.conversation_key)
            else:
                encrypted = data

            if len(self.servers) > 1:
                manifest_sha, k, m, errors = self.client.upload_sharded(
                    self.servers, encrypted)
                entry = {
                    "sha256": manifest_sha,
                    "sharded": True,
                    "size": len(data),
                    "type": "application/octet-stream",
                    "uploaded": int(time.time()),
                }
                with self._lock:
                    self.names[name] = entry
                    _save_names(self.names)

                if errors:
                    self._notify(_("Uploaded: {hash}\u2026 (shard errors: {e})").format(
                        hash=manifest_sha[:16], e=", ".join(errors)[:60]))
                else:
                    self._notify(_("Uploaded: {hash}\u2026 (sharded {k}+{m})").format(
                        hash=manifest_sha[:16], k=k, m=m))
            else:
                results, errors = self.client.upload_all(self.servers, encrypted)
                if not results:
                    return
                first_url = next(iter(results))
                result = results[first_url]
                sha256 = result["sha256"]

                entry = {
                    "sha256": sha256,
                    "url": result["url"],
                    "type": result.get("type", "application/octet-stream"),
                    "uploaded": result.get("uploaded", int(time.time())),
                    "size": len(data),
                }
                with self._lock:
                    self.names[name] = entry
                    _save_names(self.names)
                    self.blobs[sha256] = entry

                ok = len(results)
                total = len(self.servers)
                if errors:
                    self._notify(_("Uploaded: {hash}\u2026 ({ok}/{total} servers, errors: {e})").format(
                        hash=sha256[:16], ok=ok, total=total, e=", ".join(errors)))
                else:
                    self._notify(_("Uploaded: {hash}\u2026 ({ok}/{total} servers)").format(
                        hash=sha256[:16], ok=ok, total=total))
        except Exception:
            import traceback
            traceback.print_exc()

    def _notify(self, msg: str):
        try:
            import subprocess
            subprocess.Popen(
                ["notify-send", "Blooms", msg],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def mount(foreground: bool = True):
    mount_point = os.environ.get("BLOOMS_MOUNT", str(MOUNT_ROOT))
    os.makedirs(mount_point, exist_ok=True)
    fs = BlossomFS()
    print(f"Mounting BlossomFS at {mount_point}")
    FUSE(fs, mount_point, foreground=foreground, allow_other=False)
