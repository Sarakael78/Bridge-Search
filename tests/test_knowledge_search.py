from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bridge_search import config as bridge_config
from bridge_search.knowledge_search import search_approved_knowledge


def _configure(monkeypatch, tmp_path: Path, root: Path) -> None:
    config_path = tmp_path / "bridge-search.config.json"
    config_path.write_text(
        json.dumps(
            {
                "knowledge_roots": {
                    "hermes_agent_brain": {
                        "path": str(root),
                        "classification": "internal-derivative",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BRIDGE_SEARCH_CONFIG", str(config_path))
    bridge_config.get_bridge_config(reload=True)


def test_search_approved_knowledge_returns_provenance(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    note = root / "Architecture.md"
    payload = b"# Architecture\nLive artefacts outrank notes before a current-state claim.\n"
    note.write_bytes(payload)
    _configure(monkeypatch, tmp_path, root)

    result = search_approved_knowledge("live artefacts outrank notes")

    assert result["success"] is True
    assert len(result["results"]) == 1
    hit = result["results"][0]
    assert hit["path"] == str(note)
    assert hit["line_number"] == 2
    assert hit["sha256"] == hashlib.sha256(payload).hexdigest()
    assert hit["classification"] == "internal-derivative"
    assert hit["read_only"] is True


def test_search_approved_knowledge_never_crosses_configured_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "inside.md").write_text("bounded needle", encoding="utf-8")
    (tmp_path / "outside.md").write_text("bounded needle", encoding="utf-8")
    _configure(monkeypatch, tmp_path, root)

    result = search_approved_knowledge("bounded needle")

    assert [Path(hit["path"]).name for hit in result["results"]] == ["inside.md"]


def test_search_approved_knowledge_skips_hidden_and_non_markdown(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    hidden = root / ".obsidian"
    hidden.mkdir()
    (hidden / "private.md").write_text("secret needle", encoding="utf-8")
    (root / "note.txt").write_text("secret needle", encoding="utf-8")
    _configure(monkeypatch, tmp_path, root)

    result = search_approved_knowledge("secret needle")

    assert result["success"] is True
    assert result["results"] == []


def test_search_approved_knowledge_skips_symlinked_file_outside_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("external needle", encoding="utf-8")
    (root / "linked.md").symlink_to(outside)
    _configure(monkeypatch, tmp_path, root)

    result = search_approved_knowledge("external needle")

    assert result["success"] is True
    assert result["results"] == []


@pytest.mark.parametrize("incomplete_reason", ["result_limit", "unreadable_file"])
def test_incomplete_search_does_not_claim_an_exact_total(monkeypatch, tmp_path: Path, incomplete_reason: str) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "first.md").write_text("bounded needle", encoding="utf-8")
    if incomplete_reason == "result_limit":
        (root / "second.md").write_text("bounded needle", encoding="utf-8")
        (root / "third.md").write_text("bounded needle", encoding="utf-8")
    else:
        (root / "invalid.md").write_bytes(b"\xff")
    _configure(monkeypatch, tmp_path, root)

    result = search_approved_knowledge("bounded needle", limit=1)

    assert result["meta"]["returned_count"] == 1
    assert result["meta"]["total_found_exact"] is False
    assert result["meta"]["has_more"] is (incomplete_reason == "result_limit")


def test_exact_limit_without_more_matches_remains_complete(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "only.md").write_text("bounded needle", encoding="utf-8")
    _configure(monkeypatch, tmp_path, root)
    result = search_approved_knowledge("bounded needle", limit=1)
    assert result["meta"]["returned_count"] == result["meta"]["total_found"] == 1
    assert result["meta"]["has_more"] is False
    assert result["meta"]["total_found_exact"] is True


def test_approved_root_still_honours_a_denied_descendant(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    allowed = root / "public.md"
    blocked = root / "restricted.md"
    allowed.write_text("bounded needle", encoding="utf-8")
    blocked.write_text("bounded needle", encoding="utf-8")
    _configure(monkeypatch, tmp_path, root)
    config_path = tmp_path / "bridge-search.config.json"
    data = json.loads(config_path.read_text())
    data["security"] = {
        "path_denylist": "custom",
        "custom_restricted_prefixes": [str(blocked)],
    }
    config_path.write_text(json.dumps(data), encoding="utf-8")
    bridge_config.get_bridge_config(reload=True)
    original_read = Path.read_bytes
    reads = []

    def record_read(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)
    result = search_approved_knowledge("bounded needle")
    assert [hit["path"] for hit in result["results"]] == [str(allowed)]
    assert blocked not in reads


def test_directory_read_failure_keeps_total_inexact(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "public.md").write_text("bounded needle", encoding="utf-8")
    closed = root / "closed"
    closed.mkdir()
    _configure(monkeypatch, tmp_path, root)
    original_scandir = os.scandir

    def deny_one_directory(path):
        if Path(path) == closed:
            raise PermissionError("Synthetic directory read failure")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_one_directory)
    result = search_approved_knowledge("bounded needle")
    assert result["meta"]["returned_count"] == 1
    assert result["meta"]["total_found_exact"] is False
    assert result["meta"]["enumeration_errors"] == 1
