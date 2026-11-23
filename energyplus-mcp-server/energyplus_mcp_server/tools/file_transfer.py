"""file_transfer: move files between a remote client and this server.

Registered only with the streamable-HTTP transport; over stdio the server
already reads and writes the user's own files.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, Optional

from energyplus_mcp_server.scope import ScopeError, current_scope
from energyplus_mcp_server.utils.file_transfer import (
    DOWNLOAD_ROUTE,
    UPLOAD_ROUTE,
    TransferError,
    describe_ticket,
    get_store,
    zip_folder,
)
from energyplus_mcp_server.utils.path_utils import resolve_path, work_dir


def _request_base_url() -> str:
    """Origin the client used to reach this server, from the current MCP request."""
    try:
        from mcp.server.lowlevel.server import request_ctx
        request = getattr(request_ctx.get(), "request", None)
    except (ImportError, LookupError):
        request = None
    if request is None:
        return ""
    headers = request.headers
    # Behind a proxy (Cloud Run, a load balancer) TLS ends before the server,
    # so trust the forwarded scheme and host when present.
    scheme = headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = headers.get("x-forwarded-host", headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{scheme}://{host}"


def _link(route: str, code: str) -> str:
    base = get_store().settings.public_base_url or _request_base_url()
    return f"{base}{route}{code}"


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def file_transfer(
        action: Literal["request_upload", "upload_status", "list_uploads", "delete_upload", "request_download"],
        filename: Optional[str] = None,
        size_bytes: Optional[int] = None,
        sha256: Optional[str] = None,
        file_id: Optional[str] = None,
        path: Optional[str] = None,
    ) -> str:
        """Move files between the user's machine and this remote server.

        The server cannot read paths on the user's machine. Use this tool to get
        a one-time link; the file then travels directly over HTTP, not through
        the conversation.

        Upload a local model or weather file:
          1. action="request_upload", filename (and size_bytes if known; sha256
             optional) -> upload_url, file_id.
          2. Send the file to upload_url: run
             curl --upload-file <local file> "<upload_url>"
             or, without a shell, give the user upload_url to open in a browser
             and pick the file there.
          3. action="upload_status", file_id -> server_path once status="ready".
          4. Pass server_path (or just the filename) to other tools.

        Download an output: action="request_download", path=<file or folder on
        the server> -> download_url (single use; a folder is sent as .zip). Fetch
        it with curl -fJO "<download_url>" or give the link to the user.

        Also: action="list_uploads" (your uploaded files and pending uploads),
        action="delete_upload", filename=<name in models/uploads>.

        Links expire after a few minutes. Uploads are stored in your
        models/uploads folder; allowed types are .idf .imf .epJSON .epw .ddy
        .stat .csv .json .txt .zip.
        """
        try:
            scope = current_scope(config)
        except ScopeError as error:
            return json.dumps({"error": str(error)})
        if scope is None:
            return json.dumps({
                "error": "file_transfer is only needed over the HTTP transport; "
                         "with stdio, pass local file paths to the other tools directly",
            })
        store = get_store()
        owner = scope.label
        uploads_dir = work_dir(config, "uploads")

        try:
            if action == "request_upload":
                if not filename:
                    raise TransferError("request_upload requires filename")
                ticket = store.request_upload(owner, scope.user_root, filename, size_bytes, sha256 or "")
                upload_url = _link(UPLOAD_ROUTE, ticket.code)
                return json.dumps({
                    "file_id": ticket.file_id,
                    "upload_url": upload_url,
                    "stored_as": ticket.filename,
                    "expires_in_seconds": store.settings.ttl_seconds,
                    "curl": f'curl --fail --upload-file "<local path>" "{upload_url}"',
                    "browser": "Or open upload_url in a browser and choose the file.",
                    "next": "Call action='upload_status' with file_id once the upload finishes.",
                }, indent=2)

            if action == "upload_status":
                if not file_id:
                    raise TransferError("upload_status requires file_id")
                ticket = store.find_upload(owner, file_id)
                if ticket is None:
                    raise TransferError(f"No upload with file_id {file_id} (links expire after use)")
                return json.dumps(describe_ticket(ticket), indent=2)

            if action == "list_uploads":
                files = []
                if os.path.isdir(uploads_dir):
                    for entry in sorted(Path(uploads_dir).iterdir()):
                        if entry.is_file() and not entry.name.startswith("."):
                            files.append({"filename": entry.name, "server_path": str(entry),
                                          "size_bytes": entry.stat().st_size})
                pending = [describe_ticket(t) for t in store.pending_uploads(owner)]
                return json.dumps({"uploads": files, "pending": pending}, indent=2)

            if action == "delete_upload":
                if not filename:
                    raise TransferError("delete_upload requires filename")
                target = Path(uploads_dir) / Path(filename).name
                if not target.is_file():
                    raise TransferError(f"No uploaded file named {Path(filename).name}")
                target.unlink()
                return json.dumps({"deleted": str(target)}, indent=2)

            if action == "request_download":
                if not path:
                    raise TransferError("request_download requires path")
                resolved = resolve_path(config, path, description="download path")
                limit = store.settings.max_download_bytes
                if os.path.isdir(resolved):
                    archive = zip_folder(resolved, scope.can_read, limit)
                    ticket = store.request_download(owner, archive, is_bundle=True,
                                                    filename=f"{Path(resolved).name}.zip")
                else:
                    if os.path.getsize(resolved) > limit:
                        raise TransferError(f"File is larger than the download limit ({limit} bytes)")
                    ticket = store.request_download(owner, resolved)
                download_url = _link(DOWNLOAD_ROUTE, ticket.code)
                return json.dumps({
                    "download_url": download_url,
                    "filename": ticket.filename,
                    "size_bytes": ticket.size_bytes,
                    "expires_in_seconds": store.settings.ttl_seconds,
                    "single_use": True,
                    "curl": f'curl --fail -JO "{download_url}"',
                }, indent=2)

            return json.dumps({"error": f"Unknown action: {action}"})
        except (TransferError, ScopeError, FileNotFoundError, ValueError) as error:
            return json.dumps({"action": action, "error": str(error)}, indent=2)
