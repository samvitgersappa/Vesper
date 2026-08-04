---
name: capture
description: "Universal note capture: route any 'remember', 'don't let me forget', 'note to self', 'save this', 'log X' or similar intent through the Knowledge module's single routing decision point. Use for standalone ideas, facts, references, mood/reflection fragments, expenses, workouts, and reminders-with-a-date. When the capture lands as a vault note, WRITE a precise, structured note body with Obsidian wikilinks — never just echo the raw sentence."
version: 0.3.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [capture, remember, note, inbox, second-brain, knowledge, graph]
    related_skills: [journal, ask, search, people]
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

### For vault notes (`stored_in: vault_note`) — WRITE A CONNECTED NOTE

The vault is your second brain. A note that merely copies the user's sentence is
not useful later. Before calling `capture`, **write the note body yourself** —
precise, complete, and **linked into the knowledge graph**:

1. **Extract the core fact or idea.**
2. **Capture critical specifics** — names, dates, amounts, numbers, links,
   people, decisions, and any context that would be lost otherwise.
3. **Search for related notes.** Use `knowledge.search` (or `search_files`
   in the vault) to find existing notes that mention the same people, topics,
   or projects. Do this before writing — a note with zero links is an island.
4. **Write wikilinks for EVERY person, project, and topic** that has an existing
   note in the vault. Use the exact filename stem as the link target
   (e.g. `[[dheeraj]]` for `05 People/dheeraj.md`, `[[cat-quant-plan]]` for
   `04 Learning/cat-quant-plan.md`). Quartz and Obsidian render these as graph
   edges, so every link matters.
5. **Create stub People notes for NEW people.** If the user mentions someone who
   has no vault note yet, create a one-paragraph stub under `05 People/` with
   the person's name as filename (e.g. `05 People/aarav.md`). The stub should
   have at minimum: full name, context (how you know them), and any details the
   user provided. Then wikilink to it from the main note.
6. **Use specific, consistent tags** in the frontmatter. Prefer lowercase,
   hyphen-separated tags that align with the vault areas: `people`, `friends`,
   `colleagues`, `travel`, `learning`, `finance`, `trading`, `rust`, `health`,
   `career`, `cat`, `projects`, `ideas`, `journal`. Never use the tag `test`
   in the actual capture — TEST_ is a note-title prefix, not a tag.
7. **Structure the body:**
   - **The Idea / Summary** — one crisp paragraph.
   - **Key Details** — bullets for specifics (who/what/when/where/how much),
     each person name should be a wikilink.
   - **Related** — wikilinks to existing vault notes (found in step 3).
   - **Next steps / Actions** — only if there's a clear follow-up.
8. Pass the drafted body as `note_body` to `capture`.

### Call signature

- `capture(utterance, conversation_context, note_body)`:
  - `utterance` = the raw user text (verbatim, keep the full phrasing) — this is
    what the router classifies and what the routing log records.
  - `note_body` = your structured markdown draft, used as the note's body when
    the capture is a vault note.
  - `conversation_context` = optional `{}` unless you have relevant context.

### After capture

1. Read the returned `stored_in`, `rule_fired`, and `message` fields.
2. Reply to the user with a concise confirmation.
3. If `stored_in` was a vault note, mention the ref_id and any wikilinks
   created so the user knows the connections.

## MCP tools used

- `capture(utterance, conversation_context, note_body)`
- `knowledge.search` — find related notes to link to (use BEFORE writing)
