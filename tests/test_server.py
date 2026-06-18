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
