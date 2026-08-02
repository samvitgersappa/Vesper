---
name: people
description: "Look up CRM contacts via the Relationship module. Reproduces VesperAIOS /people."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [crm, people, relationships, contacts]
    related_skills: []
---

# People

Reproduces VesperAIOS `/people` (INVENTORY.md §2.2).

## When to Use

User asks about their contacts/CRM (search, list, details, due follow-ups).

## Behavior

1. Call Relationship MCP tools: `relationship.search(query)` or `relationship.person_detail(person_id)`.
2. List format: `👥 Contacts:` + `• name — company [category]` (max 10).
3. Empty → "No contacts in CRM."

## MCP tools used

- `relationship.search(query)`
- `relationship.person_detail(person_id)`
