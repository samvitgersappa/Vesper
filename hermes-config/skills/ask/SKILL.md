---
name: ask
description: "Answer a question using the Knowledge module (vault search + entity Q&A). Reproduces VesperAIOS /ask."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [knowledge, ask, qa, vault]
    related_skills: [search]
---

# Ask

Reproduces VesperAIOS `/ask <question>` (INVENTORY.md §2.2).

## When to Use

Any free-form question the user wants answered from their own knowledge vault.

## Behavior

1. Call the Knowledge module MCP `knowledge.search` tool with the question.
2. Synthesize a concise answer from the retrieved vault content, citing `file_path` sources.
3. Reply with the answer and its sources (max 4000 chars).

## MCP tools used

- `knowledge.search(query, top_k=5)`
