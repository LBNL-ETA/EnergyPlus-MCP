"""OAuth sign-in through Google, for clients (such as ChatGPT apps) that need OAuth."""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from energyplus_mcp_server.auth import REQUEST_STATE_LABEL_KEY, AuthMiddleware
from energyplus_mcp_server.config import OAuthSettings
from energyplus_mcp_server.oauth import GoogleOAuthProvider, Signer, email_from_id_token

ISSUER = "https://mcp.example.test"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
STATIC_TOKEN = "s" * 40


def _settings(**overrides):
    values = dict(
        issuer_url=ISSUER, google_client_id="gid.apps.googleusercontent.com",
        google_client_secret="gsecret", signing_key="k" * 40,
        users={"alice@lbl.gov": "alice"},
    )
    values.update(overrides)
    return OAuthSettings(**values)


class Server:
    def __init__(self, settings=None):
        self.settings = settings or _settings()
        self.google_email = "alice@lbl.gov"

        async def fake_google(code, redirect_uri):
            assert code == "google-code" and redirect_uri == ISSUER + "/oauth/google/callback"
            return self.google_email

        self.provider = GoogleOAuthProvider(self.settings, google_exchange=fake_google)

        async def mcp_endpoint(request: Request):
            return JSONResponse({"label": getattr(request.state, REQUEST_STATE_LABEL_KEY)})

        app = Starlette(routes=[*self.provider.routes("/mcp"),
                                Route("/mcp", mcp_endpoint, methods=["POST"])])
        app.add_middleware(AuthMiddleware, tokens={STATIC_TOKEN: "static"}, oauth=self.provider)
        self.client = TestClient(app, base_url=ISSUER, follow_redirects=False)

    def register(self, redirect=REDIRECT, method="client_secret_post"):
        return self.client.post("/register", json={
            "redirect_uris": [redirect], "client_name": "ChatGPT",
            "token_endpoint_auth_method": method,
        })

    def sign_in(self, client):
        """Run /authorize and the Google callback; return (response, verifier)."""
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        start = self.client.get("/authorize", params={
            "response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
            "resource": ISSUER + "/mcp",
        })
        assert start.status_code == 302, start.text
        google = urlparse(start.headers["location"])
        assert google.netloc == "accounts.google.com"
        state = parse_qs(google.query)["state"][0]
        back = self.client.get("/oauth/google/callback", params={"code": "google-code", "state": state})
        return back, verifier

    def token(self, client, **form):
        return self.client.post("/token", data={
            "client_id": client["client_id"], "client_secret": client.get("client_secret"), **form})

    def full_sign_in(self):
        client = self.register().json()
        back, verifier = self.sign_in(client)
        code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
        tokens = self.token(client, grant_type="authorization_code", code=code,
                            redirect_uri=REDIRECT, code_verifier=verifier)
        assert tokens.status_code == 200, tokens.text
        return client, tokens.json(), code, verifier

    def call_mcp(self, token):
        return self.client.post("/mcp", headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def server():
    return Server()


def test_metadata_is_public(server):
    meta = server.client.get("/.well-known/oauth-authorization-server").json()
    assert meta["authorization_endpoint"] == ISSUER + "/authorize"
    assert meta["registration_endpoint"] == ISSUER + "/register"
    for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
        resource = server.client.get(path).json()
        assert resource["resource"] == ISSUER + "/mcp"
        assert resource["authorization_servers"] == [ISSUER + "/"]


def test_unauthenticated_call_points_to_sign_in(server):
    response = server.client.post("/mcp")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{ISSUER}/.well-known/oauth-protected-resource/mcp"')


def test_full_sign_in_gives_the_users_label(server):
    client, tokens, _, _ = server.full_sign_in()
    assert client["client_id"].startswith("epc.")
    back = server.call_mcp(tokens["access_token"])
    assert back.status_code == 200 and back.json() == {"label": "alice"}
    # Fixed tokens keep working next to OAuth.
    assert server.call_mcp(STATIC_TOKEN).json() == {"label": "static"}


def test_redirect_carries_state_and_code(server):
    client = server.register().json()
    back, _ = server.sign_in(client)
    assert back.status_code == 302
    location = urlparse(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
    assert parse_qs(location.query)["state"] == ["xyz"]


def test_refresh_token_issues_new_access_token(server):
    client, tokens, _, _ = server.full_sign_in()
    refreshed = server.token(client, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert refreshed.status_code == 200, refreshed.text
    assert server.call_mcp(refreshed.json()["access_token"]).json() == {"label": "alice"}


def test_code_is_single_use(server):
    client, _, code, verifier = server.full_sign_in()
    again = server.token(client, grant_type="authorization_code", code=code,
                         redirect_uri=REDIRECT, code_verifier=verifier)
    assert again.status_code == 400


def test_code_needs_the_pkce_verifier(server):
    client = server.register().json()
    back, _ = server.sign_in(client)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    wrong = server.token(client, grant_type="authorization_code", code=code,
                         redirect_uri=REDIRECT, code_verifier="x" * 50)
    assert wrong.status_code == 400


def test_code_cannot_be_used_by_another_client(server):
    first = server.register().json()
    other = server.register().json()
    back, verifier = server.sign_in(first)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    stolen = server.token(other, grant_type="authorization_code", code=code,
                          redirect_uri=REDIRECT, code_verifier=verifier)
    assert stolen.status_code == 400


def test_client_secret_is_required(server):
    client = server.register().json()
    back, verifier = server.sign_in(client)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    response = server.token({**client, "client_secret": "wrong"}, grant_type="authorization_code",
                            code=code, redirect_uri=REDIRECT, code_verifier=verifier)
    assert response.status_code == 401


def test_email_not_on_the_list_is_refused(server):
    server.google_email = "mallory@example.com"
    client = server.register().json()
    back, _ = server.sign_in(client)
    assert back.status_code == 403 and "mallory@example.com" in back.text


def test_removing_a_user_cuts_off_their_tokens(server):
    client, tokens, _, _ = server.full_sign_in()
    server.settings.users.pop("alice@lbl.gov")
    assert server.call_mcp(tokens["access_token"]).status_code == 401
    refreshed = server.token(client, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert refreshed.status_code == 400


def test_tokens_from_another_signing_key_are_refused(server):
    _, tokens, _, _ = server.full_sign_in()
    other = Server(_settings(signing_key="z" * 40))
    assert other.call_mcp(tokens["access_token"]).status_code == 401


@pytest.mark.parametrize("redirect", [
    "https://evil.example.com/callback",
    "http://chatgpt.com/callback",              # not https
    "https://chatgpt.com.evil.com/callback",
])
def test_unknown_redirect_hosts_cannot_register(server, redirect):
    response = server.register(redirect=redirect)
    assert response.status_code == 400 and response.json()["error"] == "invalid_redirect_uri"


def test_public_clients_and_loopback_redirects(server):
    client = server.register(redirect="http://127.0.0.1:3334/callback", method="none").json()
    assert "client_secret" not in client or client["client_secret"] is None


def test_expired_or_forged_sign_in_state(server):
    response = server.client.get("/oauth/google/callback", params={"code": "google-code", "state": "eps.x.y"})
    assert response.status_code == 400


def test_google_cancel_returns_access_denied(server):
    client = server.register().json()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    start = server.client.get("/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz"})
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    back = server.client.get("/oauth/google/callback", params={"error": "access_denied", "state": state})
    assert back.status_code == 302 and "error=access_denied" in back.headers["location"]


def test_signer_rejects_tampering_and_expiry():
    signer = Signer("k" * 40)
    token = signer.dumps("ept", {"l": "alice", "exp": time.time() + 60})
    assert signer.loads("ept", token)["l"] == "alice"
    assert signer.loads("epr", token) is None                     # other kind
    kind, body, sig = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"l": "bob", "exp": time.time() + 60}).encode()).decode().rstrip("=")
    assert signer.loads("ept", f"{kind}.{forged}.{sig}") is None
    assert signer.loads("ept", signer.dumps("ept", {"exp": time.time() - 1})) is None


def _id_token(**claims):
    base = {"aud": "gid", "iss": "https://accounts.google.com", "exp": time.time() + 60,
            "email": "Alice@LBL.gov", "email_verified": True}
    base.update(claims)
    body = base64.urlsafe_b64encode(json.dumps(base).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def test_id_token_claims_are_checked():
    assert email_from_id_token(_id_token(), "gid") == "alice@lbl.gov"
    for bad in ({"aud": "other"}, {"iss": "evil"}, {"exp": 1}, {"email_verified": False}):
        with pytest.raises(ValueError):
            email_from_id_token(_id_token(**bad), "gid")


# ── configuration ───────────────────────────────────────────────────────────

def _config(monkeypatch, oauth, tokens=None, base_url=ISSUER, admins=None):
    for var in ("MCP_HTTP_HOST", "MCP_HTTP_PORT", "MCP_HTTP_PATH", "PORT", "MCP_ADMIN_LABELS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_TOKENS", json.dumps(tokens or []))
    monkeypatch.setenv("MCP_OAUTH", json.dumps(oauth) if oauth is not None else "")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", base_url)
    if admins:
        monkeypatch.setenv("MCP_ADMIN_LABELS", admins)
    from energyplus_mcp_server.config import Config
    return Config()


GOOD = {"google_client_id": "gid", "google_client_secret": "gs", "signing_key": "k" * 40,
        "users": {"Alice@LBL.gov": "alice"}}


def test_config_oauth_alone_is_enough(monkeypatch):
    cfg = _config(monkeypatch, GOOD, admins="alice")
    assert cfg.auth.tokens == {}
    assert cfg.auth.oauth.users == {"alice@lbl.gov": "alice"}
    assert cfg.auth.oauth.issuer_url == ISSUER
    assert cfg.auth.admin_labels == {"alice"}


@pytest.mark.parametrize("oauth, base_url, message", [
    ({**GOOD, "signing_key": "short"}, ISSUER, "signing_key"),
    ({**GOOD, "users": {"alice@lbl.gov": "Not Valid"}}, ISSUER, "invalid label"),
    ({**GOOD, "users": {"nobody": "alice"}}, ISSUER, "invalid email"),
    ({k: v for k, v in GOOD.items() if k != "google_client_secret"}, ISSUER, "google_client_secret"),
    (GOOD, "http://mcp.example.test", "MCP_PUBLIC_BASE_URL"),
])
def test_config_rejects_bad_oauth(monkeypatch, oauth, base_url, message):
    with pytest.raises(ValueError, match=message):
        _config(monkeypatch, oauth, base_url=base_url)


def test_config_needs_tokens_or_oauth(monkeypatch):
    with pytest.raises(ValueError, match="MCP_TOKENS or MCP_OAUTH"):
        _config(monkeypatch, None)
