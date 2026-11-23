"""One-time upload and download links for the streamable-HTTP transport.

A remote client cannot hand the server a local path, and model files are too
large to pass through the conversation. Instead the ``file_transfer`` tool
issues a short-lived, single-purpose link; the client (``curl`` or a browser)
moves the bytes directly to or from the server's ``/files/...`` routes.

- The random code in the link is the credential, so the routes need no bearer
  token. Each code belongs to the token that requested it, expires after
  ``MCP_TRANSFER_TTL_SECONDS``, and is bound to one file.
- Uploads land in the owner's ``models/uploads/`` folder, are size-capped
  (``MCP_UPLOAD_MAX_BYTES``) and count against a per-user quota
  (``MCP_USER_QUOTA_BYTES``). An upload code stops working once a file has
  been stored; a failed attempt can be retried until the code expires.
- A download code works once. Downloads are limited to files the owner may
  read; a folder is sent as a .zip.

Codes live in memory: a server restart invalidates outstanding links, not the
files already stored.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

UPLOAD_ROUTE = "/files/upload/"
DOWNLOAD_ROUTE = "/files/download/"

# EnergyPlus inputs and the companion files models and workflows reference.
UPLOAD_EXTENSIONS = frozenset({
    ".idf", ".imf", ".epjson", ".epw", ".ddy", ".stat", ".csv", ".json", ".txt", ".zip",
})

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class TransferError(ValueError):
    """A request the caller can fix (bad name, too large, expired, ...)."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


@dataclass
class TransferSettings:
    ttl_seconds: int = 900
    max_upload_bytes: int = 100 * 1024 * 1024
    user_quota_bytes: int = 1024 * 1024 * 1024
    max_download_bytes: int = 500 * 1024 * 1024
    # Origin clients use to reach the server, e.g. https://host.run.app. When
    # unset, links are built from the request's Host / X-Forwarded-* headers.
    public_base_url: str = ""

    @classmethod
    def from_env(cls) -> "TransferSettings":
        return cls(
            ttl_seconds=_env_int("MCP_TRANSFER_TTL_SECONDS", cls.ttl_seconds),
            max_upload_bytes=_env_int("MCP_UPLOAD_MAX_BYTES", cls.max_upload_bytes),
            user_quota_bytes=_env_int("MCP_USER_QUOTA_BYTES", cls.user_quota_bytes),
            max_download_bytes=_env_int("MCP_DOWNLOAD_MAX_BYTES", cls.max_download_bytes),
            public_base_url=os.getenv("MCP_PUBLIC_BASE_URL", "").strip().rstrip("/"),
        )


@dataclass
class Ticket:
    code: str
    kind: str  # "upload" | "download"
    owner: str
    expires_at: float
    file_id: str = ""
    filename: str = ""
    destination: str = ""
    expected_size: Optional[int] = None
    sha256: str = ""
    status: str = "pending"  # upload: pending | ready | failed; download: pending | used
    error: str = ""
    size_bytes: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    # Download of a folder: the zip is built when the link is requested.
    cleanup_after_send: bool = False


def safe_filename(name: str) -> str:
    """Keep only the final path component, with a conservative character set."""
    base = Path(str(name).replace("\\", "/")).name.strip()
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    if not cleaned:
        raise TransferError(f"Unusable file name: {name!r}")
    return cleaned


def folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


class TransferStore:
    """In-memory registry of outstanding upload and download codes."""

    def __init__(self, settings: Optional[TransferSettings] = None) -> None:
        self.settings = settings or TransferSettings.from_env()
        self._lock = threading.Lock()
        self._tickets: dict[str, Ticket] = {}

    # -- helpers ----------------------------------------------------------

    def _new_code(self) -> str:
        return secrets.token_urlsafe(32)

    def _prune(self) -> None:
        now = time.time()
        for code, ticket in list(self._tickets.items()):
            # Keep finished uploads around until expiry so their status can be read.
            if ticket.expires_at < now:
                if ticket.cleanup_after_send:
                    _remove_quietly(ticket.destination)
                del self._tickets[code]

    def _uploads(self, owner: str) -> list[Ticket]:
        return [t for t in self._tickets.values() if t.kind == "upload" and t.owner == owner]

    # -- uploads ----------------------------------------------------------

    def request_upload(self, owner: str, user_root: str, filename: str,
                       size_bytes: Optional[int] = None, sha256: str = "") -> Ticket:
        name = safe_filename(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in UPLOAD_EXTENSIONS:
            raise TransferError(
                f"Unsupported file type {suffix or '(none)'}; allowed: {sorted(UPLOAD_EXTENSIONS)}"
            )
        limit = self.settings.max_upload_bytes
        if size_bytes is not None:
            if size_bytes < 0:
                raise TransferError("size_bytes must not be negative")
            if size_bytes > limit:
                raise TransferError(f"File is {size_bytes} bytes; the upload limit is {limit}")
            used = folder_size(user_root) if os.path.isdir(user_root) else 0
            if used + size_bytes > self.settings.user_quota_bytes:
                raise TransferError(
                    f"Upload would exceed your storage quota ({used} of "
                    f"{self.settings.user_quota_bytes} bytes used)"
                )
        sha256 = (sha256 or "").strip().lower()
        if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise TransferError("sha256 must be 64 lowercase hex characters")

        uploads = Path(user_root) / "models" / "uploads"
        with self._lock:
            self._prune()
            destination = _available_name(uploads, name, {t.destination for t in self._uploads(owner)})
            ticket = Ticket(
                code=self._new_code(), kind="upload", owner=owner,
                expires_at=time.time() + self.settings.ttl_seconds,
                file_id=secrets.token_hex(8), filename=Path(destination).name,
                destination=str(destination), expected_size=size_bytes, sha256=sha256,
            )
            self._tickets[ticket.code] = ticket
        return ticket

    def find_upload(self, owner: str, file_id: str) -> Optional[Ticket]:
        with self._lock:
            self._prune()
            for ticket in self._uploads(owner):
                if ticket.file_id == file_id:
                    return ticket
        return None

    def pending_uploads(self, owner: str) -> list[Ticket]:
        with self._lock:
            self._prune()
            return [t for t in self._uploads(owner) if t.status != "ready"]

    def peek_upload(self, code: str) -> Optional[Ticket]:
        """The live upload ticket for ``code`` without claiming it (upload page)."""
        with self._lock:
            self._prune()
            ticket = self._tickets.get(code)
            if ticket is None or ticket.kind != "upload" or ticket.status == "ready":
                return None
            return ticket

    def claim_upload(self, code: str) -> Ticket:
        """Return the live upload ticket for ``code`` or raise TransferError."""
        with self._lock:
            self._prune()
            ticket = self._tickets.get(code)
            if ticket is None or ticket.kind != "upload":
                raise TransferError("This upload link is invalid or has expired")
            if ticket.status == "ready":
                raise TransferError("This upload link has already been used")
            if ticket.status == "receiving":
                raise TransferError("An upload to this link is already in progress")
            ticket.status = "receiving"
            return ticket

    def max_bytes_for(self, ticket: Ticket, user_root: str) -> int:
        """Bytes this upload may write: the declared size, else the remaining cap."""
        if ticket.expected_size is not None:
            return ticket.expected_size
        used = folder_size(user_root) if os.path.isdir(user_root) else 0
        return max(0, min(self.settings.max_upload_bytes, self.settings.user_quota_bytes - used))

    def finish_upload(self, ticket: Ticket, size: Optional[int] = None, error: str = "") -> None:
        with self._lock:
            if error:
                ticket.status, ticket.error = "failed", error
            else:
                ticket.status, ticket.error, ticket.size_bytes = "ready", "", size

    # -- downloads --------------------------------------------------------

    def request_download(self, owner: str, path: str, *, is_bundle: bool = False,
                         filename: str = "") -> Ticket:
        with self._lock:
            self._prune()
            ticket = Ticket(
                code=self._new_code(), kind="download", owner=owner,
                expires_at=time.time() + self.settings.ttl_seconds,
                filename=filename or Path(path).name, destination=path, cleanup_after_send=is_bundle,
                size_bytes=os.path.getsize(path),
            )
            self._tickets[ticket.code] = ticket
        return ticket

    def claim_download(self, code: str) -> Ticket:
        """Return the download ticket for ``code`` and retire it (single use)."""
        with self._lock:
            self._prune()
            ticket = self._tickets.pop(code, None)
            if ticket is None or ticket.kind != "download":
                raise TransferError("This download link is invalid, expired, or already used")
            return ticket


# -- files ---------------------------------------------------------------

def _available_name(folder: Path, name: str, reserved: set[str]) -> Path:
    """``folder/name``, or ``stem_2.ext`` ... if taken on disk or by a pending upload."""
    candidate = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 2
    while candidate.exists() or str(candidate) in reserved:
        candidate = folder / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def zip_folder(folder: str, can_read, max_bytes: int) -> str:
    """Zip ``folder`` into a temporary file; skip anything ``can_read`` rejects.

    Symlinks are followed only when their target is readable for the caller,
    so a link inside the folder cannot pull in another user's files.
    """
    fd, archive = tempfile.mkstemp(prefix="eplus-download-", suffix=".zip")
    os.close(fd)
    total = 0
    root = Path(folder)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for current, _dirs, files in os.walk(root):
                for name in sorted(files):
                    path = Path(current) / name
                    if not can_read(str(path)):
                        continue
                    total += path.stat().st_size
                    if total > max_bytes:
                        raise TransferError(
                            f"Folder is larger than the download limit ({max_bytes} bytes)"
                        )
                    bundle.write(path, arcname=str(path.relative_to(root)))
    except BaseException:
        _remove_quietly(archive)
        raise
    return archive


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_STORE: Optional[TransferStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> TransferStore:
    """Process-wide store shared by the MCP tool and the HTTP routes."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = TransferStore()
        return _STORE


def reset_store(store: Optional[TransferStore] = None) -> None:
    """Replace the process-wide store (tests)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store


def describe_ticket(ticket: Ticket) -> dict[str, Any]:
    return {
        "file_id": ticket.file_id,
        "filename": ticket.filename,
        "status": ticket.status,
        "server_path": ticket.destination if ticket.status == "ready" else None,
        "size_bytes": ticket.size_bytes,
        "expires_in_seconds": max(0, int(ticket.expires_at - time.time())),
        "error": ticket.error or None,
    }
