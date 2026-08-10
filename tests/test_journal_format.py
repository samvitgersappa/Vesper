"""Tests for the journal markdown formatting & enrichment module.

These verify the graph-optimisation guarantees: rich frontmatter, prev/next
chronology links, `## Connected` wikilink block, idempotency, and autolinking
to existing vault people/topic notes.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.modules.journal import format as fmt

D = date(2026, 8, 9)


def test_render_frontmatter_includes_graph_fields():
    fm = fmt.render_frontmatter(D, mood="good", tags=["focus"])
    assert "title: 2026-08-09" in fm
    assert "type: journal" in fm
    assert "mood: good" in fm
    assert "tags: [focus, journal, daily]" in fm
    assert "aliases:" in fm and "2026-08-09" in fm
    assert "date: 2026-08-09" in fm
    assert "confidence: 1.0" in fm


def test_render_new_note_has_sections_and_chronology():
    note = fmt.render_new_note(D)
    assert "# 2026-08-09" in note
    assert "← prev]]" in note and "next →" in note
    assert "[[2026-08-08" in note and "[[2026-08-10" in note
    for section in ("## Mood", "## Highlights", "## Learning",
                    "## Expenses", "## Connected", "## Tomorrow"):
        assert section in note


def test_extract_wikilinks_strips_alias_and_heading():
    content = "[[Divya]] met [[Alpha Project|project]] — also [[Note#Heading]]."
    assert fmt.extract_wikilinks(content) == ["Divya", "Alpha Project", "Note"]


def test_enrich_markdown_upgrades_flat_entries():
    flat = "# 2026-08-09\n\nGreat day. Met Divya.\n"
    out, changed = fmt.enrich_markdown(flat, D)
    assert changed is True
    assert "title: 2026-08-09" in out
    assert "tags: [journal, daily]" in out
    assert "[[2026-08-08|← prev]]" in out
    assert "## Connected" in out


def test_enrich_markdown_is_idempotent():
    note = fmt.render_new_note(D)
    once, changed1 = fmt.enrich_markdown(note, D)
    twice, changed2 = fmt.enrich_markdown(once, D)
    assert changed1 is False or changed1 is True
    assert changed2 is False
    assert once == twice


def test_enrich_preserves_existing_mood_and_tags():
    flat = (
        "---\nmood: anxious\ntags: [work, deep-dive]\n---\n\n"
        "# 2026-08-09\n\nRough day at work.\n"
    )
    out, _ = fmt.enrich_markdown(flat, D)
    assert "mood: anxious" in out
    assert "tags: [work, deep-dive, journal, daily]" in out


def test_auto_targets_links_existing_people_notes(tmp_path, monkeypatch):
    people = tmp_path / "05 People"
    people.mkdir(parents=True)
    (people / "Divya.md").write_text("# Divya\n\nCousin.\n")
    (tmp_path / "03 Knowledge").mkdir(parents=True)
    (tmp_path / "03 Knowledge" / "datahub.md").write_text("# DataHub\n")

    body = "Today I worked with Divya and read up on DataHub."
    rels = fmt.related_links(body, tmp_path)
    assert "Divya" in rels
    assert "datahub" in rels


def test_render_nav_uses_iso_dates():
    nav = fmt.render_nav(D)
    assert "2026-08-08" in nav
    assert "2026-08-10" in nav