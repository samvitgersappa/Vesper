---
name: capture
description: "Universal note capture: route any 'remember', 'don't let me forget', 'note to self', 'save this', 'log X' or similar intent through the Knowledge module's single routing decision point. Use for standalone ideas, facts, references, mood/reflection fragments, expenses, workouts, and reminders-with-a-date. When the capture lands as a vault note, WRITE a precise, structured note body — never just echo the raw sentence."
version: 0.2.0
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
decision point (ADDENDUM_SECOND_BRAIN.md §1). The tool classifies the utterance
into the correct store (reminder / expense / workout / journal / vault note)
deterministically and logs every decision to `hermes.capture_routing_log`.

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

### For vault notes (`stored_in: vault_note`) — WRITE A REAL NOTE

The vault is your second brain. A note that merely copies the user's sentence is
not useful later. Before calling `capture`, **write the note body yourself** —
precise, complete, and efficient:

1. **Extract the core fact or idea.** Identify the single most important thing
   being recorded.
2. **Capture critical specifics** — names, dates, amounts, numbers, links,
   people, decisions, and any context that would be lost otherwise. Never drop a
   concrete detail the user mentioned.
3. **Structure it** using the note's natural sections:
   - **The Idea / Summary** — one crisp paragraph capturing the essence.
   - **Key Details** — bullets for specifics (who/what/when/where/how much).
   - **Context / Why it matters** — only if the user implied it; don't invent.
   - **Next steps / Actions** — only if there's a follow-up implied.
4. **Keep it tight.** Prefer short sentences and bullets over prose walls. Be
   precise, not verbose. Omit filler. But never sacrifice a real detail for
   brevity — completeness of facts beats minimalism.
5. Pass the drafted body as `note_body` to `capture`.

### Call signature

- `capture(utterance, conversation_context, note_body)`:
  - `utterance` = the raw user text (verbatim, keep the full phrasing) — this is
    what the router classifies and what the routing log records.
  - `note_body` = your structured markdown draft, used as the note's body when
    the capture is a vault note.
  - `conversation_context` = optional `{}` unless you have relevant context.

### After capture

1. Read the returned `stored_in`, `rule_fired`, and `message` fields.
2. Reply to the user with a concise confirmation that reflects the actual
   `stored_in` (e.g. "Saved a vault note", "Logged as spending", "Added a
   reminder for <date>", "Appended to today's journal").
3. If `stored_in` was a vault note (`vault_note`) or journal, note the `ref_id`
   so follow-up recall can cite it.

## MCP tools used

- `capture(utterance, conversation_context, note_body)`
