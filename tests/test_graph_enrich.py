"""Tests for the Intelligence Graph enrichment.

Covers the pure, DB-free helpers in graph/logic and graph/write_adapter:
wikilink/tag extraction and the extended analytics (pagerank, clustering).
These avoid the live Postgres; full-backfill + projection integration lives in
test_integration.py.
"""

from __future__ import annotations


def test_extract_wikilinks_deduplicates():
    from backend.modules.graph.write_adapter import _extract_wikilinks

    content = "[[Alpha]] links to [[Alpha]] and [[Beta Project]] and [[Gamma#sec]]."
    assert _extract_wikilinks(content) == ["Alpha", "Beta Project", "Gamma"]


def test_extract_tags_frontmatter_and_inline():
    from backend.modules.graph.write_adapter import _extract_tags

    content = (
        "---\ntitle: x\ntags: [machine-learning, journal]\n---\n\n"
        "A #journal note about #ml."
    )
    assert "machine-learning" in _extract_tags(content)
    assert "journal" in _extract_tags(content)
    assert "ml" in _extract_tags(content)


def test_date_from_journal_path():
    from backend.modules.graph.write_adapter import _date_from_journal_path

    assert _date_from_journal_path("00 Journal/2026/2026-08-09.md") == "2026-08-09"
    assert _date_from_journal_path("03 Knowledge/foo.md") is None


def test_person_mentions_prefer_explicit_links_and_conservative_prose():
    from backend.modules.relationship.logic import extract_person_mentions

    text = "Met Priya Shah about the launch. [[Rohan Mehta|Rohan]] joined later. The Project update was useful."
    assert extract_person_mentions(text) == ["Rohan Mehta", "Priya Shah"]


def test_person_mentions_match_existing_names_without_creating_projects():
    from backend.modules.relationship.logic import extract_person_mentions

    text = "The Project update was useful and Maya Patel helped with next steps."
    assert extract_person_mentions(text, ["Maya Patel", "Project"]) == ["Maya Patel"]


def test_person_mentions_extract_birthday_and_team_lists():
    from backend.modules.relationship.logic import extract_person_mentions

    text = "Look up birthdays for Sriram, Jynanadeep, Vishnu, Divya, and colleagues. Connected with team: Kian and Grace."
    assert extract_person_mentions(text) == ["Sriram", "Jynanadeep", "Vishnu", "Divya", "Kian", "Grace"]


def test_compute_analytics_pagerank_and_clustering():
    from backend.modules.graph.logic import compute_analytics

    nodes = [
        {"id": "a", "label": "A", "entity_type": "person"},
        {"id": "b", "label": "B", "entity_type": "person"},
        {"id": "c", "label": "C", "entity_type": "person"},
    ]
    edges = [
        {"source_id": "a", "target_id": "b", "edge_type": "x", "weight": 1.0},
        {"source_id": "b", "target_id": "c", "edge_type": "x", "weight": 1.0},
        {"source_id": "a", "target_id": "c", "edge_type": "x", "weight": 1.0},
    ]
    stats = compute_analytics(nodes, edges, "person")
    assert stats["nodes"] == 3
    assert stats["edges"] == 3
    assert len(stats["top_pagerank"]) == 3
    assert all(r["score"] >= 0 for r in stats["top_pagerank"])
    assert 0 <= stats["avg_clustering"] <= 1
    assert stats["top_betweenness"]
    assert all(r["score"] >= 0 for r in stats["top_betweenness"])


def test_compute_analytics_empty_never_raises():
    from backend.modules.graph.logic import compute_analytics

    stats = compute_analytics([], [], "")
    assert stats["nodes"] == 0
    assert stats["edges"] == 0
    assert stats["top_pagerank"] == []
