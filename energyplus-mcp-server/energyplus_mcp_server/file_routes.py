"""HTTP routes behind the one-time links issued by the ``file_transfer`` tool.

  GET       /files/upload/{code}    small page to pick and send a file (browsers)
  PUT|POST  /files/upload/{code}    raw file bytes as the request body (curl)
  GET       /files/download/{code}  the file, once

The code in the path is the credential (see utils/file_transfer.py), so these
routes sit outside the bearer-token middleware.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import tempfile
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from energyplus_mcp_server.utils.file_transfer import (
    DOWNLOAD_ROUTE,
    UPLOAD_ROUTE,
    TransferError,
    get_store,
)

logger = logging.getLogger(__name__)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
             "X-Content-Type-Options": "nosniff"}


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=_NO_STORE)


def _user_root_of(destination: str) -> str:
    # Uploads go to <user_root>/models/uploads/<name>.
    return str(Path(destination).parents[2])


async def upload_page(request: Request) -> Response:
    ticket = get_store().peek_upload(request.path_params["code"])
    if ticket is None:
        return HTMLResponse(_page("Link expired", "<p>This upload link is invalid, expired, or "
                                  "already used. Ask the assistant for a new one.</p>"),
                            status_code=404, headers=_NO_STORE)
    name = html.escape(ticket.filename)
    size_note = (f" ({ticket.expected_size:,} bytes expected)"
                 if ticket.expected_size is not None else "")
    body = f"""
<p>Upload a file to the EnergyPlus MCP server. It will be stored as
<code>{name}</code>{html.escape(size_note)}.</p>
<input id="file" type="file">
<button id="send">Upload</button>
<p id="status" role="status"></p>
<script>
document.getElementById('send').onclick = async () => {{
  const file = document.getElementById('file').files[0];
  const status = document.getElementById('status');
  if (!file) {{ status.textContent = 'Choose a file first.'; return; }}
  status.textContent = 'Uploading...';
  try {{
    const response = await fetch(window.location.pathname, {{method: 'PUT', body: file}});
    const result = await response.json();
    status.textContent = response.ok
      ? 'Uploaded. Tell the assistant the upload is done.'
      : 'Upload failed: ' + (result.error || response.status);
  }} catch (error) {{ status.textContent = 'Upload failed: ' + error; }}
}};
</script>"""
    return HTMLResponse(_page("Upload a file", body), headers=_NO_STORE)


async def receive_upload(request: Request) -> Response:
    store = get_store()
    try:
        ticket = store.claim_upload(request.path_params["code"])
    except TransferError as error:
        return _error(str(error), 404)

    user_root = _user_root_of(ticket.destination)
    limit = store.max_bytes_for(ticket, user_root)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        store.finish_upload(ticket, error=f"File is larger than allowed ({limit} bytes)")
        return _error(ticket.error, 413)

    destination = Path(ticket.destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(prefix=".upload-", dir=str(destination.parent))
    digest, written = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as handle:
            async for chunk in request.stream():
                written += len(chunk)
                if written > limit:
                    raise TransferError(f"File is larger than allowed ({limit} bytes)")
                digest.update(chunk)
                handle.write(chunk)
        if ticket.expected_size is not None and written != ticket.expected_size:
            raise TransferError(
                f"Received {written} bytes but {ticket.expected_size} were declared"
            )
        if ticket.sha256 and digest.hexdigest() != ticket.sha256:
            raise TransferError("Checksum mismatch: the file does not match the declared sha256")
        os.replace(partial, destination)
    except TransferError as error:
        os.remove(partial)
        store.finish_upload(ticket, error=str(error))
        return _error(str(error), 413 if "larger" in str(error) else 400)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        store.finish_upload(ticket, error="Upload interrupted; try the link again")
        raise

    store.finish_upload(ticket, size=written)
    logger.info("file_transfer.upload owner=%s file=%s bytes=%d", ticket.owner, destination, written)
    return JSONResponse({"file_id": ticket.file_id, "server_path": str(destination),
                         "size_bytes": written, "sha256": digest.hexdigest()},
                        headers=_NO_STORE)


async def send_download(request: Request) -> Response:
    try:
        ticket = get_store().claim_download(request.path_params["code"])
    except TransferError as error:
        return _error(str(error), 404)
    if not os.path.isfile(ticket.destination):
        return _error("The file no longer exists on the server", 410)
    logger.info("file_transfer.download owner=%s file=%s", ticket.owner, ticket.destination)
    cleanup = BackgroundTask(os.remove, ticket.destination) if ticket.cleanup_after_send else None
    return FileResponse(ticket.destination, filename=ticket.filename,
                        headers=_NO_STORE, background=cleanup)


def file_routes() -> list[Route]:
    return [
        Route(UPLOAD_ROUTE + "{code}", upload_page, methods=["GET"]),
        Route(UPLOAD_ROUTE + "{code}", receive_upload, methods=["PUT", "POST"]),
        Route(DOWNLOAD_ROUTE + "{code}", send_download, methods=["GET"]),
    ]


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - EnergyPlus MCP</title>
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;line-height:1.5}}
button{{margin-left:.5rem}}</style></head>
<body><h1>{html.escape(title)}</h1>{body}</body></html>"""
