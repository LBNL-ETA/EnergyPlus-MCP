"""Tests for transport / auth additions to Config."""
import os
import pytest

from energyplus_mcp_server.config import Config


def _clear_env(monkeypatch):
    for var in ("MCP_TRANSPORT", "MCP_HTTP_HOST", "MCP_HTTP_PORT",
                "MCP_HTTP_PATH", "MCP_TOKENS", "PORT"):
        monkeypatch.delenv(var, raising=False)


def test_transport_defaults_to_stdio(monkeypatch):
    _clear_env(monkeypatch)
    cfg = Config()
    assert cfg.transport.transport == "stdio"
    assert cfg.transport.http_host == "0.0.0.0"
    assert cfg.transport.http_port == 8000
    assert cfg.transport.http_path == "/mcp"


def test_transport_reads_env_overrides(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_HTTP_PORT", "9000")
    monkeypatch.setenv("MCP_HTTP_PATH", "/custom")
    monkeypatch.setenv("MCP_TOKENS",
        '[{"label":"x","token":"abcdefghijklmnopqrstuvwxyz012345"}]')
    cfg = Config()
    assert cfg.transport.transport == "streamable-http"
    assert cfg.transport.http_host == "127.0.0.1"
    assert cfg.transport.http_port == 9000
    assert cfg.transport.http_path == "/custom"


def test_transport_port_from_PORT_env_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PORT", "8080")
    cfg = Config()
    assert cfg.transport.http_port == 8080


def test_transport_unknown_value_rejected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "websocket")
    with pytest.raises(ValueError, match="MCP_TRANSPORT must be"):
        Config()


def test_auth_tokens_default_empty(monkeypatch):
    _clear_env(monkeypatch)
    cfg = Config()
    assert cfg.auth.tokens == {}


def test_auth_tokens_parses_valid_json(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS",
        '[{"label":"alice","token":"abcdefghijklmnopqrstuvwxyz012345"},'
        ' {"label":"bob","token":"abcdefghijklmnopqrstuvwxyz543210"}]')
    cfg = Config()
    assert cfg.auth.tokens == {
        "abcdefghijklmnopqrstuvwxyz012345": "alice",
        "abcdefghijklmnopqrstuvwxyz543210": "bob",
    }


def test_auth_rejects_malformed_json(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS", "not-json-at-all")
    with pytest.raises(ValueError, match="MCP_TOKENS must be valid JSON"):
        Config()


def test_auth_rejects_missing_keys(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS", '[{"label":"alice"}]')
    with pytest.raises(ValueError, match="missing 'token' or 'label'"):
        Config()


def test_auth_rejects_bad_label(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS",
        '[{"label":"Alice/Bob","token":"abcdefghijklmnopqrstuvwxyz012345"}]')
    with pytest.raises(ValueError, match="invalid label"):
        Config()


def test_auth_rejects_short_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS", '[{"label":"alice","token":"short"}]')
    with pytest.raises(ValueError, match="token too short"):
        Config()


def test_auth_rejects_duplicate_label(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS",
        '[{"label":"alice","token":"abcdefghijklmnopqrstuvwxyz012345"},'
        ' {"label":"alice","token":"zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"}]')
    with pytest.raises(ValueError, match="duplicate label"):
        Config()


def test_auth_rejects_duplicate_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TOKENS",
        '[{"label":"alice","token":"abcdefghijklmnopqrstuvwxyz012345"},'
        ' {"label":"bob","token":"abcdefghijklmnopqrstuvwxyz012345"}]')
    with pytest.raises(ValueError, match="duplicate token"):
        Config()


def test_http_transport_with_empty_tokens_fails_closed(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    with pytest.raises(ValueError, match="streamable-http transport requires"):
        Config()


def test_stdio_with_empty_tokens_is_fine(monkeypatch):
    _clear_env(monkeypatch)
    cfg = Config()  # stdio default + no tokens → OK
    assert cfg.transport.transport == "stdio"
    assert cfg.auth.tokens == {}
