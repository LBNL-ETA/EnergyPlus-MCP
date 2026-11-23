"""OAuth sign-in through Google for remote clients that cannot send a fixed token.

Hosted MCP clients such as ChatGPT apps only support OAuth (or no auth). With
MCP_OAUTH set, the server acts as its own OAuth 2.1 authorization server, using
the MCP SDK's standard endpoints (/register, /authorize, /token and the
.well-known metadata), and hands the "who are you" step to Google:

    client --/authorize--> this server --redirect--> Google sign-in
    Google --/oauth/google/callback--> this server: email on the allowlist?
        yes -> one-time code -> client's redirect_uri -> /token -> access token

Each allowed email maps to a workspace label, exactly like an MCP_TOKENS label,
so scoping, private runs and admin checks work unchanged.

Nothing is stored. Registered clients, sign-in state, codes and tokens are
HMAC-signed, self-contained strings, so they survive restarts and need no
database. Consequences:
- Removing an email from the allowlist cuts that person off at their next
  request (every token is re-checked against the list).
- Rotating ``signing_key`` signs everyone out and voids registered clients.
- Individual tokens cannot be revoked early; access tokens last an hour.
- Codes are single-use only within one server process (in-memory record);
  they also expire after five minutes and require the client's PKCE verifier.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import secrets
import time
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from energyplus_mcp_server.config import OAuthSettings

logger = logging.getLogger(__name__)

SCOPE = "mcp"
CALLBACK_PATH = "/oauth/google/callback"
OAUTH_PATHS = frozenset({"/authorize", "/token", "/register", CALLBACK_PATH})
WELL_KNOWN_PREFIX = "/.well-known/"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

SIGN_IN_SECONDS = 600       # time allowed for the Google sign-in step
CODE_SECONDS = 300          # authorization code lifetime
ACCESS_SECONDS = 3600       # access token lifetime
REFRESH_SECONDS = 30 * 24 * 3600
MAX_REDIRECT_URIS = 5
MAX_REDIRECT_URI_LENGTH = 512


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _fingerprint(client_id: str) -> str:
    return _b64(hashlib.sha256(client_id.encode()).digest()[:16])


class Signer:
    """Make and check HMAC-signed, expiring JSON strings of one ``kind``."""

    def __init__(self, key: str):
        self._key = hashlib.sha256(b"energyplus-mcp-oauth\0" + key.encode()).digest()

    def _sign(self, kind: str, body: str) -> str:
        return _b64(hmac.new(self._key, f"{kind}.{body}".encode(), hashlib.sha256).digest())

    def dumps(self, kind: str, payload: dict) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        return f"{kind}.{body}.{self._sign(kind, body)}"

    def loads(self, kind: str, value: Optional[str]) -> Optional[dict]:
        """Return the payload, or None if ``value`` is forged, of another kind, or expired."""
        parts = (value or "").split(".")
        if len(parts) != 3 or parts[0] != kind:
            return None
        if not hmac.compare_digest(parts[2], self._sign(kind, parts[1])):
            return None
        try:
            payload = json.loads(_unb64(parts[1]))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if "exp" in payload and payload["exp"] < time.time():
            return None
        return payload


class LabeledAuthorizationCode(AuthorizationCode):
    label: str
    email: str
    jti: str


class LabeledRefreshToken(RefreshToken):
    label: str
    email: str


class LabeledAccessToken(AccessToken):
    label: str
    email: str


# (code, redirect_uri) -> verified email; replaced in tests.
GoogleExchange = Callable[[str, str], Awaitable[str]]


class GoogleOAuthProvider:
    """OAuthAuthorizationServerProvider backed by Google sign-in and an email allowlist."""

    def __init__(self, settings: OAuthSettings, google_exchange: Optional[GoogleExchange] = None):
        self.settings = settings
        self._signer = Signer(settings.signing_key)
        self._google_exchange = google_exchange or self._exchange_with_google
        self._used_codes: dict[str, float] = {}

    # ── who may sign in ─────────────────────────────────────────────────────
    @property
    def callback_url(self) -> str:
        return self.settings.issuer_url + CALLBACK_PATH

    def _allowed(self, email: str, label: str) -> bool:
        return self.settings.users.get(email) == label

    def _client_secret(self, client_id: str) -> str:
        return _b64(hmac.new(self._signer._key, b"client-secret\0" + client_id.encode(),
                             hashlib.sha256).digest())

    def _check_redirect_uri(self, uri: str) -> None:
        if len(uri) > MAX_REDIRECT_URI_LENGTH:
            raise RegistrationError("invalid_redirect_uri", "redirect URI is too long")
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        loopback = host in ("localhost", "127.0.0.1")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise RegistrationError("invalid_redirect_uri", "redirect URIs must use https")
        if not any(host == h or host.endswith("." + h) for h in self.settings.redirect_hosts):
            raise RegistrationError(
                "invalid_redirect_uri",
                f"redirect host {host!r} is not allowed on this server "
                f"(allowed: {', '.join(self.settings.redirect_hosts)})",
            )

    # ── clients (dynamic registration) ──────────────────────────────────────
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        if not uris or len(uris) > MAX_REDIRECT_URIS:
            raise RegistrationError("invalid_redirect_uri",
                                    f"register between 1 and {MAX_REDIRECT_URIS} redirect URIs")
        for uri in uris:
            self._check_redirect_uri(uri)
        metadata = client_info.model_dump(
            mode="json", exclude_none=True,
            include={"redirect_uris", "token_endpoint_auth_method", "grant_types",
                     "response_types", "scope", "client_name"},
        )
        # The SDK returns this same object to the client, so replacing its id
        # and secret here hands out the self-contained versions.
        client_info.client_id = self._signer.dumps(
            "epc", {"m": metadata, "iat": int(time.time()), "n": secrets.token_urlsafe(8)})
        if client_info.client_secret is not None:
            client_info.client_secret = self._client_secret(client_info.client_id)
        logger.info("oauth.register client_name=%s redirect_hosts=%s", client_info.client_name,
                    sorted({urlparse(u).hostname for u in uris}))

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        payload = self._signer.loads("epc", client_id)
        if payload is None:
            return None
        info = OAuthClientInformationFull.model_validate(payload["m"])
        info.client_id = client_id
        if info.token_endpoint_auth_method != "none":
            info.client_secret = self._client_secret(client_id)
        return info

    # ── sign-in ─────────────────────────────────────────────────────────────
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        resource = (params.resource or "").rstrip("/")
        if resource and resource not in (self.settings.issuer_url, self.resource_url):
            raise AuthorizeError("invalid_request", f"unknown resource {params.resource!r}")
        state = self._signer.dumps("eps", {
            "ch": _fingerprint(client.client_id or ""),
            "r": str(params.redirect_uri),
            "x": params.redirect_uri_provided_explicitly,
            "cc": params.code_challenge,
            "s": params.state,
            "sc": params.scopes or [SCOPE],
            "res": params.resource,
            "exp": int(time.time()) + SIGN_IN_SECONDS,
        })
        return GOOGLE_AUTHORIZE_URL + "?" + urlencode({
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.callback_url,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "prompt": "select_account",
        })

    async def google_callback(self, request: Request) -> Response:
        """Google sends the browser here after sign-in."""
        query = request.query_params
        state = self._signer.loads("eps", query.get("state"))
        if state is None:
            return _page("Sign-in link expired",
                         "Start again from the app you were connecting.", 400)
        if query.get("error") or not query.get("code"):
            return RedirectResponse(construct_redirect_uri(
                state["r"], error="access_denied", state=state["s"]), status_code=302)
        try:
            email = await self._google_exchange(query["code"], self.callback_url)
        except Exception as exc:  # network failure or a bad Google response
            logger.warning("oauth.google_failed error=%s", exc)
            return _page("Google sign-in failed", "Please try again in a moment.", 502)
        label = self.settings.users.get(email)
        if label is None:
            logger.info("oauth.denied email=%s", email)
            return _page("Not allowed",
                         f"{email} is not on this server's list of users. Ask the "
                         "server's administrator to add it.", 403)
        code = self._signer.dumps("epa", {
            "ch": state["ch"], "r": state["r"], "x": state["x"], "cc": state["cc"],
            "sc": state["sc"], "res": state["res"], "l": label, "e": email,
            "jti": secrets.token_urlsafe(12), "exp": int(time.time()) + CODE_SECONDS,
        })
        logger.info("oauth.signed_in label=%s", label)
        return RedirectResponse(construct_redirect_uri(state["r"], code=code, state=state["s"]),
                                status_code=302)

    async def _exchange_with_google(self, code: str, redirect_uri: str) -> str:
        """Trade Google's code for an ID token and return its verified email."""
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
        response.raise_for_status()
        return email_from_id_token(response.json()["id_token"], self.settings.google_client_id)

    # ── codes and tokens ────────────────────────────────────────────────────
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[LabeledAuthorizationCode]:
        p = self._signer.loads("epa", authorization_code)
        if p is None or p["ch"] != _fingerprint(client.client_id or ""):
            return None
        if p["jti"] in self._used_codes or not self._allowed(p["e"], p["l"]):
            return None
        return LabeledAuthorizationCode(
            code=authorization_code, scopes=p["sc"], expires_at=p["exp"],
            client_id=client.client_id, code_challenge=p["cc"], redirect_uri=p["r"],
            redirect_uri_provided_explicitly=p["x"], resource=p["res"],
            label=p["l"], email=p["e"], jti=p["jti"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: LabeledAuthorizationCode
    ) -> OAuthToken:
        now = time.time()
        self._used_codes = {j: exp for j, exp in self._used_codes.items() if exp > now}
        self._used_codes[authorization_code.jti] = authorization_code.expires_at
        return self._issue(client, authorization_code.label, authorization_code.email,
                           authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[LabeledRefreshToken]:
        p = self._signer.loads("epr", refresh_token)
        if p is None or p["ch"] != _fingerprint(client.client_id or ""):
            return None
        if not self._allowed(p["e"], p["l"]):
            return None
        return LabeledRefreshToken(token=refresh_token, client_id=client.client_id,
                                   scopes=p["sc"], expires_at=p["exp"], label=p["l"], email=p["e"])

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: LabeledRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return self._issue(client, refresh_token.label, refresh_token.email, scopes, None)

    def _issue(self, client, label: str, email: str, scopes: list[str],
               resource: Optional[str]) -> OAuthToken:
        now = int(time.time())
        common = {"ch": _fingerprint(client.client_id or ""), "l": label, "e": email, "sc": scopes}
        access = self._signer.dumps("ept", {**common, "res": resource,
                                            "jti": secrets.token_urlsafe(8),
                                            "exp": now + ACCESS_SECONDS})
        refresh = self._signer.dumps("epr", {**common, "jti": secrets.token_urlsafe(8),
                                             "exp": now + REFRESH_SECONDS})
        return OAuthToken(access_token=access, expires_in=ACCESS_SECONDS,
                          scope=" ".join(scopes), refresh_token=refresh)

    async def load_access_token(self, token: str) -> Optional[LabeledAccessToken]:
        p = self._signer.loads("ept", token)
        if p is None or not self._allowed(p["e"], p["l"]):
            return None
        return LabeledAccessToken(token=token, client_id=p["ch"], scopes=p["sc"],
                                  expires_at=p["exp"], resource=p.get("res"),
                                  label=p["l"], email=p["e"])

    async def label_for_token(self, token: str) -> Optional[str]:
        """Workspace label for a valid access token (used by AuthMiddleware)."""
        loaded = await self.load_access_token(token)
        return loaded.label if loaded else None

    async def revoke_token(self, token) -> None:  # pragma: no cover - endpoint disabled
        """Tokens are stateless; remove the email from the allowlist instead."""

    # ── HTTP routes ─────────────────────────────────────────────────────────
    @property
    def resource_url(self) -> str:
        return self.settings.issuer_url + self._mcp_path

    _mcp_path = "/mcp"

    @property
    def resource_metadata_url(self) -> str:
        return self.settings.issuer_url + "/.well-known/oauth-protected-resource" + self._mcp_path

    def routes(self, mcp_path: str = "/mcp") -> list[Route]:
        self._mcp_path = mcp_path
        issuer = AnyHttpUrl(self.settings.issuer_url)
        resource_routes = create_protected_resource_routes(
            resource_url=AnyHttpUrl(self.resource_url),
            authorization_servers=[issuer],
            scopes_supported=[SCOPE],
            resource_name="EnergyPlus-MCP",
        )
        # Some clients look for the metadata without the /mcp suffix.
        resource_routes.append(Route("/.well-known/oauth-protected-resource",
                                     endpoint=resource_routes[0].endpoint,
                                     methods=["GET", "OPTIONS"]))
        return [
            *create_auth_routes(
                self, issuer,
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                revocation_options=RevocationOptions(enabled=False),
            ),
            *resource_routes,
            Route(CALLBACK_PATH, self.google_callback, methods=["GET"]),
        ]


def email_from_id_token(id_token: str, audience: str) -> str:
    """Return the verified email in a Google ID token.

    The token came straight from Google's token endpoint over TLS, in exchange
    for our client secret, so its signature need not be checked again (OpenID
    Connect Core 3.1.3.7); its claims still are.
    """
    claims = json.loads(_unb64(id_token.split(".")[1]))
    if claims.get("aud") != audience:
        raise ValueError("ID token is for another client")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("ID token is not from Google")
    if claims.get("exp", 0) < time.time():
        raise ValueError("ID token has expired")
    if claims.get("email_verified") not in (True, "true") or not claims.get("email"):
        raise ValueError("Google account email is not verified")
    return claims["email"].strip().lower()


def _page(title: str, message: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.4rem'>{html.escape(title)}</h1><p>{html.escape(message)}</p>",
        status_code=status,
    )
