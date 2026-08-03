---
name: capture
description: "Universal note capture: route any 'remember', 'don't let me forget', 'note to self', 'save this', 'log X' or similar intent through the Knowledge module's single routing decision point. Use for standalone ideas, facts, references, mood/reflection fragments, expenses, workouts, and reminders-with-a-date."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [capture, remember, note, inbox, second-brain, knowledge]
    related_skills: [journal, ask, search]
---

# Capture

Routes casual "remember this" / "don't let me forget" / "note to self" / "save
this" utterances through `knowledge.capture` — the single capture-routing
decision point (ADDENDUM_SECOND_BRAIN.md §1). This is NOT an ordinary "save a
note" write: the tool classifies the utterance into the correct store
(reminder / expense / workout / journal / vault note) deterministically and logs
every decision to `hermes.capture_routing_log`.

## When to Use

Use whenever a turn contains capture intent — "remember," "note," "don't let me
forget," "save this," "log this," "I should," a standalone idea, a fact to keep,
a mood/reflection fragment, money spent, or a workout done. This applies even
when the capture intent is attached to other content (e.g. "met X for coffee,
remind me to follow up in two weeks").

Do NOT route through this skill for: reading/writing today's full journal entry
(use the `journal` skill), looking up contacts (use `people`), or answering a
question from the vault (use `ask`/`search`).

## Behavior

1. Call Knowledge MCP `capture` with:
   - `utterance` = the raw user text (verbatim, keep the full phrasing),
   - `conversation_context` = optional `{}` unless you have relevant context.
2. Read the returned `stored_in`, `rule_fired`, and `message` fields.
3. Reply to the user with a concise confirmation that reflects the actual
   `stored_in` (e.g. "Saved a vault note", "Logged as spending", "Added a
   reminder for <date>", "Appended to today's journal").
4. If `stored_in` was a vault note (`vault_note`) or journal, note the `ref_id`
   so follow-up recall can cite it.

## MCP tools used

- `capture(utterance, conversation_context)`
