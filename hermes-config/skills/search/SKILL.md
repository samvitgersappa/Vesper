---
name: search
description: "Full-text search across the Obsidian vault (Knowledge module). Reproduces VesperAIOS /search and /note."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [search, knowledge, vault, notes]
    related_skills: [ask]
---

# Search

Reproduces VesperAIOS `/search <query>` and `/note <title>` (INVENTORY.md §2.2).

## When to Use

User wants to find notes/vault content by keyword or title.

## Behavior

1. Call the Knowledge module MCP `knowledge.search` tool (and note lookup for titles).
2. Return results as: `🔍 Found N results:` + content preview (`content[:120]`) + `📄 file_path`.
3. Empty → "No results found."; cap at 4000 chars.

## MCP tools used

- `knowledge.search(query, top_k=5)`
- `knowledge.note_content(path)`
