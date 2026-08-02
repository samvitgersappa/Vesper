---
name: knowledge-architect
description: "Knowledge Architect judgment calls: dedupe/merge/split decisions needing genuine judgment. Reasoning step of plan §9's nightly batch."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [knowledge, architect, dedup, structure]
    cron: "30 2 * * *"
    related_skills: []
---

# Knowledge Architect (judgment calls)

The nightly batch's mechanical parts run as a plain data job (no LLM). This
skill handles only the genuine-judgment step: is this a duplicate, or two
related-but-distinct ideas?

## When to Use

Triggered after the mechanical `knowledge_architect_pass` data job.

## Behavior

1. Receive candidate dedupe/merge/split pairs from the data job (via event or
   a `knowledge` MCP tool).
2. Decide each with reasoning; write the decision back via a `knowledge` MCP tool.
3. Mechanical changes are applied by the data job, not here.
