---
name: journal
description: "Read/write journal entries backed by the Obsidian vault (Journal module). Reproduces VesperAIOS /journal."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [journal, diary, mood, vault]
    related_skills: []
---

# Journal

Reproduces VesperAIOS `/journal` (INVENTORY.md §2.2) and the vault-backed journal
(plan §8.3).

## When to Use

User wants to read or write today's journal entry, or log a mood.

## Behavior

1. Read: call Journal MCP `journal.get_entry(date=today)` → `📅 YYYY-MM-DD` + content.
2. Write: call `journal.write_entry(text, mood, source)` — content is written to the
   vault markdown file; the `diary_entries` metadata row is updated by the vault-sync
   handler (Phase 4), not by this skill directly.
3. No entry → "No journal entry for {date}."

## MCP tools used

- `journal.get_entry(date)`
- `journal.write_entry(text, mood, source)`
