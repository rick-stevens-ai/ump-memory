"""Tests for the HTTP server, including the URN-friendly /ump/get variants
and the markdown-directory auto-detection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from ump_memory.server import make_app, _resolve_store  # noqa: E402
from ump_memory.md_store import MarkdownDirectoryStore  # noqa: E402
from ump_memory.store import UMPStore  # noqa: E402


CARD_ENV = {
    "ump": "0.1",
    "id": "urn:ump:servrtestabcdefghijklmnop",
    "kind": "semantic",
    "scope": {"owner": "did:key:z6Mk-test", "project": "rs/test", "visibility": "private"},
    "time": {"created": "2026-06-08T00:00:00Z"},
    "lifecycle": {"confidence": 0.7},
    "body": {"structured": {"summary": "test card", "email": "alice@example.org"}},
}


def _seed_card(root: Path) -> str:
    mem_d = root / "memory.d"
    mem_d.mkdir(parents=True, exist_ok=True)
    slug = CARD_ENV["id"].removeprefix("urn:ump:")
    path = mem_d / f"{slug}.ump.md"
    path.write_text(
        "---\n" + json.dumps(CARD_ENV, sort_keys=True, indent=2) + "\n---\n\nbody text alice@example.org\n",
        encoding="utf-8",
    )
    return CARD_ENV["id"]


# ---- store resolution ------------------------------------------------------


def test_resolve_store_explicit_kind_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("UMP_STORE_KIND", "markdown")
    monkeypatch.delenv("UMP_DIR", raising=False)
    s = _resolve_store(tmp_path)
    assert isinstance(s, MarkdownDirectoryStore)


def test_resolve_store_explicit_kind_json(tmp_path, monkeypatch):
    monkeypatch.setenv("UMP_STORE_KIND", "json")
    monkeypatch.delenv("UMP_DIR", raising=False)
    s = _resolve_store(tmp_path / "x.jsonl")
    assert isinstance(s, UMPStore)


def test_resolve_store_ump_dir_implies_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("UMP_STORE_KIND", raising=False)
    monkeypatch.setenv("UMP_DIR", str(tmp_path))
    s = _resolve_store(None)
    assert isinstance(s, MarkdownDirectoryStore)


def test_resolve_store_falls_back_to_jsonl(tmp_path, monkeypatch):
    monkeypatch.delenv("UMP_STORE_KIND", raising=False)
    monkeypatch.delenv("UMP_DIR", raising=False)
    monkeypatch.delenv("UMP_STORE", raising=False)
    s = _resolve_store(tmp_path / "x.jsonl")
    assert isinstance(s, UMPStore)


# ---- URN-friendly /ump/get -------------------------------------------------


@pytest.fixture
def md_client(tmp_path, monkeypatch):
    monkeypatch.setenv("UMP_STORE_KIND", "markdown")
    _seed_card(tmp_path)
    app = make_app(str(tmp_path))
    return TestClient(app), CARD_ENV["id"]


def test_get_by_urn_path_param(md_client):
    client, urn = md_client
    r = client.get(f"/ump/get/{urn}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == urn
    assert body["scope"]["project"] == "rs/test"


def test_get_by_urn_query_string(md_client):
    client, urn = md_client
    r = client.get("/ump/get", params={"id": urn})
    assert r.status_code == 200
    assert r.json()["id"] == urn


def test_get_by_urn_post_body(md_client):
    client, urn = md_client
    r = client.post("/ump/get", json={"id": urn})
    assert r.status_code == 200
    assert r.json()["id"] == urn


def test_get_missing_returns_404(md_client):
    client, _urn = md_client
    r = client.get("/ump/get", params={"id": "urn:ump:nothere"})
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "not_found" in detail
    assert "nothere" in detail


def test_capabilities_reports_markdown_binding(md_client):
    client, _ = md_client
    caps = client.get("/ump/capabilities").json()
    assert "markdown_dir" in caps["bindings"]


def test_recall_returns_seeded_card(md_client):
    client, urn = md_client
    r = client.post("/ump/recall", json={"query": "alice@example.org", "limit": 5})
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(rec["id"] == urn for rec in results)


# ---- default-scope owner injection (UMP_OWNER env) ------------------------
#
# The upstream JS reference server's biggest UX pitfall is that recall returns
# {"results": []} on private records unless the caller threads scope.owner
# through every call. The agent has to learn the operator DID out of band.
# UMP_OWNER lets the server inject a default owner when the caller omits it,
# so agents can call recall with just a query and still get results back from
# their own private store.


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setenv("UMP_STORE_KIND", "markdown")
    monkeypatch.setenv("UMP_OWNER", "did:key:z6Mk-test")
    _seed_card(tmp_path)
    app = make_app(str(tmp_path))
    return TestClient(app), CARD_ENV["id"]


def test_capabilities_exposes_default_owner(owner_client):
    """Agents reading capabilities at startup should learn the operator DID
    from the server, not from agent-side hardcoded config."""
    client, _ = owner_client
    caps = client.get("/ump/capabilities").json()
    assert caps.get("default_scope", {}).get("owner") == "did:key:z6Mk-test"


def test_recall_injects_default_owner_when_scope_absent(owner_client):
    """Recall with no scope should still find owner-private records."""
    client, urn = owner_client
    r = client.post("/ump/recall", json={"query": "test", "limit": 5})
    assert r.status_code == 200
    results = r.json()["results"]
    # scope_match should be 1.0 because injected owner matches card owner
    matching = [rec for rec in results if rec["id"] == urn]
    assert matching, "default-scope injection should surface owner-private card"


def test_recall_respects_explicit_owner_over_default(owner_client):
    """An explicit scope.owner in the request must NOT be overridden by the
    server-side default — that would be a security hole (let me query as
    another operator just by setting UMP_OWNER server-side)."""
    client, _urn = owner_client
    # Different owner → card shouldn't match scope, and since this card has
    # no token overlap with "wholly-unrelated-query", overall score won't hit
    # the threshold. So results should be empty.
    r = client.post(
        "/ump/recall",
        json={
            "query": "wholly-unrelated-query-xyzpdq",
            "scope": {"owner": "did:key:z6Mk-someone-else"},
            "limit": 5,
        },
    )
    assert r.status_code == 200
    # Card's owner is "did:key:z6Mk-test", we passed "did:key:z6Mk-someone-else",
    # so scope_match is 0 AND lexical overlap is 0 → card filtered out.
    results = r.json()["results"]
    assert results == []


def test_recall_no_default_owner_falls_back_to_upstream_behavior(tmp_path, monkeypatch):
    """When UMP_OWNER is unset the server should not inject anything —
    behavior matches upstream JS server exactly."""
    monkeypatch.setenv("UMP_STORE_KIND", "markdown")
    monkeypatch.delenv("UMP_OWNER", raising=False)
    _seed_card(tmp_path)
    app = make_app(str(tmp_path))
    client = TestClient(app)
    caps = client.get("/ump/capabilities").json()
    assert "default_scope" not in caps
    # Python MarkdownDirectoryStore is lenient about scope (doesn't enforce
    # visibility=private filtering), so the card still surfaces on token
    # overlap — but capabilities cleanly shows no default is configured.
    r = client.post("/ump/recall", json={"query": "alice@example.org", "limit": 5})
    assert r.status_code == 200
